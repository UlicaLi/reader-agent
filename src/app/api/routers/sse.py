"""
SSE (Server-Sent Events) API 端点
支持多服务器部署的 Redis-based SSE
"""
import json
import asyncio
import logging
import requests
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Request, HTTPException, status
from fastapi.responses import StreamingResponse

from app.service.sse import sse_manager
from app.service.task_service import get_task_by_uuid
from app.db.models import TaskStatus, TaskSteps
from app.api.middleware import extract_access_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sse", tags=["sse"])

def convert_task_message_to_sse_format(message_data: dict) -> dict:
    """将内部任务消息转换为SSE格式"""
    
    # 获取步骤和状态
    step = message_data.get("step", "")
    progress = message_data.get("progress", 0)
    message = message_data.get("message", "")
    
    # 状态映射
    if step == TaskSteps.COMPLETED:
        status = "completed"
    elif step == TaskSteps.ERROR:
        status = "failed"
    else:
        status = "processing"
    
    return {
        "status": status,
        "step": step,
        "progress": progress,
        "message": message
    }


@router.get("/progress/{task_uuid}")
async def document_progress_sse(
    request: Request,
    task_uuid: Optional[str] = None
):
    """
    文档解析进度SSE接口
    
    Args:
        task_uuid: 可选的任务UUID，如果指定则只监控该任务
    
    Returns:
        SSE流，消息格式：
        {
            "status": "processing|completed|failed",
            "step": "任务步骤（使用TaskSteps常量）", 
            "progress": 50,
            "message": "详细消息"
        }
    """
    access_token = extract_access_token(request.headers.get("Authorization"))
    api_url = f"https://api.noread.pro/api/v1/auth/user?access_token={access_token}"
    response = requests.get(api_url)
    
    if response.status_code != 200:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未授权"
        )
    
    user_id = str(response.json().get("user_id"))
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户不存在"
        )

    # 如果指定了task_uuid，验证任务存在和权限
    if task_uuid:
        task = get_task_by_uuid(task_uuid)
        if not task:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="任务不存在"
            )
        logger.info(f"task.user_uuid: {task.user_uuid}, type(task.user_uuid): {type(task.user_uuid)}, user_id: {user_id}, type(user_id): {type(user_id)}")
        if task.user_uuid != user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="无权限访问此任务"
            )
    
    # 建立SSE连接
    connection = await sse_manager.connect(user_id)
    
    async def event_stream():
        try:
            # 如果指定了task_uuid，发送当前任务状态
            if task_uuid:
                current_task = get_task_by_uuid(task_uuid)
                if current_task:
                    # 根据任务状态确定步骤
                    if current_task.status == TaskStatus.COMPLETED:
                        current_step = TaskSteps.COMPLETED
                    elif current_task.status in [TaskStatus.FAILED, TaskStatus.CANCELLED]:
                        current_step = TaskSteps.ERROR
                    else:
                        # 从任务消息或进度推断当前步骤
                        current_step = TaskSteps.OCR_PROCESSING 
                    
                    initial_message = convert_task_message_to_sse_format({
                        "step": current_step,
                        "progress": current_task.progress,
                        "message": current_task.message or "任务进行中"
                    })
                    yield f"data: {json.dumps(initial_message)}\n\n"
            
            while True:
                # 检查客户端连接
                if await request.is_disconnected():
                    break

                try:
                    # 等待新消息，OCR处理时间较长，使用更长的超时时间
                    message = await asyncio.wait_for(connection.queue.get(), timeout=300.0)
                    
                    # 过滤消息：只处理任务进度相关的消息
                    if message.get("type") == "task_progress":
                        data = message.get("data", {})
                        msg_task_uuid = data.get("task_uuid")
                        
                        # 如果指定了task_uuid，只推送该任务的消息
                        if task_uuid and msg_task_uuid != task_uuid:
                            continue
                            
                        # 转换消息格式
                        sse_message = convert_task_message_to_sse_format(data)
                        yield f"data: {json.dumps(sse_message)}\n\n"
                        
                except asyncio.TimeoutError:
                    # 心跳消息，OCR处理时间长，心跳间隔也相应延长
                    heartbeat = {
                        "status": "processing",
                        "step": "heartbeat",
                        "progress": -1,  # -1 表示心跳
                        "message": "连接正常"
                    }
                    yield f"data: {json.dumps(heartbeat)}\n\n"
                    
        except Exception as e:
            logger.error(f"文档进度SSE流异常: {e}")
            # 错误消息
            error_message = {
                "status": "failed",
                "step": TaskSteps.ERROR,
                "progress": 0,
                "message": f"连接异常: {str(e)}"
            }
            yield f"data: {json.dumps(error_message)}\n\n"
        finally:
            await sse_manager.disconnect(user_id, connection)
    
    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive", 
            "X-Accel-Buffering": "no",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Cache-Control"
        }
    )