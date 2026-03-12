# Application configuration constants
import os
import dotenv
dotenv.load_dotenv()

APP_NAME = "yogu-reader-agent"
APP_DESCRIPTION = "Yogu Reader Agent"
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "http://localhost:1422,http://127.0.0.1:1422,https://tauri.localhost")

DB_HOST = os.getenv("DB_HOST", "116.62.145.230")
DB_PORT = os.getenv("DB_PORT", 23306)
DB_USER = os.getenv("DB_USER", "root")
DB_PASSWORD = os.getenv("DB_PASSWORD", "on4yfitg5vjxoakn")
DB_NAME = os.getenv("DB_NAME", "ocr_data")

# 数据库配置
DATABASE_URL = os.getenv(
    "DATABASE_URL", 
    f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
)

# Celery 配置
CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379")
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379")

# Media Center服务配置 (OCR和Upload接口统一base URL)
MEDIA_CENTER_ENDPOINT = os.getenv("MEDIA_CENTER_ENDPOINT", "http://localhost:8001")
MEDIA_CENTER_TIMEOUT = int(os.getenv("MEDIA_CENTER_TIMEOUT", 30))

# 嵌入服务配置
EMBED_BASE_URL = os.getenv("EMBED_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
EMBED_API_KEY = os.getenv("EMBED_API_KEY", "sk-88c8437bf2b34c2f9a357bc604157bc7")
EMBED_MODEL = os.getenv("EMBED_MODEL", "text-embedding-v4")
EMBED_DIMENSION = int(os.getenv("EMBED_DIMENSION", 1024))
EMBED_OUTPUT_TYPE = os.getenv("EMBED_OUTPUT_TYPE", "dense&sparse")
EMBED_MAX_RETRIES = int(os.getenv("EMBED_MAX_RETRIES", 3))
EMBED_TIMEOUT = int(os.getenv("EMBED_TIMEOUT", 30))
EMBED_ENABLE_MODEL = os.getenv("EMBED_ENABLE_MODEL", "true").lower() == "true"

# Milvus向量数据库配置
MILVUS_URI = os.getenv("MILVUS_URI", "./doc_chunk.db")
MILVUS_COLLECTION_NAME = os.getenv("MILVUS_COLLECTION_NAME", "chunk_hybrid")
MILVUS_BATCH_SIZE = int(os.getenv("MILVUS_BATCH_SIZE", 50))
MILVUS_MAX_TEXT_LENGTH = int(os.getenv("MILVUS_MAX_TEXT_LENGTH", 4096))
MILVUS_ENABLE_MODEL = os.getenv("MILVUS_ENABLE_MODEL", "true").lower() == "true"
MILVUS_RETRY_ON_FAILURE = os.getenv("MILVUS_RETRY_ON_FAILURE", "true").lower() == "true"
MILVUS_MAX_RETRIES = int(os.getenv("MILVUS_MAX_RETRIES", 3))

# MinIO 配置
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "oss.noread.pro")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "xjonkrkezmuoef7d")
MINIO_SECURE = os.getenv("MINIO_SECURE", "True")
MINIO_BUCKET = os.getenv("MINIO_BUCKET", "yogu-media")


#Embedding配置
DASHSCOPE_HTTP_BASE_URL = os.getenv("DASHSCOPE_HTTP_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY", "sk-88c8437bf2b34c2f9a357bc604157bc7")
DASHSCOPE_MODEL_NAME = os.getenv("DASHSCOPE_MODEL_NAME", "text-embedding-v4")
DASHSCOPE_DIMENSION = int(os.getenv("DASHSCOPE_DIMENSION", 1024))
DASHSCOPE_OUTPUT_TYPE = os.getenv("DASHSCOPE_OUTPUT_TYPE", "dense&sparse")
DASHSCOPE_MAX_RETRIES = int(os.getenv("DASHSCOPE_MAX_RETRIES", 3))
DASHSCOPE_TIMEOUT = int(os.getenv("DASHSCOPE_TIMEOUT", 30))
DASHSCOPE_ENABLE_MODEL = os.getenv("DASHSCOPE_ENABLE_MODEL", "true").lower() == "true"

# SSE配置
REDIS_SSE_URL = os.getenv("REDIS_SSE_URL", "redis://localhost:6379/3")
REDIS_SSE_PASSWORD = os.getenv("REDIS_SSE_PASSWORD", "")

# 翻译相关配置
TRANSLATION_LABELS = os.getenv("TRANSLATION_LABELS", "text,figure_title,paragraph_title").split(",")
