from sqlalchemy import Column, BigInteger, String, Integer, Text, DateTime, CHAR, JSON, Boolean, DECIMAL
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.sql import func
from .session import Base


# 任务状态常量定义
class TaskStatus:
    """任务状态常量"""

    PENDING = 0  # 等待中
    RUNNING = 1  # 运行中
    COMPLETED = 2  # 已完成
    FAILED = 3  # 失败
    CANCELLED = 4  # 已取消


class TaskSteps:
    """任务步骤常量"""
    DOWNLOAD_FILE = "download_file"        # 下载文件
    DOCUMENT_CREATED = "document_created"  # 文档记录已创建
    PDF_TO_PNG = "pdf_to_png"             # PDF转PNG
    OCR_PROCESSING = "ocr_processing"      # OCR识别
    MARKDOWN_CONVERT = "markdown_convert"  # 转换Markdown
    CHUNK_PROCESSING = "chunk_processing"  # 文档分块
    STORE_DATABASE = "store_database"      # 存储数据库
    COMPLETED = "completed"                # 完成
    ERROR = "error"                        # 错误


class Document(Base):
    """文档表模型"""

    __tablename__ = "documents"

    # 主键，自增
    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键，自增")

    # 唯一标识符
    uuid = Column(CHAR(36), nullable=False, unique=True, comment="唯一标识符")

    # 用户UUID
    user_uuid = Column(CHAR(36), nullable=False, comment="用户UUID")

    # 上传UUID
    upload_uuid = Column(CHAR(36), nullable=False, comment="上传UUID")

    # 页数
    pages_num = Column(Integer, nullable=False, default=0, comment="页数")

    # 文件扩展名
    file_ext = Column(String(16), nullable=True, comment="文件扩展名")

    # 文件名
    filename = Column(String(255), nullable=True, comment="文件名")

    # 文件大小（字节）
    file_size = Column(
        BigInteger, nullable=False, default=0, comment="文件大小（字节）"
    )

    # MD5 哈希
    md5_hash = Column(CHAR(32), nullable=True, comment="MD5 哈希")

    # SHA1 哈希
    sha1_hash = Column(CHAR(40), nullable=True, comment="SHA1 哈希")

    # 存储桶
    bucket = Column(String(64), nullable=True, comment="存储桶")

    # 存储路径
    path = Column(String(512), nullable=True, comment="存储路径")

    # 是否处理好
    is_ready = Column(Boolean, nullable=False, default=False, comment="是否处理好")

    # 摘要
    summary = Column(Text, nullable=True, comment="摘要")

    # 创建时间
    created_at = Column(
        DateTime,
        nullable=False,
        server_default=func.current_timestamp(),
        comment="创建时间",
    )

    # 更新时间
    updated_at = Column(
        DateTime, nullable=True, onupdate=func.current_timestamp(), comment="更新时间"
    )

    # 删除时间（软删除）
    deleted_at = Column(DateTime, nullable=True, comment="删除时间")

    def __repr__(self):
        return f"<Document(id={self.id}, uuid='{self.uuid}', user_uuid='{self.user_uuid}', filename='{self.filename}', file_ext='{self.file_ext}')>"

    def to_dict(self):
        """转换为字典格式"""
        return {
            "id": self.id,
            "uuid": self.uuid,
            "user_uuid": self.user_uuid,
            "pages_num": self.pages_num,
            "file_ext": self.file_ext,
            "filename": self.filename,
            "file_size": self.file_size,
            "md5_hash": self.md5_hash,
            "sha1_hash": self.sha1_hash,
            "bucket": self.bucket,
            "path": self.path,
            "summary": self.summary,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
        }


class Page(Base):
    """页面表模型"""

    __tablename__ = "pages"

    # 主键，自增
    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键，自增")

    # 唯一标识符
    uuid = Column(CHAR(36), nullable=False, comment="唯一标识符")

    # 文档UUID
    document_uuid = Column(CHAR(36), nullable=False, comment="文档UUID")

    # 页码
    page_number = Column(Integer, nullable=False, default=1, comment="页码")

    # 页像素宽度
    page_width = Column(Integer, nullable=False, default=0, comment="页像素宽度")

    # 页像素高度
    page_height = Column(Integer, nullable=False, default=0, comment="页像素高度")

    # Markdown内容
    markdown_content = Column(LONGTEXT, nullable=True, comment="Markdown内容")

    # 创建时间
    created_at = Column(
        DateTime,
        nullable=False,
        server_default=func.current_timestamp(),
        comment="创建时间",
    )

    # 更新时间
    updated_at = Column(
        DateTime, nullable=True, onupdate=func.current_timestamp(), comment="更新时间"
    )

    # 删除时间（软删除）
    deleted_at = Column(DateTime, nullable=True, comment="删除时间")

    def __repr__(self):
        return f"<Page(id={self.id}, uuid='{self.uuid}', document_uuid='{self.document_uuid}', page_number={self.page_number})>"

    def to_dict(self):
        """转换为字典格式"""
        return {
            "id": self.id,
            "uuid": self.uuid,
            "document_uuid": self.document_uuid,
            "page_number": self.page_number,
            "page_width": self.page_width,
            "page_height": self.page_height,
            "markdown_content": self.markdown_content,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
        }


class Block(Base):
    """块表模型"""

    __tablename__ = "blocks"

    # 主键，自增
    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键，自增")

    # 唯一标识符
    uuid = Column(CHAR(36), nullable=False, unique=True, comment="唯一标识符")

    # 文档UUID
    document_uuid = Column(CHAR(36), nullable=False, comment="文档UUID")

    # 页UUID
    page_uuid = Column(CHAR(36), nullable=False, comment="页UUID")

    # 标签
    label = Column(String(64), nullable=True, comment="标签")

    # 内容
    content = Column(Text, nullable=True, comment="内容")

    # 字体大小（单位：px）
    font_size_px = Column(DECIMAL(5, 2), nullable=True, comment="字体大小（单位：px）")

    # 边界框比例坐标
    bbox_left_ratio = Column(DECIMAL(10, 6), nullable=True, comment="边界框左侧位置比例(%)")
    bbox_top_ratio = Column(DECIMAL(10, 6), nullable=True, comment="边界框顶部位置比例(%)")
    bbox_width = Column(Integer, nullable=True, comment="边界框宽度（单位：px）")
    bbox_height = Column(Integer, nullable=True, comment="边界框高度（单位：px）")

    # 创建时间
    created_at = Column(
        DateTime,
        nullable=False,
        server_default=func.current_timestamp(),
        comment="创建时间",
    )

    # 更新时间
    updated_at = Column(
        DateTime, nullable=True, onupdate=func.current_timestamp(), comment="更新时间"
    )

    # 删除时间（软删除）
    deleted_at = Column(DateTime, nullable=True, comment="删除时间")

    def __repr__(self):
        return f"<Block(id={self.id}, document_uuid='{self.document_uuid}', page_uuid='{self.page_uuid}', label='{self.label}')>"

    def to_dict(self):
        """转换为字典格式"""
        return {
            "id": self.id,
            "uuid": self.uuid,
            "document_uuid": self.document_uuid,
            "page_uuid": self.page_uuid,
            "label": self.label,
            "content": self.content,
            "font_size_px": float(self.font_size_px) if self.font_size_px is not None else None,
            "bbox_left_ratio": float(self.bbox_left_ratio) if self.bbox_left_ratio is not None else None,
            "bbox_top_ratio": float(self.bbox_top_ratio) if self.bbox_top_ratio is not None else None,
            "bbox_width": float(self.bbox_width) if self.bbox_width is not None else None,
            "bbox_height": float(self.bbox_height) if self.bbox_height is not None else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
        }


class Task(Base):
    """任务表模型"""

    __tablename__ = "tasks"

    # 主键，自增
    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键，自增")

    # 唯一标识符
    uuid = Column(CHAR(36), nullable=False, unique=True, comment="唯一标识符")

    # 用户UUID
    user_uuid = Column(CHAR(36), nullable=True, comment="用户UUID")

    # 任务类型
    type = Column(String(64), nullable=False, comment="任务类型")

    # 任务状态
    status = Column(
        Integer,
        nullable=False,
        default=TaskStatus.PENDING,
        comment="任务状态：0-等待中，1-运行中，2-已完成，3-失败，4-已取消",
    )

    # 任务输入
    input = Column(LONGTEXT, nullable=True, comment="任务输入数据")

    # 任务输出
    output = Column(LONGTEXT, nullable=True, comment="任务输出数据")

    # 错误信息
    message = Column(Text, nullable=True, comment="错误信息")

    # 进度信息
    progress = Column(Integer, nullable=False, default=0, comment="任务进度（0-100）")

    # 开始时间
    started_at = Column(DateTime, nullable=True, comment="开始时间")

    # 完成时间
    finished_at = Column(DateTime, nullable=True, comment="完成时间")

    # 创建时间
    created_at = Column(
        DateTime,
        nullable=False,
        server_default=func.current_timestamp(),
        comment="创建时间",
    )

    # 更新时间
    updated_at = Column(
        DateTime, nullable=True, onupdate=func.current_timestamp(), comment="更新时间"
    )

    # 删除时间（软删除）
    deleted_at = Column(DateTime, nullable=True, comment="删除时间")

    def __repr__(self):
        return f"<Task(id={self.id}, uuid='{self.uuid}', type='{self.type}', status={self.status})>"

    def to_dict(self):
        """转换为字典格式"""
        return {
            "id": self.id,
            "uuid": self.uuid,
            "user_uuid": self.user_uuid,
            "type": self.type,
            "status": self.status,
            "input": self.input,
            "output": self.output,
            "message": self.message,
            "progress": self.progress,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
        }


class Chunk(Base):
    """文档块表模型"""

    __tablename__ = "chunks"

    # 主键，自增
    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键，自增")

    # 文档UUID
    document_uuid = Column(CHAR(36), nullable=False, comment="文档UUID")

    # chunk索引
    index = Column(Integer, nullable=False, default=0, comment="chunk索引")

    # 内容
    content = Column(Text, nullable=True, comment="内容")

    # 元数据
    meta = Column(JSON, nullable=True, comment="元数据")

    # 页码列表
    page_numbers = Column(String(128), nullable=True, comment="页码列表")

    # 创建时间
    created_at = Column(
        DateTime,
        nullable=False,
        server_default=func.current_timestamp(),
        comment="创建时间",
    )

    # 更新时间
    updated_at = Column(
        DateTime, nullable=True, onupdate=func.current_timestamp(), comment="更新时间"
    )

    # 删除时间（软删除）
    deleted_at = Column(DateTime, nullable=True, comment="删除时间")

    def __repr__(self):
        return f"<Chunk(id={self.id}, document_uuid='{self.document_uuid}', index={self.index})>"

    def to_dict(self):
        """转换为字典格式"""
        return {
            "id": self.id,
            "document_uuid": self.document_uuid,
            "index": self.index,
            "content": self.content,
            "meta": self.meta,
            "page_numbers": self.page_numbers,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
        }


class Question(Base):
    """问题列表表模型"""

    __tablename__ = "questions"

    # 主键，自增
    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键，自增")

    # 唯一标识符
    uuid = Column(CHAR(36), nullable=False, comment="唯一标识符")

    # 用户UUID
    user_uuid = Column(CHAR(36), nullable=False, comment="用户UUID")

    # 文档UUID
    document_uuid = Column(CHAR(36), nullable=False, comment="文档UUID")

    # 推荐问题
    question = Column(Text, nullable=True, comment="推荐问题")

    # 推荐问题类型
    question_type = Column(String(16), nullable=False, comment="推荐问题类型")

    # 创建时间
    created_at = Column(
        DateTime,
        nullable=False,
        server_default=func.current_timestamp(),
        comment="创建时间",
    )

    # 更新时间
    updated_at = Column(
        DateTime, nullable=True, onupdate=func.current_timestamp(), comment="更新时间"
    )

    # 删除时间（软删除）
    deleted_at = Column(DateTime, nullable=True, comment="删除时间")

    def __repr__(self):
        return f"<Question(id={self.id}, uuid='{self.uuid}', user_uuid='{self.user_uuid}', document_uuid='{self.document_uuid}', question_type='{self.question_type}')>"

    def to_dict(self):
        """转换为字典格式"""
        return {
            "id": self.id,
            "uuid": self.uuid,
            "user_uuid": self.user_uuid,
            "document_uuid": self.document_uuid,
            "question": self.question,
            "question_type": self.question_type,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
        }


class Translation(Base):
    """翻译表模型"""

    __tablename__ = "translations"

    # 主键，自增
    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键，自增")

    # 块UUID
    block_uuid = Column(CHAR(36), nullable=False, comment="块UUID")

    # 语言
    lang = Column(String(16), nullable=False, comment="语言")

    # 翻译内容
    content = Column(Text, nullable=True, comment="翻译内容")

    # 创建时间
    created_at = Column(
        DateTime,
        nullable=False,
        server_default=func.current_timestamp(),
        comment="创建时间",
    )

    # 更新时间
    updated_at = Column(
        DateTime, nullable=True, onupdate=func.current_timestamp(), comment="更新时间"
    )

    # 删除时间（软删除）
    deleted_at = Column(DateTime, nullable=True, comment="删除时间")

    def __repr__(self):
        return f"<Translation(id={self.id}, block_uuid='{self.block_uuid}', lang='{self.lang}')>"

    def to_dict(self):
        """转换为字典格式"""
        return {
            "id": self.id,
            "block_uuid": self.block_uuid,
            "lang": self.lang,
            "content": self.content,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
        }


