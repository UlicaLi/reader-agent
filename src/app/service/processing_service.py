"""
文档处理服务模块
包含PDF转换、OCR处理、Markdown转换、文档分块等功能
"""
import os
import httpx
from typing import List, Dict, Any
from app.service.document_service import (get_document_by_upload_uuid, save_pages_to_database, 
                                  save_chunks_to_database, mark_document_ready, get_document_by_uuid, get_document_pages)
from app.utils.pdf_extractor import PDFExtractor
from app.utils.chunker import chunk_markdown_pages
from app.utils.embedding import EmbeddingService
from app.service.task_service import send_progress_sse
from app.service.document_service import save_page_ocr_result, save_page_blocks, check_page_ocr_exists
from app.config import MEDIA_CENTER_ENDPOINT
from app.db.models import Chunk
from app.db.session import SessionLocal
from sqlalchemy.orm import Session
import logging

logger = logging.getLogger(__name__)


def convert_pdf_to_png(file_path: str, document_uuid: str, task_uuid: str, user_uuid: str) -> List[str]:
    """
    将PDF转换为PNG图片
    
    Args:
        file_path: PDF文件路径
        document_uuid: 文档UUID
        task_uuid: 任务UUID
        user_uuid: 用户UUID
        
    Returns:
        List[str]: PNG文件路径列表
    """
    upload_uuid = os.path.basename(os.path.dirname(file_path))
    png_dir = f"/tmp/documents/{upload_uuid}/pages"
    os.makedirs(png_dir, exist_ok=True)
    
    png_files = []
    
    try:
        with PDFExtractor(file_path) as extractor:
            page_count = extractor.page_count
            logger.info(f"开始转换PDF，共{page_count}页: {file_path}")
            
            for page_num in range(page_count):
                png_file = os.path.join(png_dir, f"page_{page_num + 1:03d}.png")
                extractor.convert_page_to_png(page_num, png_file)
                png_files.append(png_file)
                
                # 可以在这里发送详细进度更新
                logger.debug(f"转换完成页面 {page_num + 1}/{page_count}: {png_file}")
        
        logger.info(f"PDF转换完成，生成{len(png_files)}个PNG文件")
        return png_files
        
    except Exception as e:
        logger.error(f"PDF转PNG转换失败: {e}")
        raise


async def call_ocr_api(image_data: bytes) -> Dict[str, Any]:
    """
    调用OCR API进行文字识别
    
    Args:
        image_data: 图片数据
        
    Returns:
        Dict[str, Any]: OCR识别结果
    """
    try:
        url = f"{MEDIA_CENTER_ENDPOINT}/api/v1/ocr"
        
        files = {"file": ("image.png", image_data, "image/png")}
        
        # 设置无限超时，避免超时重试
        async with httpx.AsyncClient(timeout=None) as client:
            response = await client.post(url, files=files)
            response.raise_for_status()
            
            result = response.json()
            return result
            
    except Exception as e:
        logger.error(f"OCR API调用失败: {e}")
        raise


async def process_ocr_batch(png_files: List[str], document_uuid: str, task_uuid: str, user_uuid: str) -> List[Dict]:
    """
    批量处理OCR识别，并直接保存到Pages表
    
    Args:
        png_files: PNG文件路径列表
        document_uuid: 文档UUID
        task_uuid: 任务UUID
        user_uuid: 用户UUID
        
    Returns:
        List[Dict]: OCR结果列表，每个包含页码和文本内容
    """
    
    results = []
    total_files = len(png_files)
    
    for i, png_file in enumerate(png_files):
        try:
            page_number = i + 1
            
            # 检查页面是否已经存在OCR记录
            if check_page_ocr_exists(document_uuid, page_number):
                logger.info(f"页面{page_number}已存在OCR记录，跳过OCR处理")
                
                # 从数据库获取已存在的页面内容
                pages = get_document_pages(document_uuid)
                existing_page = next((p for p in pages if p.page_number == page_number), None)
                
                if existing_page:
                    page_result = {
                        "page_number": page_number,
                        "file_path": png_file,
                        "markdown_content": existing_page.markdown_content
                    }
                    results.append(page_result)
                    
                    # 更新进度
                    base_progress = 40  # OCR从40%开始
                    progress_range = 30  # OCR占用30%的进度(40%-70%)
                    current_progress = base_progress + int((i + 1) / total_files * progress_range)
                    
                    await send_progress_sse(user_uuid, task_uuid, "ocr_processing", current_progress, 
                                          f"OCR识别进度: {i+1}/{total_files} 页 (已跳过)")
                continue
            
            # 读取图片文件
            with open(png_file, 'rb') as f:
                image_data = f.read()
            
            # 调用OCR API，返回字典结构
            ocr_result = await call_ocr_api(image_data)
            
            # 获取markdown内容
            markdown_list = ocr_result.get("markdown", [])
            if not isinstance(markdown_list, list) or len(markdown_list) == 0:
                raise ValueError(f"OCR结果markdown字段格式错误，期望非空列表，实际: {type(markdown_list)}")
            
            page_markdown_content = markdown_list[0]
            page_blocks = ocr_result.get("blocks", [])

            page_width = ocr_result.get("image_width")
            page_height = ocr_result.get("image_height")
            
            if page_width is None or page_height is None:
                raise ValueError(f"OCR结果缺少image_width或image_height字段，OCR结果: {ocr_result.keys()}")
            
            page_result = {
                "page_number": page_number,
                "file_path": png_file,
                "markdown_content": page_markdown_content
            }
            results.append(page_result)
            
            # 直接保存页面的markdown内容到Pages表
            save_page_ocr_result(document_uuid, page_number, page_markdown_content, page_width, page_height, is_final=True)
            
            # 保存页面的blocks数据到Blocks表
            save_page_blocks(document_uuid, page_number, page_blocks)
            
            
            # 更新进度
            base_progress = 40  # OCR从40%开始
            progress_range = 30  # OCR占用30%的进度(40%-70%)
            current_progress = base_progress + int((i + 1) / total_files * progress_range)
            
            await send_progress_sse(user_uuid, task_uuid, "ocr_processing", current_progress, 
                                  f"OCR识别进度: {i+1}/{total_files} 页")
                
        except Exception as e:
            logger.error(f"处理页面{i+1} OCR失败: {e}")
            logger.error(f"PNG文件: {png_file}")
            if 'ocr_result' in locals():
                logger.error(f"OCR结果: {ocr_result}")
    
    if len(results) == 0:
        logger.error(f"OCR处理失败，没有结果")
        raise Exception("OCR处理失败，没有结果")
    else:
        logger.info(f"OCR批量处理完成，共{total_files}页，成功{len(results)}页")
    
    return results


async def process_single_page_ocr(document_uuid: str, page_number: int) -> Dict[str, Any]:
    """
    对单个页面进行OCR处理
    
    Args:
        document_uuid: 文档UUID
        page_number: 页码（从1开始）
        
    Returns:
        Dict[str, Any]: OCR处理结果，包含markdown_content和blocks
        
    Raises:
        ValueError: 当文档不存在或页码无效时
        Exception: OCR处理失败时
    """
    from app.service.document_service import get_document_by_uuid, get_upload_info, download_file_from_minio
    
    logger.info(f"开始处理单页面OCR: document_uuid={document_uuid}, page_number={page_number}")
    
    # 1. 获取文档信息
    document = get_document_by_uuid(document_uuid)
    if not document:
        raise ValueError(f"文档不存在: {document_uuid}")
    
    # 2. 获取PDF文件路径
    upload_uuid = document.upload_uuid
    temp_dir = f"/tmp/documents/{upload_uuid}"
    pdf_path = os.path.join(temp_dir, "original.pdf")
    
    # 如果PDF文件不存在，从MinIO下载
    if not os.path.exists(pdf_path):
        logger.info(f"PDF文件不存在，从MinIO下载: {pdf_path}")
        file_info = get_upload_info(upload_uuid)
        pdf_path = download_file_from_minio(file_info, f"single_page_ocr_{document_uuid}")
    
    # 3. 转换指定页面为PNG
    png_dir = f"{temp_dir}/pages"
    os.makedirs(png_dir, exist_ok=True)
    png_file = os.path.join(png_dir, f"page_{page_number:03d}.png")
    
    try:
        with PDFExtractor(pdf_path) as extractor:
            extractor.convert_page_to_png(page_number - 1, png_file)
        
        # 4. 读取PNG文件并调用OCR API
        with open(png_file, 'rb') as f:
            image_data = f.read()
        
        ocr_result = await call_ocr_api(image_data)
        
        # 5. 解析OCR结果
        markdown_list = ocr_result.get("markdown", [])
        
        page_markdown_content = markdown_list[0]
        page_blocks = ocr_result.get("blocks", [])

        page_width = ocr_result.get("image_width")
        page_height = ocr_result.get("image_height")
        
        # 7. 保存到数据库
        save_page_ocr_result(document_uuid, page_number, page_markdown_content, page_width, page_height, is_final=True)
        save_page_blocks(document_uuid, page_number, page_blocks)
        
        logger.info(f"单页面OCR处理完成: document_uuid={document_uuid}, page_number={page_number}")
        
        # 7. 清理临时PNG文件
        try:
            os.remove(png_file)
            logger.debug(f"清理临时PNG文件: {png_file}")
        except Exception as e:
            logger.warning(f"清理临时PNG文件失败: {e}")
        
        return {
            "success": True,
            "page_number": page_number,
            "markdown_content": page_markdown_content,
            "blocks": page_blocks
        }
        
    except Exception as e:
        logger.error(f"单页面OCR处理失败: document_uuid={document_uuid}, page_number={page_number}, 错误: {e}")
        # 清理临时文件
        try:
            if os.path.exists(png_file):
                os.remove(png_file)
        except:
            pass
        raise


def convert_to_markdown_pages(document_uuid: str) -> List[Dict]:
    """
    从Pages表中获取已保存的Markdown内容
    
    Args:
        document_uuid: 文档UUID
        
    Returns:
        List[Dict]: 页面内容列表，包含页码和Markdown内容
    """
    
    # 从数据库获取页面记录
    pages = get_document_pages(document_uuid)
    if not pages:
        logger.error(f"未找到文档页面记录: {document_uuid}")
        return []
    
    pages_content = []
    
    for page in pages:
        page_number = page.page_number
        markdown_content = page.markdown_content or ""
        
        page_content = {
            "page_number": page_number,
            "markdown_content": markdown_content
        }
        pages_content.append(page_content)
    
    logger.info(f"获取页面内容完成，共{len(pages_content)}页")
    return pages_content


def chunk_document_content(pages_content: List[Dict], document_uuid: str) -> List[Dict]:
    """
    对文档内容进行分块处理
    
    Args:
        pages_content: 页面内容列表
        document_uuid: 文档UUID
        
    Returns:
        List[Dict]: 分块结果列表
    """
    # 准备输入数据格式
    markdown_pages = [
        {
            "markdown": page["markdown_content"],
            "pageIndex": page["page_number"]
        }
        for page in pages_content
    ]
    
    # 定义标题分割规则
    header_rules = [
        ("#", "Header 1"),
        ("##", "Header 2"),
        ("###", "Header 3"),
    ]
    
    chunks = []
    try:
        # 使用现有的分块函数
        for i, doc in enumerate(chunk_markdown_pages(markdown_pages, header_rules)):
            chunk_data = {
                "content": doc.page_content,
                "index": i,  # 添加索引字段
                "meta": doc.metadata,
                "page_numbers": doc.metadata.get("pageIndex", [])
            }
            chunks.append(chunk_data)
        
        logger.info(f"文档分块完成，共生成{len(chunks)}个块")
        return chunks
        
    except Exception as e:
        logger.error(f"文档分块失败: {e}")


def store_chunks_to_vector_db(chunks: List[Dict], document_uuid: str):
    """
    将分块存储到向量数据库
    
    Args:
        chunks: 分块数据列表，每个元素包含 content, index, meta, page_numbers 等字段
        document_uuid: 文档UUID
        
    Raises:
        Exception: 向量数据库存储失败时抛出异常
    """
    if not chunks:
        logger.warning(f"没有chunks需要存储到向量数据库，文档: {document_uuid}")
        return
        
    logger.info(f"开始将{len(chunks)}个chunks存储到向量数据库，文档: {document_uuid}")
    
    # 创建数据库会话
    db: Session = SessionLocal()
    
    try:
        # 从数据库中获取对应的Chunk对象
        chunk_objects = []
        for chunk_data in chunks:
            # 根据document_uuid和index查找对应的Chunk对象
            chunk_obj = db.query(Chunk).filter(
                Chunk.document_uuid == document_uuid,
                Chunk.index == chunk_data.get("index"),
                Chunk.deleted_at.is_(None)
            ).first()
            
            if chunk_obj:
                chunk_objects.append(chunk_obj)
            else:
                logger.warning(f"未找到对应的Chunk对象: document_uuid={document_uuid}, index={chunk_data.get('index')}")
        
        if not chunk_objects:
            error_msg = f"没有找到有效的Chunk对象，向量数据库存储失败，文档: {document_uuid}"
            logger.error(error_msg)
            raise Exception(error_msg)
        
        # 创建EmbeddingService实例并处理chunks
        embedding_service = EmbeddingService()
        processed_count = embedding_service.process_chunks(chunk_objects)
        
        logger.info(f"成功将{processed_count}个chunks存储到向量数据库，文档: {document_uuid}")
        
    except Exception as e:
        logger.error(f"向量数据库存储失败: {e}")
        # 向量存储失败应该导致整个任务失败
        raise Exception(f"向量数据库存储失败: {e}")
    finally:
        db.close()


def store_document_data(upload_uuid: str, pages_content: List[Dict], task_uuid: str, document_uuid: str = None):
    """
    存储文档数据到数据库, 包含页面保存、分块和向量化存储
    
    Raises:
        Exception: 当任何步骤失败时抛出异常，包括向量数据库存储失败
    """
    # 如果没有传入document_uuid，则通过upload_uuid查询
    if not document_uuid:
        document = get_document_by_upload_uuid(upload_uuid)
        if not document:
            raise ValueError(f"找不到对应的文档记录: {upload_uuid}")
        document_uuid = document.uuid
    else:
        # 验证document_uuid是否有效
        document = get_document_by_uuid(document_uuid)
        if not document:
            raise ValueError(f"找不到对应的文档记录: {document_uuid}")
    
    try:
        # 保存页面内容
        save_pages_to_database(document_uuid, pages_content, task_uuid)
        
        # 文档分块
        chunks = chunk_document_content(pages_content, document_uuid)
        
        # 保存分块
        save_chunks_to_database(document_uuid, chunks, task_uuid)

        # 向量化存储（关键步骤，失败时应该抛出异常）
        store_chunks_to_vector_db(chunks, document_uuid)
        
        # 只有在所有步骤都成功后才标记文档为就绪
        mark_document_ready(document_uuid)
        
        logger.info(f"文档数据存储完成: {document_uuid}")
        
    except Exception as e:
        logger.error(f"文档数据存储失败: {document_uuid}, 错误: {e}")
        # 重新抛出异常，确保调用者知道存储失败
        raise

