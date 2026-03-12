import json
import logging
import os
import sys
from typing import Dict, List, Any
import time
import dashscope
from http import HTTPStatus
from pymilvus import (
    connections,
    utility,
    FieldSchema,
    CollectionSchema,
    DataType,
    Collection,
)
from sqlalchemy.orm import Session
from app.db.models import Chunk
from app.db.session import SessionLocal
from app.config import (
    DASHSCOPE_API_KEY, 
    DASHSCOPE_MODEL_NAME, 
    DASHSCOPE_DIMENSION, 
    DASHSCOPE_OUTPUT_TYPE,
    MILVUS_URI,
    MILVUS_COLLECTION_NAME
)

# 设置默认值
DEFAULT_MILVUS_URI = MILVUS_URI
DEFAULT_COLLECTION_NAME = MILVUS_COLLECTION_NAME
DEFAULT_DASHSCOPE_DIMENSION = DASHSCOPE_DIMENSION

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class EmbeddingService:
    def __init__(
            self,
            milvus_uri: str = DEFAULT_MILVUS_URI,
            collection_name: str = DEFAULT_COLLECTION_NAME,
    ):
        self.milvus_uri = milvus_uri
        self.collection_name = collection_name
        self.collection = None

        self._connect_milvus()
        self._init_dashscope()
        self._init_collection()

    def _connect_milvus(self):
        logger.info(f"尝试连接到 Milvus 服务：{self.milvus_uri}")
        try:
            connections.connect(uri=self.milvus_uri)
            logger.info("成功连接到 Milvus。")
        except Exception as e:
            logger.error(f"连接 Milvus 失败：{e}")
            raise Exception(f"连接 Milvus 失败：{e}")

    def _init_dashscope(self):
        """初始化DashScope客户端"""
        logger.info("初始化 DashScope Embedding 服务...")
        
        # 设置API密钥
        api_key = DASHSCOPE_API_KEY
        if not api_key:
            logger.error("DashScope API密钥未设置")
            raise ValueError("DashScope API密钥未设置")
        
        dashscope.api_key = api_key
        logger.info("DashScope客户端初始化完成")

    def _init_collection(self):
        """初始化或获取Milvus集合"""
        if not utility.has_collection(self.collection_name):
            logger.info(f"集合 '{self.collection_name}' 不存在，正在创建...")
            self._create_schema_and_collection()
        else:
            logger.info(f"集合 '{self.collection_name}' 已存在，正在加载...")
            self.collection = Collection(self.collection_name)
        
        # 确保集合已加载
        if self.collection:
            self.collection.load()
            logger.info(f"集合 '{self.collection_name}' 加载完成。文档总数: {self.collection.num_entities}")

    def _create_schema_and_collection(self):
        """创建Chunk专用的Milvus Schema"""
        fields = [
            FieldSchema(name="pk", dtype=DataType.VARCHAR, is_primary=True, auto_id=True, max_length=100),
            FieldSchema(name="chunk_id", dtype=DataType.INT64),  # Chunk主键ID（用于关联数据库）
            FieldSchema(name="document_uuid", dtype=DataType.VARCHAR, max_length=100),  # 文档UUID
            FieldSchema(name="index", dtype=DataType.INT64),  # chunk索引
            FieldSchema(name="content", dtype=DataType.VARCHAR, max_length=65535),  # 内容
            FieldSchema(name="meta", dtype=DataType.VARCHAR, max_length=4096),  # 元数据(JSON)
            FieldSchema(name="page_numbers", dtype=DataType.VARCHAR, max_length=256),  # 页码列表
            FieldSchema(name="created_at", dtype=DataType.VARCHAR, max_length=64),  # 创建时间
            FieldSchema(name="updated_at", dtype=DataType.VARCHAR, max_length=64),  # 更新时间
            FieldSchema(name="deleted_at", dtype=DataType.VARCHAR, max_length=64),  # 删除时间
            FieldSchema(name="sparse_vector", dtype=DataType.SPARSE_FLOAT_VECTOR),
            FieldSchema(name="dense_vector", dtype=DataType.FLOAT_VECTOR, dim=DEFAULT_DASHSCOPE_DIMENSION)
        ]
        schema = CollectionSchema(fields, description="PDF文档分块集合 (混合搜索)")

        logger.info(f"正在为集合 '{self.collection_name}' 创建 schema...")
        self.collection = Collection(name=self.collection_name, schema=schema, consistency_level="Strong")

        logger.info(f"正在为稀疏向量字段 'sparse_vector' 创建索引 (SPARSE_INVERTED_INDEX)...")
        self.collection.create_index("sparse_vector", {"index_type": "SPARSE_INVERTED_INDEX", "metric_type": "IP"})
        logger.info(f"正在为密集向量字段 'dense_vector' 创建索引 (AUTOINDEX)...")
        self.collection.create_index("dense_vector", {"index_type": "AUTOINDEX", "metric_type": "IP"})
        logger.info("Schema 和索引创建完成。")

    def _prepare_chunk_text(self, chunk: Chunk) -> str:
        """准备Chunk的文本内容用于embedding"""
        text_parts = []
        
        # 添加主要内容
        if chunk.content:
            text_parts.append(chunk.content)
        
        # 添加元数据信息
        if chunk.meta:
            try:
                meta_data = json.loads(chunk.meta) if isinstance(chunk.meta, str) else chunk.meta
                if isinstance(meta_data, dict):
                    # 提取元数据中的文本信息
                    for key, value in meta_data.items():
                        if isinstance(value, str) and value.strip():
                            text_parts.append(f"{key}: {value}")
            except (json.JSONDecodeError, TypeError):
                logger.warning(f"解析chunk {chunk.id} 的meta失败")
        
        return ' '.join(filter(None, text_parts))

    def _generate_embedding(self, text: str) -> Dict[str, Any]:
        """使用DashScope生成embedding"""
        try:
            resp = dashscope.TextEmbedding.call(
                model=DASHSCOPE_MODEL_NAME,
                input=text,
                dimension=DASHSCOPE_DIMENSION,
                output_type=DASHSCOPE_OUTPUT_TYPE
            )
            
            if resp.status_code == HTTPStatus.OK:
                # 处理返回结果
                embeddings = resp.output["embeddings"]
                if embeddings and len(embeddings) > 0:
                    embedding_data = embeddings[0]  # 取第一个结果
                    
                    # 提取密集向量
                    dense_vector = embedding_data.get("embedding", [])
                    
                    # 提取稀疏向量
                    sparse_embedding = embedding_data.get("sparse_embedding", [])
                    sparse_vector = {}
                    for item in sparse_embedding:
                        if "index" in item and "value" in item:
                            sparse_vector[item["index"]] = item["value"]
                    
                    return {
                        "dense": dense_vector,
                        "sparse": sparse_vector
                    }
                else:
                    raise ValueError("DashScope返回的embedding为空")
            else:
                raise Exception(f"DashScope API调用失败: {resp.message}")
                
        except Exception as e:
            logger.error(f"生成embedding失败: {e}")
            raise

    def _create_milvus_entity(self, chunk: Chunk, text: str) -> Dict[str, Any]:
        """为单个Chunk创建Milvus实体，根据models.py中的Chunk表结构"""
        # 生成embedding
        embedding_result = self._generate_embedding(text)
        sparse_vector = embedding_result["sparse"]
        dense_vector = embedding_result["dense"]
        
        entity = {
            "chunk_id": chunk.id,
            "document_uuid": str(chunk.document_uuid),
            "index": chunk.index,
            "content": chunk.content or "",
            "meta": json.dumps(chunk.meta) if chunk.meta else "",
            "page_numbers": chunk.page_numbers or "",
            "created_at": chunk.created_at.isoformat() if chunk.created_at else "",
            "updated_at": chunk.updated_at.isoformat() if chunk.updated_at else "",
            "deleted_at": chunk.deleted_at.isoformat() if chunk.deleted_at else "",
            "sparse_vector": sparse_vector,
            "dense_vector": dense_vector
        }
        logger.info(f"创建Milvus实体: {entity['chunk_id']}, {entity['index']}")

        return entity

    def process_chunks(self, chunks: List[Chunk]) -> int:
        """
        处理Chunk列表并存储到Milvus
        
        Args:
            chunks: Chunk对象列表
            
        Returns:
            int: 成功处理的chunk数量
        """
        
        if not chunks:
            logger.warning("没有chunks需要处理")
            return 0
        
        logger.info(f"开始处理 {len(chunks)} 个chunks到Milvus...")
        
        # 批量处理chunks
        milvus_entities = []
        processed_count = 0
        
        for chunk in chunks:
            try:
                # 准备文本内容
                text = self._prepare_chunk_text(chunk)
                if not text.strip():
                    logger.warning(f"跳过空内容的chunk {chunk.id}")
                    continue
                
                # 创建Milvus实体
                entity = self._create_milvus_entity(chunk, text)
                milvus_entities.append(entity)
                processed_count += 1
                
            except Exception as e:
                logger.error(f"处理chunk {chunk.id} 失败: {e}")
                continue
        
        if not milvus_entities:
            logger.warning("没有有效的chunks需要插入到Milvus")
            return 0
        
        # 批量插入到Milvus
        logger.info(f"开始将 {len(milvus_entities)} 个chunks插入到Milvus...")
        batch_size = 100
        max_retries = 3
        
        for i in range(0, len(milvus_entities), batch_size):
            batch_to_insert = milvus_entities[i: i + batch_size]
            retry_count = 0
            success = False
            
            while retry_count < max_retries and not success:
                try:
                    insert_result = self.collection.insert(batch_to_insert)
                    logger.debug(f"已插入批次 {i // batch_size + 1}，包含 {len(batch_to_insert)} 个chunks")
                    success = True
                except Exception as e:
                    retry_count += 1
                    logger.error(f"将批次 {i // batch_size + 1} 插入 Milvus 失败 (重试 {retry_count}/{max_retries}): {e}")
                    if retry_count >= max_retries:
                        logger.error(f"批次 {i // batch_size + 1} 插入失败，已达到最大重试次数")
                    else:
                        time.sleep(1)  # 重试前等待1秒
        
        if processed_count > 0:
            self.collection.flush()
            logger.info(f"成功将 {processed_count} 个chunks存储到Milvus")
        else:
            logger.warning("没有chunks成功插入到Milvus")
        
        return processed_count

    def search_chunks(self, query_text: str, document_uuid: str = None, limit: int = 10) -> List[Dict[str, Any]]:
        """
        搜索chunks
        
        Args:
            query_text: 查询文本
            document_uuid: 限制搜索的文档ID（可选）
            limit: 返回结果数量限制
            
        Returns:
            List[Dict[str, Any]]: 搜索结果
        """
        if not self.collection:
            logger.error("Milvus集合未初始化")
            return []
        
        try:
            # 生成查询向量
            embedding_result = self._generate_embedding(query_text)
            query_sparse_vector = embedding_result["sparse"]
            query_dense_vector = embedding_result["dense"]
            
            # 构建搜索表达式
            search_params = {
                "metric_type": "IP",
                "params": {"nprobe": 10}
            }
            
            # 构建过滤表达式
            filter_expr = None
            if document_uuid is not None:
                filter_expr = f'document_uuid == "{document_uuid}"'
            
            # 执行混合搜索
            results = self.collection.search(
                data=[query_dense_vector],
                anns_field="dense_vector",
                param=search_params,
                limit=limit,
                expr=filter_expr,
                output_fields=["chunk_id", "document_uuid", "index", "content", "meta", "page_numbers", "created_at", "updated_at"]
            )
            
            # 格式化结果
            search_results = []
            for hits in results:
                for hit in hits:
                    result = {
                        "score": hit.score,
                        "chunk_id": hit.entity.get("chunk_id"),
                        "document_uuid": hit.entity.get("document_uuid"),
                        "index": hit.entity.get("index"),
                        "content": hit.entity.get("content", ""),
                        "meta": hit.entity.get("meta", ""),
                        "page_numbers": hit.entity.get("page_numbers", ""),
                        "created_at": hit.entity.get("created_at", ""),
                        "updated_at": hit.entity.get("updated_at", "")
                    }
                    search_results.append(result)
            
            return search_results
            
        except Exception as e:
            logger.error(f"搜索chunks失败: {e}")
            return []

if __name__ == "__main__":
    """
    主函数：从数据库中取出指定文档的 chunks 进行 embedding 并保存到 Milvus
    """
    
    # 添加项目根目录到 Python 路径
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
    sys.path.insert(0, project_root)
    
    # 指定的文档 UUID
    TARGET_DOCUMENT_UUID = "d2d1ee31-a4c0-497b-acac-d5ada2c1d0aa"
    
    def main():
        """主函数"""
        logger.info(f"开始处理文档 {TARGET_DOCUMENT_UUID} 的 chunks...")
        
        # 创建数据库会话
        db: Session = SessionLocal()
        
        try:
            # 查询指定文档的所有 chunks
            chunks = db.query(Chunk).filter(
                Chunk.document_uuid == TARGET_DOCUMENT_UUID,
                Chunk.deleted_at.is_(None)  # 排除已删除的 chunks
            ).order_by(Chunk.index).all()
            
            if not chunks:
                logger.warning(f"未找到文档 {TARGET_DOCUMENT_UUID} 的 chunks")
                return
            
            logger.info(f"找到 {len(chunks)} 个 chunks 需要处理")
            
            # 创建 EmbeddingService 实例
            embedding_service = EmbeddingService()
            
            # 处理 chunks 并保存到 Milvus
            processed_count = embedding_service.process_chunks(chunks)
            
            logger.info(f"成功处理了 {processed_count} 个 chunks 到 Milvus")
            
        except Exception as e:
            logger.error(f"处理 chunks 时发生错误: {e}")
            raise
        finally:
            db.close()
    
    if __name__ == "__main__":
        main() 