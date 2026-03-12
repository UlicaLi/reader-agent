import json
import asyncio
from datetime import datetime
from fastapi import APIRouter, Request, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.schemas import TaskResponse
from app.db.session import get_db
from app.db.models import Task, TaskStatus
from app.service.sse import sse_manager
from app.tasks.worker import celery
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tasks", tags=["tasks"])




@router.get("/{task_uuid}", response_model=TaskResponse, summary="查询任务详情")
async def get_task(
    task_uuid: str,
    db: Session = Depends(get_db)
):
    """
    查询任务详情
    
    - **task_uuid**: 任务UUID
    
    返回任务的详细信息
    """
    task = db.query(Task).filter(Task.uuid == task_uuid).first()
    
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="任务不存在"
        )
    
    return task


@router.get("/{task_uuid}/progress", summary="SSE实时进度监控")
async def monitor_task_progress(
    request: Request,
    task_uuid: str,
    user_uuid: str,
    db: Session = Depends(get_db)
):
    """
    通过SSE实时监控任务进度
    
    - **task_uuid**: 任务UUID
    - **user_uuid**: 用户UUID（查询参数）
    
    返回SSE流，实时推送任务进度更新
    """
    # 验证任务存在
    task = db.query(Task).filter(Task.uuid == task_uuid).first()
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="任务不存在"
        )
    
    # 验证用户权限
    if task.user_uuid != user_uuid:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="无权限访问此任务"
        )
    
    # 建立SSE连接
    connection = await sse_manager.connect(user_uuid)
    
    async def event_stream():
        try:
            # 发送当前任务状态
            current_status = {
                "type": "task_status",
                "data": {
                    "task_uuid": task_uuid,
                    "status": task.status,
                    "progress": task.progress,
                    "message": task.message,
                    "timestamp": datetime.now().isoformat()
                }
            }
            yield f"data: {json.dumps(current_status)}\n\n"
            
            while True:
                # 检查客户端是否断开连接
                if await request.is_disconnected():
                    break
                
                try:
                    # 等待新消息
                    message = await asyncio.wait_for(connection.queue.get(), timeout=30.0)
                    
                    # 只推送与当前任务相关的消息
                    if (message.get("type") == "task_progress" and 
                        message.get("data", {}).get("task_uuid") == task_uuid):
                        yield f"data: {json.dumps(message)}\n\n"
                    elif message.get("type") in ["task_started", "task_completed", "task_failed"]:
                        yield f"data: {json.dumps(message)}\n\n"
                    
                except asyncio.TimeoutError:
                    # 发送心跳
                    heartbeat = {
                        "type": "heartbeat",
                        "timestamp": datetime.now().isoformat()
                    }
                    yield f"data: {json.dumps(heartbeat)}\n\n"
                    
        except Exception as e:
            logger.error(f"任务进度SSE流异常: {e}")
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


@router.delete("/{task_uuid}", summary="取消任务")
async def cancel_task(
    task_uuid: str,
    user_uuid: str,
    db: Session = Depends(get_db)
):
    """
    取消正在运行的任务
    
    - **task_uuid**: 任务UUID
    - **user_uuid**: 用户UUID（查询参数）
    """
    # 验证任务存在和权限
    task = db.query(Task).filter(Task.uuid == task_uuid).first()
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="任务不存在"
        )
    
    if task.user_uuid != user_uuid:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="无权限操作此任务"
        )
    
    try:
        # 取消Celery任务
        output_data = json.loads(task.output or "{}")
        celery_task_id = output_data.get("celery_task_id")
        
        if celery_task_id:
            celery.control.revoke(celery_task_id, terminate=True)
        
        # 更新任务状态
        task.status = TaskStatus.CANCELLED
        task.message = "任务已被用户取消"
        task.finished_at = datetime.now()
        db.commit()
        
        # 发送取消通知
        await sse_manager.send_to_user(
                user_id=user_uuid,
                event_type="task_cancelled",
                data={
                    "task_uuid": task_uuid,
                    "message": "任务已取消",
                    "timestamp": datetime.now().isoformat()
                }
            )
        
        logger.info(f"任务已取消: {task_uuid}")
        
        return {"message": "任务已取消", "task_uuid": task_uuid}
        
    except Exception as e:
        logger.error(f"取消任务失败: {e}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"取消任务失败: {str(e)}"
        )
