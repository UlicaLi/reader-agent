import json
import uuid
import asyncio
from celery import Celery
from app.config import CELERY_BROKER_URL, CELERY_RESULT_BACKEND
from app.service.task_service import (
    get_task_by_uuid, update_task_progress, complete_task, fail_task, 
)
from app.service.document_service import (
   download_file_from_minio, create_document_record, cleanup_temp_files, get_upload_info, get_document_pages, get_document_by_uuid
)
from app.service.processing_service import convert_pdf_to_png
from app.db.models import TaskSteps
from app.tasks.executor import TaskExecutor
import logging

logger = logging.getLogger(__name__)

celery = Celery(__name__)
celery.conf.broker_url = CELERY_BROKER_URL
celery.conf.result_backend = CELERY_RESULT_BACKEND


def run_async_in_celery(coro):
    """在 Celery worker 中安全运行异步函数"""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # 创建新的事件循环
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    try:
        return loop.run_until_complete(coro)
    finally:
        # 轻量级清理
        pending = asyncio.all_tasks(loop)
        for task in pending:
            task.cancel()
        # 不强制关闭事件循环，让它自然管理


@celery.task(name="parse_document_task", bind=True)
def parse_document_task(self, task_uuid: str):
    """
    文档解析主任务
    
    Args:
        task_uuid: 任务UUID
        
    Returns:
        dict: 任务执行结果
    """
    
    # 获取任务记录
    task = get_task_by_uuid(task_uuid)
    if not task:
        raise ValueError(f"任务不存在: {task_uuid}")
    
    input_data = json.loads(task.input)
    upload_uuid = input_data["upload_uuid"]
    user_uuid = input_data.get("user_uuid")
    
    document_uuid = None  # 用于存储Document记录的UUID
    file_path = None
    png_files = []
    
    try:
        # 步骤1: 下载文件 (0-15%)
        update_task_progress(task_uuid, 0, "开始下载文件")
        
        # 从uploads表获取文件信息
        file_info = get_upload_info(upload_uuid)
        file_path = download_file_from_minio(file_info, task_uuid)
        
        update_task_progress(task_uuid, 15, "文件下载完成，正在创建文档记录")
        
        # 步骤2: 创建Document记录 (15-20%)
        document_uuid = str(uuid.uuid4())
        document = create_document_record(
            uuid_str=document_uuid,
            user_uuid=user_uuid,
            upload_info=file_info,
            file_path=file_path,
            task_uuid=task_uuid
        )
        
        update_task_progress(task_uuid, 20, f"文档记录已创建: {document.filename}")
        
        # 步骤3: PDF转PNG (20-40%)
        png_files = convert_pdf_to_png(file_path, document_uuid, task_uuid, user_uuid)
        
        # 运行主任务的异步步骤
        document_info = {
            'filename': document.filename,
            'pages_num': document.pages_num
        }
        executor = TaskExecutor(task_uuid, user_uuid)
        run_async_in_celery(executor.execute_main_flow_progress(document_info, len(png_files)))
        
        update_task_progress(task_uuid, 40, f"PDF转换完成，共生成{len(png_files)}张图片")
        
        # 步骤4-6: 继续OCR处理流程 (40-100%)
        result = continue_ocr_processing(task_uuid, png_files, user_uuid, document_uuid, upload_uuid)
        
        # 清理临时文件
        cleanup_temp_files(file_path, png_files)
        
        return {
            "status": "completed", 
            "document_uuid": document_uuid,
            "message": "文档解析完成"
        }
        
    except Exception as e:
        # 任务失败处理
        error_msg = f"文档解析失败: {str(e)}"
        logger.error(error_msg)
        fail_task(task_uuid, error_msg)
        executor = TaskExecutor(task_uuid, user_uuid)
        # 重新获取任务状态，确保使用最新的进度
        current_task = get_task_by_uuid(task_uuid)
        current_progress = current_task.progress if current_task else 0
        logger.error(f"parse_document_task错误处理 - 任务: {task_uuid}, 当前进度: {current_progress}%")
        run_async_in_celery(executor.execute_simple_progress(TaskSteps.ERROR, current_progress, error_msg))
        
        # 清理临时文件
        cleanup_temp_files(file_path, png_files)
        
        raise


@celery.task(name="resume_document_parse_from_point", bind=True)
def resume_document_parse_from_point(self, task_uuid: str, recovery_info: dict):
    """
    从特定恢复点恢复文档解析任务
    
    Args:
        task_uuid: 任务UUID
        recovery_info: 恢复信息
        
    Returns:
        dict: 任务执行结果
    """
    logger.info(f"开始恢复任务: {task_uuid}, 恢复点: {recovery_info.get('recovery_point')}")
    
    task = get_task_by_uuid(task_uuid)
    if not task:
        raise ValueError(f"任务不存在: {task_uuid}")
    
    input_data = json.loads(task.input)
    upload_uuid = input_data["upload_uuid"]
    user_uuid = input_data.get("user_uuid")
    
    recovery_point = recovery_info["recovery_point"]
    document_uuid = recovery_info.get("document_uuid")
    
    logger.info(f"任务 {task_uuid} 当前进度: {task.progress}%, 恢复点: {recovery_point}")
    
    try:
        if recovery_point == "document_created":
            # 从PDF转换开始恢复
            return resume_from_pdf_convert(task_uuid, recovery_info)
        elif recovery_point == "pdf_converted":
            # PDF已转换，从Document创建开始
            return resume_from_document_creation(task_uuid, recovery_info)
        elif recovery_point == "ocr_partial":
            # OCR部分完成，继续OCR
            return resume_from_ocr_partial(task_uuid, recovery_info)
        elif recovery_point == "chunk_store":
            # 从分块存储阶段恢复
            return resume_from_chunk_store(task_uuid, recovery_info)
        elif recovery_point == "embedding_store":
            # 从向量存储阶段恢复
            return resume_from_embedding_store(task_uuid, recovery_info)
        elif recovery_point == "completed":
            # 任务已完成，直接返回
            return {"status": "completed", "document_uuid": document_uuid}
        else:
            # 未知恢复点，从头开始
            return parse_document_task(task_uuid)
            
    except Exception as e:
        error_msg = f"恢复任务失败: {str(e)}"
        logger.error(error_msg)
        fail_task(task_uuid, error_msg)
        raise


def resume_from_pdf_convert(task_uuid: str, recovery_info: dict):
    """从PDF转换阶段恢复"""
    task = get_task_by_uuid(task_uuid)
    input_data = json.loads(task.input)
    user_uuid = input_data.get("user_uuid")
    upload_uuid = input_data["upload_uuid"]
    document_uuid = recovery_info["document_uuid"]
    
    file_path = recovery_info["available_files"].get("pdf_file")
    if not file_path:
        # 重新下载文件
        file_info = get_upload_info(upload_uuid)
        file_path = download_file_from_minio(file_info, task_uuid)
    
    try:
        # 从20%开始
        executor = TaskExecutor(task_uuid, user_uuid)
        run_async_in_celery(executor.execute_recovery_progress("pdf_convert"))
        png_files = convert_pdf_to_png(file_path, document_uuid, task_uuid, user_uuid)
        
        # 继续后续步骤
        return continue_ocr_processing(task_uuid, png_files, user_uuid, document_uuid, upload_uuid)
        
    except Exception as e:
        error_msg = f"PDF转换恢复失败: {str(e)}"
        fail_task(task_uuid, error_msg)
        raise


def continue_ocr_processing(task_uuid: str, png_files: list, user_uuid: str, document_uuid: str, upload_uuid: str):
    """继续OCR处理流程"""
    try:
        # 运行完整的OCR处理流程，包括向量存储 (40-100%)
        executor = TaskExecutor(task_uuid, user_uuid)
        ocr_results = run_async_in_celery(
            executor.execute_ocr_with_progress(png_files, document_uuid, upload_uuid)
        )
        
        # OCR处理已经包含了完整的存储流程（包括向量存储），直接完成任务
        complete_task(task_uuid, document_uuid, "文档解析完成")
        
        return {"status": "completed", "document_uuid": document_uuid}
        
    except Exception as e:
        error_msg = f"文档处理失败: {str(e)}"
        fail_task(task_uuid, error_msg)
        # 向量存储失败时，发送错误进度更新
        executor = TaskExecutor(task_uuid, user_uuid)
        task = get_task_by_uuid(task_uuid)
        current_progress = task.progress if task else 90  # 使用当前进度，避免设置为100%
        run_async_in_celery(executor.execute_simple_progress(TaskSteps.ERROR, current_progress, error_msg))
        raise


def resume_from_document_creation(task_uuid: str, recovery_info: dict):
    """从Document创建阶段恢复（有PNG文件但没有Document记录）"""
    task = get_task_by_uuid(task_uuid)
    input_data = json.loads(task.input)
    user_uuid = input_data.get("user_uuid")
    upload_uuid = input_data["upload_uuid"]
    
    png_files = recovery_info["available_files"].get("png_files", [])
    
    try:
        # 从15%开始，创建Document记录
        executor = TaskExecutor(task_uuid, user_uuid)
        run_async_in_celery(executor.execute_recovery_progress("document_creation"))
        
        file_info = get_upload_info(upload_uuid)
        file_path = recovery_info["available_files"].get("pdf_file")
        if not file_path:
            file_path = download_file_from_minio(file_info, task_uuid)
        
        document_uuid = str(uuid.uuid4())
        document = create_document_record(
            uuid_str=document_uuid,
            user_uuid=user_uuid,
            upload_info=file_info,
            file_path=file_path,
            task_uuid=task_uuid
        )
        
        # 继续OCR处理
        return continue_ocr_processing(task_uuid, png_files, user_uuid, document_uuid, upload_uuid)
        
    except Exception as e:
        error_msg = f"Document创建恢复失败: {str(e)}"
        fail_task(task_uuid, error_msg)
        raise


def resume_from_ocr_partial(task_uuid: str, recovery_info: dict):
    """从OCR部分完成阶段恢复"""
    task = get_task_by_uuid(task_uuid)
    input_data = json.loads(task.input)
    user_uuid = input_data.get("user_uuid")
    upload_uuid = input_data["upload_uuid"]
    document_uuid = recovery_info["document_uuid"]
    
    png_files = recovery_info["available_files"].get("png_files", [])
    completed_pages = recovery_info["ocr_completed_pages"]
    total_pages = recovery_info["total_pages"]
    
    try:
        # 检查总页数是否有效
        if total_pages <= 0:
            logger.error(f"文档总页数无效: {total_pages}, 尝试重新获取页数信息")
            # 尝试从文档记录重新获取页数
            document = get_document_by_uuid(document_uuid)
            if document and document.pages_num > 0:
                total_pages = document.pages_num
                recovery_info["total_pages"] = total_pages
                logger.info(f"重新获取到文档页数: {total_pages}")
            else:
                logger.warning(f"无法获取有效页数，直接进入分块存储阶段")
        
        executor = TaskExecutor(task_uuid, user_uuid)
        run_async_in_celery(executor.execute_recovery_progress("ocr_partial", 
                                    completed_pages=completed_pages, total_pages=total_pages))
        
        # 继续处理剩余的页面
        remaining_png_files = png_files[completed_pages:] if png_files else []
        
        if remaining_png_files:
            # 继续OCR处理
            executor = TaskExecutor(task_uuid, user_uuid)
            ocr_results = run_async_in_celery(executor.execute_recovery_ocr_steps(remaining_png_files, document_uuid))
        
        # OCR完成后直接进行分块存储
        return resume_from_chunk_store(task_uuid, recovery_info)
        
    except Exception as e:
        error_msg = f"OCR部分恢复失败: {str(e)}"
        fail_task(task_uuid, error_msg)
        raise


def resume_from_chunk_store(task_uuid: str, recovery_info: dict):
    """从分块存储阶段恢复 - 只处理分块和数据库存储，不包含向量存储"""
    task = get_task_by_uuid(task_uuid)
    input_data = json.loads(task.input)
    user_uuid = input_data.get("user_uuid")
    upload_uuid = input_data["upload_uuid"]
    document_uuid = recovery_info["document_uuid"]
    
    try:
        # 从85%开始
        executor = TaskExecutor(task_uuid, user_uuid)
        run_async_in_celery(executor.execute_recovery_progress("chunk_store"))
        
        # 获取页面内容（从数据库）
        pages = get_document_pages(document_uuid)
        
        if not pages:
            raise ValueError("未找到页面数据，无法恢复")
        
        pages_content = [
            {
                "page_number": page.page_number,
                "markdown_content": page.markdown_content
            }
            for page in pages
        ]
        
        # 更新进度：开始分块处理 (87%)
        run_async_in_celery(executor.execute_simple_progress(TaskSteps.STORE_DATABASE, 87, "开始文档分块处理"))
        
        # 只执行分块和数据库存储，不包含向量存储
        from app.service.processing_service import chunk_document_content, save_chunks_to_database
        
        # 文档分块
        chunks = chunk_document_content(pages_content, document_uuid)
        
        # 保存分块到数据库
        save_chunks_to_database(document_uuid, chunks, task_uuid)
        
        # 更新进度：分块存储完成，准备向量存储 (90%)
        run_async_in_celery(executor.execute_simple_progress(TaskSteps.STORE_DATABASE, 90, "分块存储完成，准备向量存储"))
        
        # 调用向量存储恢复函数
        return resume_from_embedding_store(task_uuid, recovery_info)
        
    except Exception as e:
        error_msg = f"分块存储恢复失败: {str(e)}"
        logger.error(error_msg)
        fail_task(task_uuid, error_msg)
        raise


def resume_from_embedding_store(task_uuid: str, recovery_info: dict):
    """从向量存储阶段恢复 - 专门处理向量存储，支持增量恢复"""
    task = get_task_by_uuid(task_uuid)
    input_data = json.loads(task.input)
    user_uuid = input_data.get("user_uuid")
    upload_uuid = input_data["upload_uuid"]
    document_uuid = recovery_info["document_uuid"]
    
    try:
        # 从90%开始（接续分块存储完成后的进度）
        executor = TaskExecutor(task_uuid, user_uuid)
        run_async_in_celery(executor.execute_recovery_progress("embedding_store"))
        
        # 更新进度：开始向量存储 (92%)
        run_async_in_celery(executor.execute_simple_progress(TaskSteps.STORE_DATABASE, 92, "开始向量数据库存储"))
        
        # 获取所有chunks（从数据库）
        from app.db.session import SessionLocal
        from app.db.models import Chunk
        
        db = SessionLocal()
        try:
            chunks = db.query(Chunk).filter(
                Chunk.document_uuid == document_uuid,
                Chunk.deleted_at.is_(None)
            ).all()
            
            if not chunks:
                raise ValueError("未找到chunks数据，无法恢复向量存储")
            
            logger.info(f"找到{len(chunks)}个chunks需要检查向量存储状态")
            
            # 检查向量数据库中已存在的chunks
            from app.utils.embedding import EmbeddingService
            embedding_service = EmbeddingService()
            
            # 通过document_uuid查询Milvus中已存在的chunks
            existing_chunk_indices = set()
            try:
                if embedding_service.collection:
                    existing_results = embedding_service.collection.query(
                        expr=f'document_uuid == "{document_uuid}"',
                        output_fields=["chunk_id", "index"]
                    )
                    existing_chunk_indices = {result["index"] for result in existing_results}
                    logger.info(f"向量数据库中已存在{len(existing_chunk_indices)}个chunks")
                else:
                    logger.warning("向量数据库未初始化，将重新存储所有chunks")
            except Exception as e:
                logger.warning(f"检查向量数据库已存在chunks失败: {e}，将重新存储所有chunks")
            
            # 过滤出需要存储的chunks
            chunks_to_store = [chunk for chunk in chunks if chunk.index not in existing_chunk_indices]
            
            if chunks_to_store:
                logger.info(f"需要存储{len(chunks_to_store)}个chunks到向量数据库")
                
                # 更新进度：正在进行向量存储 (95%)
                run_async_in_celery(executor.execute_simple_progress(TaskSteps.STORE_DATABASE, 95, f"正在存储{len(chunks_to_store)}个chunks到向量数据库"))
                
                # 直接使用EmbeddingService处理chunks
                processed_count = embedding_service.process_chunks(chunks_to_store)
                logger.info(f"成功存储{processed_count}个chunks到向量数据库")
                
                if processed_count != len(chunks_to_store):
                    logger.warning(f"预期存储{len(chunks_to_store)}个chunks，实际存储{processed_count}个")
            else:
                logger.info("所有chunks已存在于向量数据库中，跳过向量存储")
            
            # 更新进度：向量存储完成 (98%)
            run_async_in_celery(executor.execute_simple_progress(TaskSteps.STORE_DATABASE, 98, "向量存储完成，标记文档就绪"))
            
            # 标记文档为就绪
            from app.service.processing_service import mark_document_ready
            mark_document_ready(document_uuid)
            
        finally:
            db.close()
        
        # 完成任务
        complete_task(task_uuid, document_uuid, "恢复：向量存储完成")
        run_async_in_celery(executor.execute_simple_progress(TaskSteps.COMPLETED, 100, "文档解析恢复完成"))
        
        return {"status": "completed", "document_uuid": document_uuid}
        
    except Exception as e:
        error_msg = f"向量存储恢复失败: {str(e)}"
        logger.error(error_msg)
        fail_task(task_uuid, error_msg)
        # 向量存储失败时，发送错误进度更新
        executor = TaskExecutor(task_uuid, user_uuid)
        task = get_task_by_uuid(task_uuid)
        current_progress = task.progress if task else 90
        run_async_in_celery(executor.execute_simple_progress(TaskSteps.ERROR, current_progress, error_msg))
        raise
