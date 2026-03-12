"""
文档解析API路由
处理文档解析相关的接口，包括启动解析、查询进度、断点恢复等
"""
import uuid
import json
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
import requests

from app.api.schemas import TaskResponse, TaskCreateRequest, RecoveryInfo
from app.db.session import get_db
from app.db.models import Task, TaskStatus
from app.service.task_service import (
    send_task_started_notification,
    analyze_task_recovery_point, get_completed_task_by_upload_uuid
)
from app.service.document_service import check_document_exists_in_db, get_document_pages, get_document_chunks
from app.tasks.worker import parse_document_task, resume_document_parse_from_point
from app.tasks.progress import get_recovery_progress
from app.api.middleware import extract_access_token
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["documents"])

@router.post("/parse", response_model=TaskResponse, summary="启动文档解析任务")
async def parse_document(
    request_body: TaskCreateRequest,
    request: Request,
    db: Session = Depends(get_db)
):
    """
    启动文档解析任务
    
    - **upload_uuid**: 文件上传UUID（从加密的文件信息中解析）
    - **user_uuid**: 用户UUID
    
    返回完整的任务实体，包含所有字段
    """
    try:
        
        # 获取upload_uuid
        upload_uuid = request_body.upload_uuids[0]
        logger.info(f"收到解析请求: upload_uuid={upload_uuid}")

        # 获取用户UUID
        authorization = request.headers.get("Authorization")

        access_token = extract_access_token(authorization)

        api_url = f"https://api.noread.pro/api/v1/auth/user?access_token={access_token}"
        response = requests.get(api_url)
        
        if response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="未授权"
            )
        logger.info(f"response: {response.json()}")
        
        user_uuid = str(response.json().get("user_id"))
        if not user_uuid:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="用户不存在"
            )

        # 1. 检查是否已存在该upload_uuid的完整文档记录
        document_status = check_document_exists_in_db(upload_uuid)
        
        if document_status["exists"]:
            if document_status["is_ready"]:
                # 文档已完成，返回已完成的任务记录
                completed_task = get_completed_task_by_upload_uuid(upload_uuid)
                if completed_task:
                    logger.info(f"文档已完成解析，返回已完成任务: upload_uuid={upload_uuid}, task_uuid={completed_task.uuid}")
                    return completed_task
                else:
                    # 如果找不到对应的任务记录，创建一个虚拟的已完成任务记录
                    task_uuid = str(uuid.uuid4())
                    task = Task(
                        uuid=task_uuid,
                        user_uuid=user_uuid,
                        type="document_parse",
                        status=TaskStatus.COMPLETED,
                        input=json.dumps({
                            "upload_uuid": upload_uuid,
                            "user_uuid": user_uuid
                        }),
                        output=json.dumps({
                            "document_uuid": document_status["document"].uuid,
                            "message": "文档已存在且已完成解析"
                        }),
                        progress=100,
                        message="文档已完成解析",
                        created_at=datetime.now(),
                        finished_at=datetime.now()
                    )
                    db.add(task)
                    db.commit()
                    db.refresh(task)
                    return task
            elif document_status["needs_resume"]:
                # 文档存在但未完成，进行断点恢复
                logger.info(f"文档存在但未完成，开始断点恢复: upload_uuid={upload_uuid}")
                
                # 查找是否有对应此upload_uuid的未完成任务记录
                existing_tasks = db.query(Task).filter(
                    Task.type == "document_parse",
                    Task.status.in_([TaskStatus.PENDING, TaskStatus.RUNNING, TaskStatus.FAILED])
                ).order_by(Task.created_at.desc()).all()
                
                existing_task = None
                task_uuid = None
                
                # 检查是否有对应此upload_uuid的任务
                for task in existing_tasks:
                    if task.input:
                        try:
                            input_data = json.loads(task.input)
                            if input_data.get("upload_uuid") == upload_uuid:
                                # 找到对应的任务，使用最新的一个
                                existing_task = task
                                task_uuid = task.uuid
                                logger.info(f"找到现有任务进行恢复: {task_uuid}, 状态: {task.status}, 进度: {task.progress}%")
                                break
                        except:
                            continue
                
                if not existing_task:
                    # 创建新的恢复任务
                    task_uuid = str(uuid.uuid4())
                    logger.info(f"未找到现有任务，创建新的恢复任务: {task_uuid}")
                
                if not existing_task:
                    # 创建新的任务记录用于恢复
                    task = Task(
                        uuid=task_uuid,
                        user_uuid=user_uuid,
                        type="document_parse",
                        status=TaskStatus.PENDING,
                        input=json.dumps({
                            "upload_uuid": upload_uuid,
                            "user_uuid": user_uuid
                        }),
                        output=None,
                        progress=0,  # 初始设置为0，后续会根据恢复点调整
                        message="准备断点恢复",
                        created_at=datetime.now()
                    )
                    db.add(task)
                    db.commit()
                    db.refresh(task)
                else:
                    task = existing_task
                
                # 分析恢复点并启动恢复任务
                recovery_info = analyze_task_recovery_point(task_uuid)
                
                # 根据恢复点设置适当的进度
                recovery_progress = get_recovery_progress(recovery_info["recovery_point"])
                if recovery_progress > 0:
                    task.progress = recovery_progress
                    task.message = f"断点恢复：从{recovery_info['recovery_point']}阶段继续"
                    db.commit()
                    logger.info(f"任务 {task_uuid} 恢复进度设置为 {recovery_progress}%")
                
                if recovery_info["recovery_point"] == "completed":
                    # 实际上已经完成了，只需要标记文档为ready
                    from app.service.document_service import mark_document_ready
                    mark_document_ready(document_status["document"].uuid)
                    
                    task.status = TaskStatus.COMPLETED
                    task.progress = 100
                    task.message = "文档解析已完成"
                    task.output = json.dumps({
                        "document_uuid": document_status["document"].uuid,
                        "recovery_point": "completed"
                    })
                    task.finished_at = datetime.now()
                    db.commit()
                    db.refresh(task)
                    return task
                else:
                    # 启动断点恢复任务
                    logger.info(f"启动恢复任务前 - 任务 {task_uuid} 当前进度: {task.progress}%, 恢复点: {recovery_info['recovery_point']}")
                    celery_task = resume_document_parse_from_point.delay(task_uuid, recovery_info)
                    
                    # 保持恢复进度，不重置为0
                    current_progress = task.progress  # 保存当前进度
                    task.status = TaskStatus.RUNNING
                    task.started_at = datetime.now()
                    task.message = f"从{recovery_info['recovery_point']}阶段恢复执行"
                    task.progress = current_progress  # 明确保持进度
                    db.commit()
                    db.refresh(task)
                    logger.info(f"启动恢复任务后 - 任务 {task_uuid} 当前进度: {task.progress}%")
                    
                    # 发送恢复通知
                    await send_task_started_notification(user_uuid, task_uuid)
                    
                    logger.info(f"断点恢复任务已启动: {task_uuid}, upload_uuid: {upload_uuid}, 恢复点: {recovery_info['recovery_point']}")
                    return task
        
        # 2. 创建Task记录到数据库
        task_uuid = str(uuid.uuid4())
        
        # 检查是否有现有的工作可以基于（即使不满足恢复条件）
        initial_progress = 0
        initial_message = "任务已创建，等待执行"
        
        # 如果文档存在，根据现有工作设置初始进度
        if document_status["exists"]:
            document = document_status["document"]
            pages = get_document_pages(document.uuid) if document else []
            chunks = get_document_chunks(document.uuid) if document else []
            
            if chunks:
                # 有分块数据，说明至少完成到85%
                initial_progress = 85
                initial_message = "基于现有工作重新开始，从分块存储阶段继续"
            elif pages:
                # 有页面数据，说明至少完成到70%
                initial_progress = 70
                initial_message = "基于现有工作重新开始，从文档分块阶段继续"
            elif document:
                # 有文档记录，说明至少完成到20%
                initial_progress = 20
                initial_message = "基于现有工作重新开始，从PDF转换阶段继续"
            
            logger.info(f"基于现有工作设置初始进度: {initial_progress}% - {initial_message}")
        
        task = Task(
            uuid=task_uuid,
            user_uuid=user_uuid,
            type="document_parse",
            status=TaskStatus.PENDING,
            input=json.dumps({
                "upload_uuid": upload_uuid,
                "user_uuid": user_uuid
            }),
            output=None,
            progress=initial_progress,
            message=initial_message,
            created_at=datetime.now()
        )
        db.add(task)
        db.commit()
        db.refresh(task)
        
        # 3. 提交Celery任务
        logger.info(f"创建新的完整解析任务: {task_uuid}, upload_uuid: {upload_uuid}")
        celery_task = parse_document_task.delay(task_uuid)
        
        task.status = TaskStatus.RUNNING
        task.started_at = datetime.now()
        task.message = "任务开始执行"
        db.commit()
        db.refresh(task)
        
        # 4. 发送初始SSE消息
        await send_task_started_notification(user_uuid, task_uuid)
        
        logger.info(f"文档解析任务已启动: {task_uuid}, upload_uuid: {upload_uuid}")
        
        return task
        
    except Exception as e:
        logger.error(f"启动文档解析任务失败: {e}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"启动文档解析任务失败: {str(e)}"
        )


@router.post("/{task_uuid}/resume", response_model=TaskResponse, summary="断点恢复任务")
async def resume_document_parse(
    request: Request,
    task_uuid: str,
    db: Session = Depends(get_db)
):
    """
    断点恢复任务
    
    - **task_uuid**: 任务UUID
    
    根据任务当前状态和已完成的工作，从适当的恢复点继续执行任务
    """
    try:
        authorization = request.headers.get("Authorization")
        access_token = extract_access_token(authorization)

        api_url = f"https://api.noread.pro/api/v1/auth/user?access_token={access_token}"
        response = requests.get(api_url)
        logger.info(f"response: {response.json()}")

        if response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="未授权"
            )
        
        user_uuid = str(response.json().get("user_id"))
        if not user_uuid:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="用户不存在"
            )
        # 1. 检查任务状态
        task = db.query(Task).filter(Task.uuid == task_uuid).first()
        if not task:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="任务不存在"
            )
        logger.info(f"task: {task.user_uuid}, user_uuid: {user_uuid}")
        
        if task.user_uuid != user_uuid:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="无权限访问此任务"
            )
        if task.status == TaskStatus.COMPLETED:
            # 任务已完成，直接返回
            return task
        
        
        # 2. 分析恢复点
        recovery_info = analyze_task_recovery_point(task_uuid)
        
        # 3. 根据恢复点选择恢复策略
        if recovery_info["recovery_point"] == "completed":
            # 已完成，更新数据库状态
            task.status = TaskStatus.COMPLETED
            task.progress = 100
            task.message = "任务已完成"
            task.finished_at = datetime.now()
            db.commit()
            return task
        
        # 4. 创建恢复任务
        if recovery_info["recovery_point"] is None:
            # 从头开始
            celery_task = parse_document_task.delay(task_uuid)
            recovery_message = "任务重新开始执行"
        else:
            # 从特定点恢复
            celery_task = resume_document_parse_from_point.delay(task_uuid, recovery_info)
            recovery_message = f"从{recovery_info['recovery_point']}阶段恢复"
        
        # 5. 更新任务状态
        task.output = json.dumps({
            "recovery_point": recovery_info["recovery_point"],
            "recovery_time": datetime.now().isoformat(),
        })
        task.status = TaskStatus.RUNNING
        task.message = recovery_message
        task.started_at = datetime.now()
        db.commit()
        db.refresh(task)
        
        logger.info(f"任务恢复成功: {task_uuid}, 恢复点: {recovery_info['recovery_point']}")
        
        return task
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"恢复任务失败: {e}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"恢复任务失败: {str(e)}"
        )

