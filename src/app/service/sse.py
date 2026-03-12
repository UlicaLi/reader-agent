"""
SSE (Server-Sent Events) 服务
用于实时推送消息到客户端
支持 Redis 作为消息代理，用于多服务器部署
"""
import asyncio
import json
import logging
from typing import Dict, Set, Optional, Any
from datetime import datetime, timezone
import threading
import uuid
from fastapi import Request
from fastapi.responses import StreamingResponse
import redis.asyncio as redis

from app.config import REDIS_SSE_URL, REDIS_SSE_PASSWORD

logger = logging.getLogger(__name__)


class SSEConnection:
    """SSE 连接管理"""
    
    def __init__(self, user_id: int, queue: asyncio.Queue, connection_id: str = None):
        self.user_id = user_id
        self.queue = queue
        self.connection_id = connection_id or str(uuid.uuid4())
        self.connected_at = datetime.now(timezone.utc)
        self.last_ping = datetime.now(timezone.utc)


class RedisSSEManager:
    """基于 Redis 的 SSE 连接管理器，支持多服务器部署"""
    
    def __init__(self):
        # 本地连接存储（仅当前服务器实例）
        self.local_connections: Dict[int, Set[SSEConnection]] = {}
        self.local_lock = asyncio.Lock()
        
        # Redis 连接
        self.redis_pool = None
        # 监听来自其他服务器实例的消息
        self.pubsub = None
        self.server_id = str(uuid.uuid4())  # 当前服务器实例ID
        
        # 消息监听任务
        self._listen_task = None
        self._initialized = False
    
    async def _ensure_redis_connection(self):
        """确保 Redis 连接已建立"""
        if not self._initialized:
            try:
                # 清理旧连接
                if self.pubsub:
                    try:
                        await self.pubsub.close()
                    except:
                        pass
                    self.pubsub = None
                
                if self.redis_pool:
                    try:
                        await self.redis_pool.close()
                    except:
                        pass
                    self.redis_pool = None
                
                # 使用 SSE 专用的 Redis 配置
                redis_url = REDIS_SSE_URL
                if REDIS_SSE_PASSWORD:
                    # 如果有密码，需要在 URL 中包含密码
                    url_parts = redis_url.split('://')
                    if len(url_parts) == 2:
                        scheme, rest = url_parts
                        # 密码前有冒号 :，表示没有用户名
                        redis_url = f"{scheme}://:{REDIS_SSE_PASSWORD}@{rest}"
                
                logger.info(f"尝试连接 Redis: {redis_url}")
                
                self.redis_pool = redis.from_url(
                    redis_url,
                    encoding="utf-8",
                    decode_responses=True,
                    max_connections=20,
                    retry_on_timeout=True,
                    socket_connect_timeout=5,
                    socket_timeout=5
                )
                
                # 测试连接
                await self.redis_pool.ping()
                logger.info("Redis 连接测试成功")
                
                # 初始化 pub/sub
                self.pubsub = self.redis_pool.pubsub()
                await self.pubsub.subscribe("sse_messages")
                logger.info("Redis pubsub 订阅成功")
                
                # 启动消息监听任务（如果还没有启动）
                if not self._listen_task or self._listen_task.done():
                    self._listen_task = asyncio.create_task(self._listen_for_messages())
                    logger.info("Redis 消息监听任务已启动")
                
                self._initialized = True
                logger.info(f"Redis SSE Manager 初始化成功, 服务器ID: {self.server_id}")
                
            except Exception as e:
                logger.error(f"Redis SSE Manager 初始化失败: {e}")
                # 降级到本地模式
                self._initialized = False
                self.pubsub = None
                self.redis_pool = None
    
    async def _listen_for_messages(self):
        """监听 Redis pub/sub 消息"""
        try:
            while True:
                # 检查 pubsub 连接是否有效
                if not self.pubsub:
                    logger.warning("Redis pubsub 连接不存在，尝试重新初始化")
                    await asyncio.sleep(5)  # 等待5秒后重试
                    continue
                
                try:
                    message = await self.pubsub.get_message(timeout=1.0)
                    if message and message['type'] == 'message':
                        try:
                            data = json.loads(message['data'])
                            # 只处理来自其他服务器的消息
                            if data.get('server_id') != self.server_id:
                                await self._handle_redis_message(data)
                        except json.JSONDecodeError as e:
                            logger.error(f"Redis 消息解析失败: {e}")
                        except Exception as e:
                            logger.error(f"处理 Redis 消息失败: {e}")
                except Exception as e:
                    logger.error(f"获取 Redis 消息失败: {e}")
                    # 如果是连接错误，尝试重新连接
                    if "connection" in str(e).lower() or "pubsub" in str(e).lower():
                        logger.info("检测到连接问题，尝试重新初始化 Redis 连接")
                        self._initialized = False
                        await self._ensure_redis_connection()
                    await asyncio.sleep(1)  # 短暂等待后继续
                    
        except asyncio.CancelledError:
            logger.info("Redis 消息监听任务已取消")
        except Exception as e:
            logger.error(f"Redis 消息监听错误: {e}")
    
    async def _handle_redis_message(self, data: dict):
        """处理来自 Redis 的消息"""
        try:
            message_type = data.get('type')
            if message_type == 'user_message':
                user_id = data.get('user_id')
                event_type = data.get('event_type')
                message_data = data.get('data')
                
                if user_id and event_type and message_data is not None:
                    await self._send_to_local_user(user_id, event_type, message_data)
                    
        except Exception as e:
            logger.error(f"处理 Redis 消息失败: {e}")
    
    async def _send_to_local_user(self, user_id: int, event_type: str, data: Any):
        """向本地连接的用户发送消息"""
        async with self.local_lock:
            if user_id not in self.local_connections:
                return
            
            connections = list(self.local_connections[user_id])
        
        # 构造 SSE 消息
        message = {
            "type": event_type,
            "data": data,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
        # 发送到用户的所有本地连接
        disconnected = []
        success_count = 0
        for connection in connections:
            try:
                await connection.queue.put(message)
                success_count += 1
            except Exception as e:
                logger.error(f"向用户 {user_id} 发送本地消息失败: {e}")
                disconnected.append(connection)
        
        if success_count > 0:
            logger.info(f"成功向用户 {user_id} 的 {success_count} 个本地连接发送消息")
        
        # 清理断开的连接
        if disconnected:
            await self._cleanup_disconnected_connections(user_id, disconnected)
    
    async def _cleanup_disconnected_connections(self, user_id: int, disconnected: list):
        """清理断开的连接"""
        async with self.local_lock:
            if user_id in self.local_connections:
                for conn in disconnected:
                    self.local_connections[user_id].discard(conn)
                if not self.local_connections[user_id]:
                    del self.local_connections[user_id]
    
    async def _publish_message(self, message_type: str, **kwargs):
        """发布消息到 Redis"""
        if not self._initialized:
            await self._ensure_redis_connection()
        
        if self.redis_pool:
            try:
                message = {
                    'type': message_type,
                    'server_id': self.server_id,
                    'timestamp': datetime.now(timezone.utc).isoformat(),
                    **kwargs
                }
                await self.redis_pool.publish("sse_messages", json.dumps(message))
                logger.debug(f"成功发布 Redis 消息: {message_type}")
            except Exception as e:
                logger.error(f"发布 Redis 消息失败: {e}")
                # 如果是连接错误，标记需要重新初始化
                if "connection" in str(e).lower():
                    logger.info("检测到 Redis 连接问题，标记需要重新初始化")
                    self._initialized = False
        else:
            logger.warning(f"Redis 连接不可用，无法发布消息: {message_type}")
    
    async def connect(self, user_id: int) -> SSEConnection:
        """建立新的 SSE 连接"""
        await self._ensure_redis_connection()
        
        queue = asyncio.Queue()
        connection = SSEConnection(user_id, queue)
        
        async with self.local_lock:
            if user_id not in self.local_connections:
                self.local_connections[user_id] = set()
            self.local_connections[user_id].add(connection)
        
        logger.info(f"用户 {user_id} 通过 SSE 连接到服务器 {self.server_id}")
        return connection
    
    async def disconnect(self, user_id: int, connection: SSEConnection):
        """断开 SSE 连接"""
        async with self.local_lock:
            if user_id in self.local_connections:
                self.local_connections[user_id].discard(connection)
                if not self.local_connections[user_id]:
                    del self.local_connections[user_id]
        
        logger.info(f"用户 {user_id} 从服务器 {self.server_id} 断开 SSE 连接")
    
    async def send_to_user(self, user_id: int, event_type: str, data: Any):
        """向特定用户发送消息（跨服务器）"""
        logger.info(f"尝试向用户 {user_id} 发送消息类型: {event_type}")
        
        # 先发送给本地连接
        await self._send_to_local_user(user_id, event_type, data)
        
        # 然后通过 Redis 发送给其他服务器实例
        await self._publish_message(
            'user_message',
            user_id=user_id,
            event_type=event_type,
            data=data
        )
        
        logger.info(f"消息已发送给用户 {user_id}，类型: {event_type}")
    
    async def broadcast_message(self, sender_id: int, receiver_id: int, message_data: dict):
        """广播新私信消息"""
        logger.info(f"广播私信消息: 发送者 {sender_id} -> 接收者 {receiver_id}")
        
        # 发送给发送者（确认发送成功）
        await self.send_to_user(sender_id, "message_sent", message_data)
        
        # 发送给接收者（新消息通知）
        await self.send_to_user(receiver_id, "new_message", message_data)
        
        logger.info(f"私信消息广播完成: 发送者 {sender_id} -> 接收者 {receiver_id}")
    
    async def notify_message_read(self, user_id: int, other_user_id: int):
        """通知消息已读"""
        logger.info(f"通知消息已读: 用户 {user_id}, 对方用户 {other_user_id}")
        await self.send_to_user(user_id, "messages_read", {
            "other_user_id": other_user_id
        })
    
    async def get_connection_count(self) -> int:
        """获取当前服务器的连接数"""
        async with self.local_lock:
            return sum(len(conns) for conns in self.local_connections.values())
    
    async def get_user_connection_count(self, user_id: int) -> int:
        """获取指定用户在当前服务器的连接数"""
        async with self.local_lock:
            return len(self.local_connections.get(user_id, set()))
    
    async def get_global_stats(self) -> dict:
        """获取全局统计信息"""
        local_count = await self.get_connection_count()
        
        # 尝试从 Redis 获取全局统计
        total_servers = 1
        if self.redis_pool:
            try:
                # 这里可以扩展为更复杂的全局统计逻辑
                # 例如定期将统计信息写入 Redis
                pass
            except Exception as e:
                logger.error(f"获取全局统计失败: {e}")
        
        return {
            "local_connections": local_count,
            "server_id": self.server_id,
            "redis_connected": self._initialized,
            "total_servers": total_servers
        }
    
    async def close(self):
        """关闭管理器"""
        if self._listen_task:
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass
        
        if self.pubsub:
            await self.pubsub.close()
        
        if self.redis_pool:
            await self.redis_pool.close()
        
        logger.info(f"Redis SSE Manager 已关闭 (服务器: {self.server_id})")


# 向后兼容的旧式管理器（已弃用，但保留以防有代码依赖）
class SSEManager:
    """旧式 SSE 连接管理器（已弃用，请使用 RedisSSEManager）"""
    
    def __init__(self):
        logger.warning("SSEManager 已弃用，请使用 RedisSSEManager 以支持多服务器部署")
        self.redis_manager = RedisSSEManager()
    
    async def connect(self, user_id: int) -> SSEConnection:
        return await self.redis_manager.connect(user_id)
    
    async def disconnect(self, user_id: int, connection: SSEConnection):
        return await self.redis_manager.disconnect(user_id, connection)
    
    async def send_to_user(self, user_id: int, event_type: str, data: Any):
        return await self.redis_manager.send_to_user(user_id, event_type, data)
    
    async def broadcast_message(self, sender_id: int, receiver_id: int, message_data: dict):
        return await self.redis_manager.broadcast_message(sender_id, receiver_id, message_data)
    
    async def notify_message_read(self, user_id: int, other_user_id: int):
        return await self.redis_manager.notify_message_read(user_id, other_user_id)
    
    async def get_connection_count(self) -> int:
        return await self.redis_manager.get_connection_count()
    
    async def get_user_connection_count(self, user_id: int) -> int:
        return await self.redis_manager.get_user_connection_count(user_id)


# 全局 SSE 管理器实例（使用 Redis 支持）
sse_manager = RedisSSEManager()


async def create_sse_response(user_id: int, request: Request) -> StreamingResponse:
    """创建 SSE 响应流"""
    
    connection = await sse_manager.connect(user_id)
    
    async def event_stream():
        try:
            # 发送连接成功消息
            yield f"data: {json.dumps({'type': 'connected', 'message': 'SSE connection established', 'server_id': sse_manager.server_id})}\n\n"
            
            while True:
                # 检查客户端是否断开连接
                if await request.is_disconnected():
                    break
                
                try:
                    # 等待新消息（带超时的心跳）
                    message = await asyncio.wait_for(connection.queue.get(), timeout=30.0)
                    yield f"data: {json.dumps(message)}\n\n"
                    
                except asyncio.TimeoutError:
                    # 发送心跳
                    heartbeat = {
                        "type": "heartbeat",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "server_id": sse_manager.server_id
                    }
                    yield f"data: {json.dumps(heartbeat)}\n\n"
                    connection.last_ping = datetime.now(timezone.utc)
                    
        except Exception as e:
            logger.error(f"SSE 流异常: {e}")
        finally:
            await sse_manager.disconnect(user_id, connection)
    
    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # 禁用 nginx 缓冲
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Cache-Control"
        }
    ) 