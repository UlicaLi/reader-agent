"""
任务服务模块
处理任务相关的业务逻辑，包括任务状态管理、进度更新等
"""
import json
import uuid
import asyncio
from datetime import datetime
from typing import Optional, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import and_
import logging
import os
import glob

from app.db.session import SessionLocal
from app.db.models import Task, TaskStatus, TaskSteps
from app.service.document_service import get_document_by_upload_uuid, get_document_pages, get_document_chunks, get_document_by_uuid
from app.service.sse import sse_manager

logger = logging.getLogger(__name__)


def check_vector_storage_complete(document_uuid: str) -> bool:
    """
    检查指定文档的向量存储是否完成
    
    Args:
        document_uuid: 文档UUID
        
    Returns:
        bool: 向量存储是否完成
    """
    try:
        from app.utils.embedding import EmbeddingService
        embedding_service = EmbeddingService()
        
        if not embedding_service.collection:
            logger.warning(f"向量数据库未初始化，无法检查存储状态: {document_uuid}")
            return False
        
        # 查询该文档在向量数据库中的chunks数量
        try:
            existing_results = embedding_service.collection.query(
                expr=f'document_uuid == "{document_uuid}"',
                output_fields=["chunk_id"]
            )
            vector_chunks_count = len(existing_results)
        except Exception as e:
            logger.warning(f"查询向量数据库失败: {e}")
            return False
        
        # 查询数据库中的chunks数量
        from app.db.session import SessionLocal
        from app.db.models import Chunk
        
        db = SessionLocal()
        try:
            db_chunks_count = db.query(Chunk).filter(
                Chunk.document_uuid == document_uuid,
                Chunk.deleted_at.is_(None)
            ).count()
        finally:
            db.close()
        
        # 如果向量数据库中的chunks数量等于数据库中的chunks数量，则认为向量存储完成
        is_complete = vector_chunks_count > 0 and vector_chunks_count == db_chunks_count
        
        logger.info(f"向量存储检查 - 文档: {document_uuid}, 数据库chunks: {db_chunks_count}, 向量chunks: {vector_chunks_count}, 完成状态: {is_complete}")
        
        return is_complete
        
    except Exception as e:
        logger.error(f"检查向量存储完成状态失败: {e}")
        return False


def get_task_by_uuid(task_uuid: str) -> Optional[Task]:
    """根据UUID获取任务记录"""
    db = SessionLocal()
    try:
        return db.query(Task).filter(
            and_(Task.uuid == task_uuid, Task.deleted_at.is_(None))
        ).first()
    finally:
        db.close()


def get_completed_task_by_upload_uuid(upload_uuid: str) -> Optional[Task]:
    """根据upload_uuid获取已完成的任务记录"""
    db = SessionLocal()
    try:
        # 查询所有包含该upload_uuid的已完成任务
        tasks = db.query(Task).filter(
            and_(
                Task.type == "document_parse",
                Task.status == TaskStatus.COMPLETED,
                Task.deleted_at.is_(None)
            )
        ).all()
        
        # 检查input字段中是否包含指定的upload_uuid
        for task in tasks:
            if task.input:
                try:
                    input_data = json.loads(task.input)
                    if input_data.get("upload_uuid") == upload_uuid:
                        return task
                except:
                    continue
        
        return None
    finally:
        db.close()


def create_task_record(task_uuid: str, user_uuid: str, upload_uuid: str, task_type: str = "document_parse") -> Task:
    """创建任务记录"""
    db = SessionLocal()
    try:
        task = Task(
            uuid=task_uuid,
            user_uuid=user_uuid,
            type=task_type,
            status=TaskStatus.PENDING,
            input=json.dumps({
                "upload_uuid": upload_uuid,
                "user_uuid": user_uuid,
                "started_at": datetime.now().isoformat()
            }),
            progress=0,
            message="任务已创建，等待执行",
            created_at=datetime.now()
        )
        db.add(task)
        db.commit()
        db.refresh(task)
        
        logger.info(f"Task created: {task_uuid}, type: {task_type}, user: {user_uuid}")
        return task
    finally:
        db.close()


def update_task_status(task_uuid: str, status: int, progress: int, message: str, 
                      output_data: Dict = None):
    """更新任务状态"""
    db = SessionLocal()
    try:
        task = db.query(Task).filter(Task.uuid == task_uuid).first()
        if task:
            task.status = status
            task.progress = progress
            task.message = message
            task.updated_at = datetime.now()
            
            if output_data:
                current_output = {}
                if task.output:
                    try:
                        current_output = json.loads(task.output)
                    except:
                        pass
                current_output.update(output_data)
                task.output = json.dumps(current_output)
            
            if status == TaskStatus.COMPLETED:
                task.finished_at = datetime.now()
            elif status == TaskStatus.FAILED:
                task.finished_at = datetime.now()
                
            db.commit()
            logger.info(f"Task updated: {task_uuid}, status: {status}, progress: {progress}%")
    finally:
        db.close()


def update_task_progress(task_uuid: str, progress: int, message: str):
    """更新任务进度"""
    update_task_status(task_uuid, TaskStatus.RUNNING, progress, message)


def complete_task(task_uuid: str, document_uuid: str = None, message: str = "任务完成"):
    """完成任务"""
    output_data = {}
    if document_uuid:
        output_data["document_uuid"] = document_uuid
        
        # 收集文档统计信息
        try:
            document_stats = collect_document_statistics(document_uuid)
            output_data.update(document_stats)
        except Exception as e:
            logger.error(f"收集文档统计信息失败: {e}")
    
    update_task_status(task_uuid, TaskStatus.COMPLETED, 100, message, output_data)


def collect_document_statistics(document_uuid: str) -> dict:
    """
    收集文档统计信息
    
    Args:
        document_uuid: 文档UUID
        
    Returns:
        dict: 包含文档统计信息的字典
    """
    stats = {
        "total_pages": 0,
        "successful_pages": 0,
        "failed_pages": 0,
        "total_chunks": 0,
        "completion_time": datetime.now().isoformat()
    }
    
    try:
        # 获取文档基本信息
        document = get_document_by_uuid(document_uuid)
        if document:
            stats["total_pages"] = document.pages_num
            stats["document_filename"] = document.filename
            stats["file_size"] = document.file_size
        
        # 获取页面处理结果
        pages = get_document_pages(document_uuid)
        if pages:
            stats["successful_pages"] = len(pages)
            # 计算失败页数（总页数 - 成功页数）
            stats["failed_pages"] = max(0, stats["total_pages"] - stats["successful_pages"])
        
        # 获取分块信息
        chunks = get_document_chunks(document_uuid)
        if chunks:
            stats["total_chunks"] = len(chunks)
        
        logger.info(f"文档统计信息收集完成: {document_uuid}, 总页数: {stats['total_pages']}, "
                   f"成功页数: {stats['successful_pages']}, 失败页数: {stats['failed_pages']}, "
                   f"分块数: {stats['total_chunks']}")
        
    except Exception as e:
        logger.error(f"收集文档统计信息时出错: {e}")
    
    return stats


def fail_task(task_uuid: str, error_msg: str):
    """标记任务失败"""
    logger.error(f"task_uuid: {task_uuid}, error_msg: {error_msg}")
    task = get_task_by_uuid(task_uuid)
    logger.error(f"task.progress: {task.progress}")
    current_progress = task.progress if task else 0
    logger.error(f"current_progress: {current_progress}")
    update_task_status(task_uuid, TaskStatus.FAILED, current_progress, error_msg)


async def send_task_started_notification(user_uuid: str, task_uuid: str):
    """发送任务开始通知"""
    try:
        await sse_manager.send_to_user(
                user_id=user_uuid,
                event_type="task_started",
                data={
                    "task_uuid": task_uuid,
                    "message": "文档解析任务开始",
                    "timestamp": datetime.now().isoformat()
                }
            )
    except Exception as e:
        logger.error(f"发送任务开始通知失败: {e}")


async def send_progress_sse(user_uuid: str, task_uuid: str, step: str, progress: int, message: str):
    """发送进度到SSE"""
    try:
        # 更新数据库
        update_task_progress(task_uuid, progress, message)
        
        # 发送SSE消息
        await sse_manager.send_to_user(
                user_id=user_uuid,
                event_type="task_progress",
                data={
                    "task_uuid": task_uuid,
                    "step": step,
                    "progress": progress,
                    "message": message,
                    "timestamp": datetime.now().isoformat()
                }
            )
    except Exception as e:
        logger.error(f"发送进度SSE失败: {e}")

def analyze_task_recovery_point(task_uuid: str) -> dict:
    """
    分析任务的恢复点
    通过检查已完成的工作和数据库记录来确定从哪里恢复
    """
    
    task = get_task_by_uuid(task_uuid)
    if not task:
        raise ValueError("任务不存在")
    
    input_data = json.loads(task.input)
    upload_uuid = input_data["upload_uuid"]
    
    recovery_info = {
        "task_uuid": task_uuid,
        "upload_uuid": upload_uuid,
        "current_progress": task.progress,
        "last_message": task.message,
        "recovery_point": None,
        "document_uuid": None,
        "available_files": {},
        "ocr_completed_pages": 0,
        "total_pages": 0,
    }
    
    # 1. 检查是否已有Document记录
    document = get_document_by_upload_uuid(upload_uuid)
    if document:
        recovery_info["document_uuid"] = document.uuid
        recovery_info["total_pages"] = document.pages_num
        recovery_info["recovery_point"] = "document_created"
        
        # 2. 检查Page记录（OCR结果）
        pages = get_document_pages(document.uuid)
        if pages:
            recovery_info["ocr_completed_pages"] = len(pages)
            
            # 检查OCR是否完全完成
            if len(pages) >= document.pages_num and document.pages_num > 0:
                recovery_info["recovery_point"] = "ocr_completed"
                
                # OCR结果已经是markdown格式，直接检查Chunk记录
                chunks = get_document_chunks(document.uuid)
                if chunks:
                    recovery_info["recovery_point"] = "chunk_store"
                    
                    # 检查向量存储是否完成
                    vector_storage_complete = check_vector_storage_complete(document.uuid)
                    if vector_storage_complete:
                        # 向量存储已完成，检查文档是否标记为ready
                        if document.is_ready:
                            recovery_info["recovery_point"] = "completed"
                        else:
                            # 向量存储完成但文档未标记为ready，需要完成最后步骤
                            recovery_info["recovery_point"] = "embedding_store"
                    else:
                        # 向量存储未完成，需要进行向量存储
                        recovery_info["recovery_point"] = "embedding_store"
            else:
                # OCR部分完成
                recovery_info["recovery_point"] = "ocr_partial"
    
    # 5. 检查临时文件（用于恢复PDF转换阶段）
    temp_dir = f"/tmp/documents/{upload_uuid}"
    if os.path.exists(f"{temp_dir}/original.pdf"):
        recovery_info["available_files"]["pdf_file"] = f"{temp_dir}/original.pdf"
    
    png_files = glob.glob(f"{temp_dir}/pages/*.png")
    if png_files:
        recovery_info["available_files"]["png_files"] = png_files
        
        # 如果有PNG文件但没有Document记录，说明在Document创建前失败
        if not document:
            recovery_info["recovery_point"] = "pdf_converted"
    
    logger.info(f"恢复点分析完成 - 任务: {task_uuid}, 恢复点: {recovery_info['recovery_point']}, "
                f"文档UUID: {recovery_info.get('document_uuid')}, "
                f"OCR完成页数: {recovery_info['ocr_completed_pages']}/{recovery_info['total_pages']}")
    
    return recovery_info
