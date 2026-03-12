"""
文档服务模块
处理文档相关的业务逻辑，包括创建、更新、查询等操作
"""
import os
import uuid
import json
import hashlib
import glob
import httpx
from datetime import datetime
from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import and_
import fitz  # PyMuPDF

from app.db.session import SessionLocal
from app.db.models import Document, Page, Chunk, Block
from app.service.minio_service import minio_service
from app.utils.pdf_extractor import PDFExtractor
from app.config import MEDIA_CENTER_ENDPOINT, MEDIA_CENTER_TIMEOUT
import logging

logger = logging.getLogger(__name__)

try:
    font = fitz.Font("cjk")  # 字体
except Exception as e:
    raise Exception(f"Failed to load cjk font. {e}\n无法加载cjk字体。")


def get_upload_info(upload_uuid: str) -> Dict[str, Any]:
    """
    通过API接口获取文件信息
    
    Args:
        upload_uuid: 上传文件UUID
        
    Returns:
        dict: 文件信息字典
    """
    try:
        with httpx.Client(timeout=MEDIA_CENTER_TIMEOUT) as client:
            response = client.get(f"{MEDIA_CENTER_ENDPOINT}/api/v1/upload/{upload_uuid}")
            response.raise_for_status()
            return response.json()
    except httpx.HTTPError as e:
        logger.error(f"获取上传文件信息失败: {e}, upload_uuid: {upload_uuid}")
        raise Exception(f"获取上传文件信息失败: {str(e)}")
    except Exception as e:
        logger.error(f"获取上传文件信息时发生未知错误: {e}, upload_uuid: {upload_uuid}")
        raise


def get_pdf_page_count(file_path: str) -> int:
    """获取PDF页数"""
    try:
        # 检查文件是否存在
        if not os.path.exists(file_path):
            logger.error(f"PDF文件不存在: {file_path}")
            return 0
        
        # 检查文件大小
        file_size = os.path.getsize(file_path)
        if file_size == 0:
            logger.error(f"PDF文件为空: {file_path}")
            return 0
        
        with PDFExtractor(file_path) as extractor:
            page_count = extractor.page_count
            if page_count <= 0:
                logger.error(f"PDF页数无效: {page_count}, 文件: {file_path}")
                return 0
            return page_count
    except Exception as e:
        logger.error(f"获取PDF页数失败: {e}, 文件: {file_path}")
        return 0


def download_file_from_minio(file_info: Dict[str, Any], task_uuid: str) -> str:
    """
    从MinIO下载文件到本地
    
    Args:
        file_info: 文件信息字典
        task_uuid: 任务UUID，用于创建临时目录
        
    Returns:
        str: 本地文件路径
    """
    upload_uuid = file_info["uuid"]
    temp_dir = f"/tmp/documents/{upload_uuid}"
    logger.info(f"temp_dir: {temp_dir}")
    os.makedirs(temp_dir, exist_ok=True)
    
    local_file_path = os.path.join(temp_dir, "original.pdf")
    
    # 检查文件是否已存在
    if os.path.exists(local_file_path):
        logger.info(f"文件已存在，跳过下载: {local_file_path}")
        return local_file_path
    
    try:
        # 从MinIO下载文件
        object_name = file_info["path"]
        logger.info(f"object_name: {object_name}")
        file_data = minio_service.get_file_data(object_name)
        
        # 保存到本地
        with open(local_file_path, 'wb') as f:
            f.write(file_data)
        
        logger.info(f"文件下载完成: {local_file_path}, 大小: {len(file_data)} bytes")
        return local_file_path
        
    except Exception as e:
        logger.error(f"从MinIO下载文件失败: {e}")
        raise


def create_document_record(uuid_str: str, user_uuid: str, upload_info: Dict[str, Any], 
                          file_path: str, task_uuid: str) -> Document:
    """
    创建Document记录
    
    Args:
        uuid_str: 文档UUID
        user_uuid: 用户UUID  
        upload_info: 上传文件信息字典
        file_path: 本地文件路径
        task_uuid: 关联的任务UUID
        
    Returns:
        Document: 创建的文档记录
    """    
    # 获取PDF页数
    pages_num = get_pdf_page_count(file_path)
    
    db = SessionLocal()
    try:
        document = Document(
            uuid=uuid_str,
            user_uuid=user_uuid,
            upload_uuid=upload_info["uuid"],
            pages_num=pages_num,
            file_ext=upload_info["file_ext"],
            filename=f'document_{upload_info["uuid"]}.{upload_info["file_ext"]}',
            file_size=upload_info["file_size"],
            md5_hash=upload_info["md5_hash"],
            sha1_hash=upload_info["sha1_hash"],
            bucket=upload_info["bucket"],
            path=upload_info["path"],
            is_ready=False,
            summary=None,
            created_at=datetime.now()
        )
        
        db.add(document)
        db.commit()
        db.refresh(document)
        
        # 记录日志
        logger.info(f"Document created: {uuid_str}, file: {document.filename}, "
                   f"pages: {pages_num}, size: {document.file_size}, task: {task_uuid}")
        
        return document
    finally:
        db.close()


def get_document_by_uuid(document_uuid: str) -> Optional[Document]:
    """根据UUID获取文档记录"""
    db = SessionLocal()
    try:
        return db.query(Document).filter(
            and_(Document.uuid == document_uuid, Document.deleted_at.is_(None))
        ).first()
    finally:
        db.close()


def get_document_by_upload_uuid(upload_uuid: str) -> Optional[Document]:
    """
    根据upload_uuid获取文档记录
    """
    db = SessionLocal()
    try:
        return db.query(Document).filter(
            and_(
                Document.upload_uuid == upload_uuid,
                Document.deleted_at.is_(None)
            )
        ).first()
    finally:
        db.close()


def update_document_pages(document_uuid: str, pages_num: int):
    """更新文档页数"""
    db = SessionLocal()
    try:
        document = db.query(Document).filter(Document.uuid == document_uuid).first()
        if document:
            document.pages_num = pages_num
            document.updated_at = datetime.now()
            db.commit()
    finally:
        db.close()


def mark_document_ready(document_uuid: str):
    """标记文档为就绪状态"""
    db = SessionLocal()
    try:
        document = db.query(Document).filter(Document.uuid == document_uuid).first()
        if document:
            document.is_ready = True
            document.updated_at = datetime.now()
            db.commit()
            logger.info(f"Document marked as ready: {document_uuid}")
    finally:
        db.close()


def get_document_pages(document_uuid: str) -> List[Page]:
    """获取文档的页面记录"""
    db = SessionLocal()
    try:
        return db.query(Page).filter(
            and_(
                Page.document_uuid == document_uuid,
                Page.deleted_at.is_(None)
            )
        ).order_by(Page.page_number).all()
    finally:
        db.close()


def get_document_chunks(document_uuid: str) -> List[Chunk]:
    """获取文档的分块记录"""
    db = SessionLocal()
    try:
        return db.query(Chunk).filter(
            and_(
                Chunk.document_uuid == document_uuid,
                Chunk.deleted_at.is_(None)
            )
        ).order_by(Chunk.index).all()
    finally:
        db.close()


def save_page_ocr_result(document_uuid: str, page_number: int, ocr_content: str, page_width: int = 0, page_height: int = 0, is_final: bool = False):
    """
    保存单页OCR结果到数据库
    
    Args:
        document_uuid: 文档UUID
        page_number: 页码
        ocr_content: OCR识别的文本内容
        page_width: 页像素宽度
        page_height: 页像素高度
        is_final: 是否为最终内容（Markdown格式化后）
    """
    db = SessionLocal()
    try:
        # 检查是否已存在该页面记录
        existing_page = db.query(Page).filter(
            Page.document_uuid == document_uuid,
            Page.page_number == page_number
        ).first()
        
        if existing_page:
            # 更新现有记录
            existing_page.markdown_content = ocr_content
            existing_page.page_width = page_width
            existing_page.page_height = page_height
            existing_page.updated_at = datetime.now()
        else:
            # 创建新记录
            page = Page(
                uuid=str(uuid.uuid4()),
                document_uuid=document_uuid,
                page_number=page_number,
                page_width=page_width,
                page_height=page_height,
                markdown_content=ocr_content,
                created_at=datetime.now()
            )
            db.add(page)
        
        db.commit()
        logger.debug(f"保存页面{page_number}的{'最终' if is_final else 'OCR'}内容到数据库")
    finally:
        db.close()


def check_page_ocr_exists(document_uuid: str, page_number: int) -> bool:
    """
    检查指定页面是否已经存在OCR记录
    
    Args:
        document_uuid: 文档UUID
        page_number: 页码
        
    Returns:
        bool: 如果页面已存在OCR记录且有内容则返回True，否则返回False
    """
    db = SessionLocal()
    try:
        existing_page = db.query(Page).filter(
            Page.document_uuid == document_uuid,
            Page.page_number == page_number,
            Page.deleted_at.is_(None)
        ).first()
        
        # 检查页面是否存在且有markdown内容
        if existing_page and existing_page.markdown_content:
            # 检查内容是否不为空（去除空白字符后）
            if existing_page.markdown_content.strip():
                logger.debug(f"页面{page_number}已存在OCR记录，跳过OCR处理")
                return True
        
        return False
    finally:
        db.close()


# 计算填满宽和高的多行字体大小
def calculateFontSize(text, w, h):
    if h > w:  # 竖排转为横排计算
        w, h = h, w
    
    # 字体大小初值，从行高开始估算
    fontsize = round(h / 2)  # 初始估算：假设至少需要2行
    logger.info(f"text: {text}")
    logger.info(f"original fontsize: {fontsize}, w: {w}, h: {h}, text length: {len(text)}")
    minSize = 5  # 大小下限
    
    def getTextDimensions(text, fontsize):
        """计算文本在指定字体大小下的宽度和所需行数"""
        if not text.strip():
            return 0, 1
        
        # 计算单行文本宽度
        text_width = font.text_length(text, fontsize=fontsize)
        
        # 计算需要的行数
        lines_needed = max(1, int((text_width / w) + 0.99))  # 向上取整
        
        return text_width, lines_needed
    
    def getTextHeight(fontsize, lines_needed):
        """计算文本在指定字体大小和行数下的总高度"""
        line_height = fontsize * 1.2  # 行高通常是字体大小的1.2倍
        return line_height * lines_needed
    
    # 首先找到一个合适的起始点
    while fontsize >= minSize:
        text_width, lines_needed = getTextDimensions(text, fontsize)
        total_height = getTextHeight(fontsize, lines_needed)
        
        if total_height <= h:
            break
        fontsize -= 1
    
    # 精确调整：增大字体直到刚好超过限制
    while fontsize < h:  # 防止无限循环
        test_fontsize = fontsize + 1
        text_width, lines_needed = getTextDimensions(text, test_fontsize)
        total_height = getTextHeight(test_fontsize, lines_needed)
        
        if total_height > h:
            break
        fontsize = test_fontsize
    
    # 最后精调：以0.1为步长减小字体
    while fontsize >= minSize:
        text_width, lines_needed = getTextDimensions(text, fontsize)
        total_height = getTextHeight(fontsize, lines_needed)
        
        if total_height <= h:
            break
        fontsize -= 0.1

    return max(minSize, fontsize)


def save_page_blocks(document_uuid: str, page_number: int, blocks: List[Dict[str, Any]]):
    """
    保存页面的blocks数据到数据库
    
    Args:
        document_uuid: 文档UUID
        page_number: 页码
        blocks: blocks数据列表，每个元素包含label、content、bbox
    """
    db = SessionLocal()
    try:
        # 先获取页面UUID
        page = db.query(Page).filter(
            Page.document_uuid == document_uuid,
            Page.page_number == page_number
        ).first()
        
        if not page:
            logger.error(f"找不到页面记录: document_uuid={document_uuid}, page_number={page_number}")
            return
        
        page_uuid = page.uuid
        page_width = page.page_width
        page_height = page.page_height
        
        # 删除该页面已存在的blocks（如果有的话）
        db.query(Block).filter(
            Block.document_uuid == document_uuid,
            Block.page_uuid == page_uuid
        ).delete()
        
        # 保存新的blocks
        for idx, block_data in enumerate(blocks):
            # 处理bbox字段，计算比例坐标
            bbox_left_ratio = bbox_top_ratio = bbox_width = bbox_height = None
            font_size_px = None
            bbox_value = block_data.get('bbox', None)
            
            if bbox_value is not None and isinstance(bbox_value, list) and len(bbox_value) >= 4:
                if page_width and page_height and page_width > 0 and page_height > 0:
                    x1, y1, x2, y2 = bbox_value[:4]
                    # 转换为left, top, width, height百分比
                    bbox_left_ratio = float(x1) / float(page_width)
                    bbox_top_ratio = float(y1) / float(page_height)
                    bbox_width = float(x2 - x1)
                    bbox_height = float(y2 - y1)
               
            block = Block(
                uuid=str(uuid.uuid4()),
                document_uuid=document_uuid,
                page_uuid=page_uuid,
                label=block_data.get('label'),
                content=block_data.get('content'),
                font_size_px="15",
                bbox_left_ratio=bbox_left_ratio,
                bbox_top_ratio=bbox_top_ratio,
                bbox_width=bbox_width,
                bbox_height=bbox_height,
                created_at=datetime.now()
            )
            db.add(block)
        
        db.commit()
        logger.debug(f"保存页面{page_number}的{len(blocks)}个blocks到数据库")
    except Exception as e:
        logger.error(f"保存页面blocks失败: {e}")
        db.rollback()
    finally:
        db.close()


def update_page_markdown_content(page_uuid: str, markdown_content: str):
    """更新页面的Markdown内容"""
    db = SessionLocal()
    try:
        page = db.query(Page).filter(Page.uuid == page_uuid).first()
        if page:
            page.markdown_content = markdown_content
            page.updated_at = datetime.now()
            db.commit()
    finally:
        db.close()


def save_pages_to_database(document_uuid: str, pages_content: List[Dict], task_uuid: str):
    """保存页面内容到数据库（用于兼容，实际上OCR结果已经保存了）"""
    db = SessionLocal()
    try:
        for page_data in pages_content:
            # 更新为最终的Markdown内容
            save_page_ocr_result(
                document_uuid=document_uuid,
                page_number=page_data["page_number"],
                ocr_content=page_data["markdown_content"],
                page_width=page_data.get("page_width", 0),
                page_height=page_data.get("page_height", 0),
                is_final=True
            )
        
        logger.info(f"更新了{len(pages_content)}页的最终Markdown内容")
    finally:
        db.close()


def save_chunks_to_database(document_uuid: str, chunks: List[Dict], task_uuid: str):
    """保存分块到数据库"""
    db = SessionLocal()
    try:
        for i, chunk_data in enumerate(chunks):
            chunk = Chunk(
                document_uuid=document_uuid,
                index=i,
                content=chunk_data["content"],
                meta=chunk_data.get("meta", {}),
                page_numbers=",".join(map(str, chunk_data.get("page_numbers", []))),
                created_at=datetime.now()
            )
            db.add(chunk)
        
        db.commit()
        logger.info(f"Saved {len(chunks)} chunks for document: {document_uuid}")
    finally:
        db.close()


def cleanup_temp_files(file_path: str = None, png_files: List[str] = None):
    """清理临时文件"""
    try:
        if file_path and os.path.exists(file_path):
            # 删除整个临时目录
            temp_dir = os.path.dirname(file_path)
            if temp_dir.startswith("/tmp/documents/"):
                import shutil
                shutil.rmtree(temp_dir, ignore_errors=True)
                logger.info(f"清理临时目录: {temp_dir}")
    except Exception as e:
        logger.error(f"清理临时文件失败: {e}")


def check_document_exists_in_db(upload_uuid: str) -> dict:
    """
    检查数据库中是否已存在该上传文件的完整记录
    
    Returns:
        dict: {
            "exists": bool,  # 是否存在
            "is_ready": bool,  # 是否已完成
            "document": Document or None,  # 文档记录
            "needs_resume": bool  # 是否需要断点恢复
        }
    """
    document = get_document_by_upload_uuid(upload_uuid)
    if not document:
        return {
            "exists": False,
            "is_ready": False,
            "document": None,
            "needs_resume": False
        }
    
    # 如果文档已标记为ready，说明已完成
    if document.is_ready:
        logger.info(f"文档已完成解析: upload_uuid={upload_uuid}, document_uuid={document.uuid}")
        return {
            "exists": True,
            "is_ready": True,
            "document": document,
            "needs_resume": False
        }
    
    # 检查是否有页面记录
    pages = get_document_pages(document.uuid)
    if not pages:
        return {
            "exists": True,
            "is_ready": False,
            "document": document,
            "needs_resume": True
        }
    
    # 检查是否有分块记录
    chunks = get_document_chunks(document.uuid)
    if not chunks:
        return {
            "exists": True,
            "is_ready": False,
            "document": document,
            "needs_resume": True
        }
    
    # 如果有完整的页面和分块记录，但is_ready为False，可能是数据不一致
    # 这种情况下也认为文档已存在，需要标记为ready
    logger.warning(f"文档有完整记录但未标记为ready: upload_uuid={upload_uuid}, document_uuid={document.uuid}")
    return {
        "exists": True,
        "is_ready": False,
        "document": document,
        "needs_resume": True
    }
