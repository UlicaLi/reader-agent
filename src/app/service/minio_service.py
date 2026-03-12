from minio import Minio
from minio.error import S3Error
import io
from datetime import datetime, timedelta
import random
import string
from typing import Optional
from app.config import MINIO_ENDPOINT, MINIO_ACCESS_KEY, MINIO_SECRET_KEY, MINIO_SECURE, MINIO_BUCKET


class MinioService:
    """MinIO 对象存储服务"""
    
    def __init__(self):
        self.client = Minio(
            MINIO_ENDPOINT,
            access_key=MINIO_ACCESS_KEY,
            secret_key=MINIO_SECRET_KEY,
            secure=MINIO_SECURE
        )
        self.bucket = MINIO_BUCKET
    
    def get_file_data(self, object_name: str) -> bytes:
        """从MinIO获取文件数据"""
        try:
            response = self.client.get_object(self.bucket, object_name)
            data = response.read()
            response.close()
            response.release_conn()
            return data
        except S3Error as e:
            raise Exception(f"Failed to get file from MinIO: {str(e)}")
    
    async def download_file(self, object_name: str) -> bytes:
        """下载文件数据（异步方法，兼容现有代码）"""
        return self.get_file_data(object_name)


# 创建全局MinIO服务实例
minio_service = MinioService()