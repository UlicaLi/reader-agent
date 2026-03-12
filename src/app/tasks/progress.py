"""
任务进度管理模块
"""
import logging
from typing import List, Dict
from app.db.models import TaskSteps
from app.service.task_service import send_progress_sse

logger = logging.getLogger(__name__)


class ProgressConfig:
    """进度配置"""
    MAIN_FLOW = [
        {"step": TaskSteps.DOWNLOAD_FILE, "progress": 0, "message": "正在从存储服务下载文件..."},
        {"step": TaskSteps.DOCUMENT_CREATED, "progress": 20, "message_template": "文档记录已创建：{filename}，共{pages_num}页"},
        {"step": TaskSteps.PDF_TO_PNG, "progress": 20, "message": "开始转换PDF页面为图片"},
        {"step": TaskSteps.PDF_TO_PNG, "progress": 40, "message_template": "PDF转换完成，共{png_files_count}页"},
    ]
    
    RECOVERY_FLOW = {
        "document_creation": [
            {"step": TaskSteps.DOCUMENT_CREATED, "progress": 15, "message": "恢复：创建文档记录"},
        ],
        "pdf_convert": [
            {"step": TaskSteps.PDF_TO_PNG, "progress": 20, "message": "恢复：开始转换PDF页面"},
        ],
        "ocr_partial": [
            {"step": TaskSteps.OCR_PROCESSING, "progress": "calculated", "message_template": "恢复：继续OCR识别，已完成{completed_pages}/{total_pages}页"},
        ],
        "chunk_store": [
            {"step": TaskSteps.STORE_DATABASE, "progress": 85, "message": "恢复：开始文档分块和存储"},
        ],
        "embedding_store": [
            {"step": TaskSteps.STORE_DATABASE, "progress": 90, "message": "恢复：开始向量数据库存储"},
        ],
        "completed": [
            {"step": TaskSteps.COMPLETED, "progress": 100, "message": "恢复：文档解析完成"},
        ],
        
    }
    
    OCR_FLOW = [
        {"step": TaskSteps.OCR_PROCESSING, "progress": 40, "message": "开始OCR文字识别"},
        {"step": TaskSteps.OCR_PROCESSING, "progress": 70, "message": "OCR文字识别完成"},
        {"step": TaskSteps.MARKDOWN_CONVERT, "progress": 70, "message": "获取页面内容"},
        {"step": TaskSteps.STORE_DATABASE, "progress": 75, "message": "开始文档分块和存储"},
        {"step": TaskSteps.COMPLETED, "progress": 100, "message": "文档解析完成"},
    ]


class TaskProgressManager:
    """任务进度管理器"""
    
    def __init__(self, task_uuid: str, user_uuid: str):
        self.task_uuid = task_uuid
        self.user_uuid = user_uuid
    
    async def report_progress(self, step: TaskSteps, progress: int, message: str):
        """报告进度"""
        try:
            await send_progress_sse(self.user_uuid, self.task_uuid, step, progress, message)
        except Exception as e:
            logger.error(f"进度报告失败 [任务:{self.task_uuid}]: {str(e)}")
            # 进度报告失败不应该中断主流程
    
    async def report_batch_progress(self, progress_items: List[Dict]):
        """批量报告进度"""
        for item in progress_items:
            await self.report_progress(
                item['step'], 
                item['progress'], 
                item['message']
            )
    
    async def report_main_flow_progress(self, document_info: dict, png_files_count: int):
        """报告主流程进度"""
        progress_items = []
        
        for config in ProgressConfig.MAIN_FLOW:
            message = config.get('message', '')
            if 'message_template' in config:
                message = config['message_template'].format(
                    filename=document_info.get('filename', ''),
                    pages_num=document_info.get('pages_num', 0),
                    png_files_count=png_files_count
                )
            
            progress_items.append({
                'step': config['step'],
                'progress': config['progress'],
                'message': message
            })
        
        await self.report_batch_progress(progress_items)
    
    async def report_recovery_progress(self, recovery_type: str, **kwargs):
        """报告恢复流程进度"""
        config = ProgressConfig.RECOVERY_FLOW.get(recovery_type, [])
        
        for item in config:
            progress = item['progress']
            message = item.get('message', '')
            
            if progress == "calculated":
                # 动态计算进度
                progress = self._calculate_recovery_progress(**kwargs)
            
            if 'message_template' in item:
                message = item['message_template'].format(**kwargs)
            
            await self.report_progress(
                item['step'], progress, message
            )
    
    async def report_ocr_flow_progress(self, step_index: int = None):
        """报告OCR流程进度"""
        if step_index is not None:
            # 报告特定步骤
            if 0 <= step_index < len(ProgressConfig.OCR_FLOW):
                config = ProgressConfig.OCR_FLOW[step_index]
                await self.report_progress(
                    config['step'], 
                    config['progress'], 
                    config['message']
                )
        else:
            # 报告所有步骤
            for config in ProgressConfig.OCR_FLOW:
                await self.report_progress(
                    config['step'], 
                    config['progress'], 
                    config['message']
                )
    
    def _calculate_recovery_progress(self, completed_pages: int, total_pages: int, **kwargs):
        """计算恢复进度"""
        base_progress = 40
        progress_range = 30
        if total_pages > 0:
            return base_progress + int(completed_pages / total_pages * progress_range)
        return base_progress


def get_recovery_progress(recovery_point: str) -> int:
    """
    根据恢复点返回适当的进度值
    
    Args:
        recovery_point: 恢复点类型
        
    Returns:
        int: 对应的进度百分比
    """
    recovery_progress_map = {
        "document_created": 20,     # Document已创建
        "pdf_converted": 40,        # PDF转换完成
        "ocr_partial": 50,          # OCR部分完成
        "ocr_completed": 70,        # OCR完全完成  
        "chunk_store": 85,          # 分块存储完成
        "embedding_store": 90,      # 准备向量存储
        "completed": 100            # 完全完成
    }
    
    return recovery_progress_map.get(recovery_point, 0)
