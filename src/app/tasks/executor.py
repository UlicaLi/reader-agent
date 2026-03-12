"""
任务执行器模块
"""
import logging
from typing import List
from app.db.models import TaskSteps
from app.service.processing_service import process_ocr_batch, convert_to_markdown_pages, store_document_data
from app.tasks.progress import TaskProgressManager

logger = logging.getLogger(__name__)


class TaskExecutor:
    """任务执行器"""
    
    def __init__(self, task_uuid: str, user_uuid: str):
        self.progress_manager = TaskProgressManager(task_uuid, user_uuid)
        self.task_uuid = task_uuid
        self.user_uuid = user_uuid
    
    async def execute_main_flow_progress(self, document_info: dict, png_files_count: int):
        """执行主流程进度报告"""
        await self.progress_manager.report_main_flow_progress(document_info, png_files_count)
    
    async def execute_ocr_with_progress(self, png_files: list, document_uuid: str, upload_uuid: str):
        """执行OCR并报告进度，包括完整的存储流程"""
        # OCR识别 (40-70%)
        await self.progress_manager.report_progress(TaskSteps.OCR_PROCESSING, 40, "开始OCR文字识别")
        ocr_results = await process_ocr_batch(png_files, document_uuid, self.task_uuid, self.user_uuid)
        await self.progress_manager.report_progress(TaskSteps.OCR_PROCESSING, 70, "OCR文字识别完成")
        
        # 获取页面内容进度报告 (70-75%)
        await self.progress_manager.report_progress(TaskSteps.MARKDOWN_CONVERT, 75, "获取页面内容")
        
        # 文档分块和数据库存储进度报告 (75-90%)
        await self.progress_manager.report_progress(TaskSteps.STORE_DATABASE, 75, "开始文档分块和数据库存储")
        
        # 获取页面内容 (同步操作)
        pages_content = convert_to_markdown_pages(document_uuid)
        
        # 向量数据库存储进度报告 (90-100%)
        await self.progress_manager.report_progress(TaskSteps.STORE_DATABASE, 90, "开始向量数据库存储")
        
        # 存储包括向量数据库存储
        store_document_data(upload_uuid, pages_content, self.task_uuid, document_uuid)
        
        # 只有在所有存储步骤（包括向量数据库）都成功后才设置100%
        await self.progress_manager.report_progress(TaskSteps.COMPLETED, 100, "文档解析完成")
        
        return ocr_results
    
    async def execute_recovery_ocr_steps(self, png_files: list, document_uuid: str):
        """执行恢复阶段的OCR步骤"""
        try:
            ocr_results = await process_ocr_batch(png_files, document_uuid, self.task_uuid, self.user_uuid)
            return ocr_results
        except Exception as e:
            logger.error(f"恢复OCR步骤失败 [任务:{self.task_uuid}]: {str(e)}")
            raise
    
    async def execute_recovery_progress(self, recovery_type: str, **kwargs):
        """执行恢复流程进度报告"""
        await self.progress_manager.report_recovery_progress(recovery_type, **kwargs)
    
    async def execute_simple_progress(self, step: TaskSteps, progress: int, message: str):
        """执行简单的进度报告"""
        await self.progress_manager.report_progress(step, progress, message)
    
    async def execute_full_ocr_flow_progress(self):
        """执行完整的OCR流程进度报告"""
        await self.progress_manager.report_ocr_flow_progress()
