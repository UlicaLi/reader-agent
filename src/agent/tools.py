import uuid
from google.adk.tools import ToolContext
import dashscope
from http import HTTPStatus
from pymilvus import (
    connections,
    utility,
    Collection,
    AnnSearchRequest,
    WeightedRanker,
    RRFRanker
)
from typing import Optional, Dict
from sqlalchemy.exc import SQLAlchemyError
import logging
from app.config import MILVUS_URI, MILVUS_COLLECTION_NAME, EMBED_API_KEY
import os
import json
from datetime import datetime

# 导入数据库相关模块
from app.db import get_db, Document, Page, Chunk, Question, Block

# 设置日志
logger = logging.getLogger(__name__)


def get_document_metadata(tool_context: ToolContext) -> Dict:
    """获取文档元数据 - 从数据库查询真实的文档信息"""
    document_uuids = tool_context.state.get("document_uuids")
    
    if not document_uuids:
        logger.warning("未找到document_uuids")
        return None
    
    # 使用第一个文档UUID
    document_uuid = document_uuids[0]
    
    try:
        db_gen = get_db()
        session = next(db_gen)
        
        # 查询文档信息
        document = session.query(Document).filter(
            Document.uuid == document_uuid,
            Document.deleted_at.is_(None)  # 只查询未删除的文档
        ).first()
        
        if not document:
            logger.warning(f"未找到文档: {document_uuid}")
            return None

        document_metadata = {
            "id": document.id,
            "uuid": document.uuid,
            "user_uuid": document.user_uuid,
            "pages_num": document.pages_num,
            "file_ext": document.file_ext,
            "filename": document.filename,
            "file_size": document.file_size,
            "md5_hash": document.md5_hash,
            "sha1_hash": document.sha1_hash,
            "bucket": document.bucket,
            "path": document.path,
            "summary": document.summary,
            "created_at": document.created_at.isoformat() if document.created_at else None,
            "updated_at": document.updated_at.isoformat() if document.updated_at else None,
            "deleted_at": document.deleted_at.isoformat() if document.deleted_at else None,
        }

        return document_metadata
        
    except SQLAlchemyError as e:
        logger.error(f"数据库查询失败: {str(e)}")
        return None
    except Exception as e:
        logger.error(f"获取文档元数据时发生未知错误: {str(e)}")
        return None
    finally:
        if 'session' in locals():
            session.close()


def get_page_content(tool_context: ToolContext, page_number: int) -> Dict:
    """获取页面内容 - 从数据库查询真实的页面信息"""
    document_uuids = tool_context.state.get("document_uuids")
    
    if not document_uuids:
        logger.warning("未找到document_uuids")
        return None
    
    # 使用第一个文档UUID
    document_uuid = document_uuids[0]
    
    if page_number <= 0:
        logger.warning(f"无效的页码: {page_number}")
        return None
    
    try:
        db_gen = get_db()
        session = next(db_gen)
        
        # 查询页面信息
        page = session.query(Page).filter(
            Page.document_uuid == document_uuid,
            Page.page_number == page_number,
            Page.deleted_at.is_(None)  # 只查询未删除的页面
        ).first()
        
        if not page:
            logger.warning(f"未找到页面: 文档{document_uuid}, 页码{page_number}")
            return None
        
        page_content = {
            "id": page.id,
            "uuid": page.uuid,
            "document_uuid": page.document_uuid,
            "page_number": page.page_number,
            "markdown_content": page.markdown_content,
            "created_at": page.created_at.isoformat() if page.created_at else None,
            "updated_at": page.updated_at.isoformat() if page.updated_at else None,
            "deleted_at": page.deleted_at.isoformat() if page.deleted_at else None,
        }
        
        return page_content
        
    except SQLAlchemyError as e:
        logger.error(f"数据库查询失败: {str(e)}")
        return None
    except Exception as e:
        logger.error(f"获取页面内容时发生未知错误: {str(e)}")
        return None
    finally:
        if 'session' in locals():
            session.close()

# 计算chunks数量
def count_chunks(tool_context: ToolContext) -> Dict:
    """获取文档的chunk总数 - 从数据库查询真实的chunk数量"""
    document_uuids = tool_context.state.get("document_uuids")
    
    if not document_uuids:
        logger.warning("未找到document_uuids")
        return None
    
    # 使用第一个文档UUID
    document_uuid = document_uuids[0]
    
    try:
        db_gen = get_db()
        session = next(db_gen)
        
        # 查询chunk总数
        total_count = session.query(Chunk).filter(
            Chunk.document_uuid == document_uuid,
            Chunk.deleted_at.is_(None)  # 只统计未删除的chunk
        ).count()
        
        logger.info(f"文档 {document_uuid} 共有 {total_count} 个chunks")
        
        return total_count
        
    except SQLAlchemyError as e:
        logger.error(f"数据库查询失败: {str(e)}")
        return None
    except Exception as e:
        logger.error(f"统计chunk数量时发生未知错误: {str(e)}")
        return None
    finally:
        if 'session' in locals():
            session.close()


def seek_chunks(tool_context: ToolContext, offset: int, limit: Optional[int]) -> Dict:
    """分页获取chunk列表 - 从数据库查询真实的chunk信息"""
    document_uuids = tool_context.state.get("document_uuids")
    
    if not document_uuids:
        logger.warning("未找到document_uuids")
        return None

    if not limit:
        limit = 10
    
    # 使用第一个文档UUID
    document_uuid = document_uuids[0]
    
    if offset < 0 or limit < 0:
        logger.warning(f"无效的参数: offset={offset}, limit={limit}")
        return None
    
    # 限制最大返回数量为10
    limit = min(limit, 10)
    
    try:
        db_gen = get_db()
        session = next(db_gen)
        
        # 查询总数
        total_count = session.query(Chunk).filter(
            Chunk.document_uuid == document_uuid,
            Chunk.deleted_at.is_(None)
        ).count()
        
        # 分页查询chunks
        chunks_result = session.query(Chunk).filter(
            Chunk.document_uuid == document_uuid,
            Chunk.deleted_at.is_(None)
        ).order_by(Chunk.index).offset(offset).limit(limit)
        
        chunks = []
        for chunk in chunks_result:
            chunk_data = {
                "id": chunk.id,
                "document_uuid": chunk.document_uuid,
                "index": chunk.index,
                "content": chunk.content,
                "meta": chunk.meta,
                "page_numbers": chunk.page_numbers,
                "created_at": chunk.created_at.isoformat() if chunk.created_at else None,
                "updated_at": chunk.updated_at.isoformat() if chunk.updated_at else None,
                "deleted_at": chunk.deleted_at.isoformat() if chunk.deleted_at else None,
            }
            chunks.append(chunk_data)
        
        result_data = {
            "chunks": chunks,
            "total": total_count,
            "offset": offset,
            "limit": limit,
            "has_more": offset + limit < total_count,
            "returned_count": len(chunks),
        }
        
        return result_data
        
    except SQLAlchemyError as e:
        logger.error(f"数据库查询失败: {str(e)}")
        return None
    except Exception as e:
        logger.error(f"获取chunk列表时发生未知错误: {str(e)}")
        return None
    finally:
        if 'session' in locals():
            session.close()


def get_chunk_content(tool_context: ToolContext, chunk_id: str) -> Dict:
    """获取特定chunk的详细内容 - 从数据库查询真实的chunk数据"""
    document_uuids = tool_context.state.get("document_uuids")
    
    if not document_uuids:
        logger.warning("未找到document_uuids")
        return None
    
    # 使用第一个文档UUID
    document_uuid = document_uuids[0]
    
    # 解析chunk_id，支持多种格式
    chunk_index = None
    if chunk_id.isdigit():
        # 如果是纯数字，直接使用
        chunk_index = int(chunk_id)
    elif "_" in chunk_id:
        # 如果包含下划线，尝试解析后缀
        try:
            chunk_index = int(chunk_id.split("_")[-1])
        except ValueError:
            logger.warning(f"无法解析chunk_id: {chunk_id}")
            return None
    else:
        logger.warning(f"无法解析chunk_id: {chunk_id}")
        return None
    
    try:
        db_gen = get_db()
        session = next(db_gen)
        
        # 根据document_uuid和index查询chunk
        chunk = session.query(Chunk).filter(
            Chunk.document_uuid == document_uuid,
            Chunk.index == chunk_index,
            Chunk.deleted_at.is_(None)  # 只查询未删除的chunk
        ).first()
        
        if not chunk:
            logger.warning(f"未找到chunk: 文档{document_uuid}, 索引{chunk_index}")
            return None
        
        chunk_data = {
            "id": chunk.id,
            "document_uuid": chunk.document_uuid,
            "index": chunk.index,
            "chunk_id": f"chunk_{chunk.index}",  # 生成标准格式的chunk_id
            "content": chunk.content,
            "meta": chunk.meta,
            "page_numbers": chunk.page_numbers,
            "created_at": chunk.created_at.isoformat() if chunk.created_at else None,
            "updated_at": chunk.updated_at.isoformat() if chunk.updated_at else None,
            "deleted_at": chunk.deleted_at.isoformat() if chunk.deleted_at else None,
        }
        
        return chunk_data
        
    except SQLAlchemyError as e:
        logger.error(f"数据库查询失败: {str(e)}")
        return None
    except Exception as e:
        logger.error(f"获取chunk内容时发生未知错误: {str(e)}")
        return None
    finally:
        if 'session' in locals():
            session.close()


def _generate_query_embeddings(query: str) -> Dict:
    """使用DashScope生成查询文本的嵌入向量"""
    try:
        os.environ["DASHSCOPE_API_KEY"] = EMBED_API_KEY
        resp = dashscope.TextEmbedding.call(
            model="text-embedding-v4",
            input=query,
            dimension=1024,  # 指定向量维度（仅 text-embedding-v3及 text-embedding-v4支持该参数）
            output_type="dense&sparse"
        )

        print(resp) if resp.status_code == HTTPStatus.OK else print(resp)
        
        # 提取嵌入向量
        embeddings = resp.output["embeddings"]
        embedding_data = embeddings[0]
        dense_vector = embedding_data.get("embedding", [])
        sparse_embedding = embedding_data.get("sparse_embedding", [])
        
        # 转换稀疏向量格式
        sparse_vector = {}
        for item in sparse_embedding:
            if "index" in item and "value" in item:
                sparse_vector[item["index"]] = item["value"]
        
        logger.info(f"生成嵌入向量成功，密集向量维度: {len(dense_vector)}, 稀疏向量非零元素: {len(sparse_vector)}")
        
        return {
            "dense_vector": dense_vector,
            "sparse_vector": sparse_vector
        }
        
    except Exception as e:
        logger.error(f"生成嵌入向量时发生错误: {str(e)}")
        return None


def _create_search_requests(dense_vector: list, sparse_vector: dict, document_uuid: str, top_k: int):
    """创建密集向量和稀疏向量的搜索请求"""
    # 构建过滤表达式 - 更新字段名从document_id到document_uuid
    filter_expr = f'document_uuid == "{document_uuid}"'
    
    # 搜索参数
    search_params = {
        "metric_type": "IP",
        "params": {
            "radius": 0.4,
            "range_filter": 1.0
        }
    }
    
    # 创建密集向量搜索请求
    dense_req = AnnSearchRequest(
        data=[dense_vector],
        anns_field="dense_vector",
        param=search_params,
        limit=top_k,
        expr=filter_expr
    )
    
    # 创建稀疏向量搜索请求
    sparse_req = AnnSearchRequest(
        data=[sparse_vector],
        anns_field="sparse_vector", 
        param=search_params,
        limit=top_k,
        expr=filter_expr
    )
    
    return dense_req, sparse_req


def _execute_hybrid_search(collection: Collection, dense_req, sparse_req, top_k: int):
    """执行混合搜索"""
    try:
        # 使用RRF重排器
        rrf_k = 60
        reranker = RRFRanker(k=rrf_k)
        
        # 执行混合搜索 - 更新output_fields以匹配新的schema
        output_fields = ["content", "chunk_id", "document_uuid", "index", "meta", "page_numbers"]
        
        logger.info("执行混合搜索...")
        hybrid_search_results = collection.hybrid_search(
            reqs=[dense_req, sparse_req],
            rerank=reranker,
            limit=top_k,
            output_fields=output_fields,
        )
        
        # 提取搜索结果
        results_hits = []
        if hybrid_search_results and hybrid_search_results[0]:
            results_hits = hybrid_search_results[0]
        
        logger.info(f"混合搜索完成，获得 {len(results_hits)} 条命中结果")
        
        return results_hits
        
    except Exception as e:
        logger.error(f"执行混合搜索时发生错误: {str(e)}")
        return None


def _format_search_results(results_hits: list) -> list:
    """格式化搜索结果为chunks格式"""
    relevant_chunks = []
    
    # 处理None或空结果的情况
    if not results_hits:
        logger.warning("搜索结果为空或None")
        return relevant_chunks
    
    for hit in results_hits:
        entity = hit.entity
        
        # 解析meta字段（如果是JSON字符串）
        meta_data = entity.get("meta", "{}")
        if isinstance(meta_data, str):
            try:
                import json
                meta_parsed = json.loads(meta_data)
            except (json.JSONDecodeError, TypeError):
                meta_parsed = {}
        else:
            meta_parsed = meta_data if meta_data else {}
        
        chunk_data = {
            "id": entity.get("chunk_id"),
            "document_uuid": entity.get("document_uuid"),
            "index": entity.get("index"),
            "chunk_id": f"chunk_{entity.get('index', 0)}",
            "content": entity.get("content", ""),
            "meta": {
                "chunk_type": "text",
                "relevance_score": round(hit.score, 4),
                **meta_parsed  # 合并原有的meta数据
            },
            "page_numbers": entity.get("page_numbers", ""),
        }
        relevant_chunks.append(chunk_data)
    
    return relevant_chunks


def _connect_and_load_collection():
    """连接Milvus并加载集合"""
    try:
        connections.connect(uri=MILVUS_URI)
        collection = Collection(MILVUS_COLLECTION_NAME)
        collection.load()
        return collection
    except Exception as e:
        logger.error(f"连接Milvus或加载集合失败: {str(e)}")
        raise


def search_chunks(tool_context: ToolContext, query: str):
    """语义搜索相关chunks - 使用DashScope和Milvus进行混合搜索"""
    document_uuids = tool_context.state.get("document_uuids")

    if not document_uuids:
        logger.warning("未找到document_uuids")
        return None
    
    # 使用第一个文档UUID作为过滤条件
    document_uuid = document_uuids[0]
    
    try:
        logger.info(f"开始搜索chunks，查询: '{query}', 文档: {document_uuid}")
        
        # 1. 生成嵌入向量
        embedding_result = _generate_query_embeddings(query)
        if not embedding_result:
            logger.error("生成嵌入向量失败")
            return []
            
        dense_vector = embedding_result["dense_vector"]
        sparse_vector = embedding_result["sparse_vector"]
        
        # 2. 连接Milvus并加载集合
        collection = _connect_and_load_collection()
        
        # 3. 创建搜索请求
        top_k = 3
        dense_req, sparse_req = _create_search_requests(
            dense_vector, sparse_vector, document_uuid, top_k
        )
        
        # 4. 执行混合搜索
        search_result = _execute_hybrid_search(collection, dense_req, sparse_req, top_k)
        
        # 5. 格式化搜索结果
        relevant_chunks = _format_search_results(search_result)
        
        logger.info(f"搜索完成，返回 {len(relevant_chunks)} 个相关chunks")
        
        return relevant_chunks
        
    except Exception as e:
        logger.error(f"搜索chunks时发生错误: {str(e)}", exc_info=True)
        return []


def get_document_summary(tool_context: ToolContext):
    """获取文档摘要"""
    document_uuids = tool_context.state.get("document_uuids")
    if not document_uuids:
        logger.warning("未找到document_uuids")
        return None
    
    # 使用第一个文档UUID
    document_uuid = document_uuids[0]

    try:
        db_gen = get_db()
        session = next(db_gen)

        document = session.query(Document).filter(
            Document.uuid == document_uuid,
            Document.deleted_at.is_(None)
        ).first()

        if document:
            summary = document.summary
            logger.info(f"获取文档摘要成功: {summary}")
            return summary
        else:
            logger.warning(f"未找到文档: {document_uuid}")
            return None
        
    except Exception as e:
        logger.error(f"获取文档摘要时发生未知错误: {str(e)}")
        return None
    finally:
        if 'session' in locals():
            session.close()