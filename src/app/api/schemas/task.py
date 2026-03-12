from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field


class TaskResponse(BaseModel):
    """任务响应模型，对应Task数据库实体"""
    id: int = Field(..., description="任务ID")
    uuid: str = Field(..., description="任务UUID")
    user_uuid: Optional[str] = Field(None, description="用户UUID")
    type: str = Field(..., description="任务类型")
    status: int = Field(..., description="任务状态")
    input: Optional[str] = Field(None, description="任务输入数据")
    output: Optional[str] = Field(None, description="任务输出数据")
    message: Optional[str] = Field(None, description="任务消息")
    progress: int = Field(..., description="任务进度(0-100)")
    started_at: Optional[datetime] = Field(None, description="开始时间")
    finished_at: Optional[datetime] = Field(None, description="完成时间")
    created_at: datetime = Field(..., description="创建时间")
    updated_at: Optional[datetime] = Field(None, description="更新时间")
    
    class Config:
        from_attributes = True


class TaskCreateRequest(BaseModel):
    """创建任务请求模型"""
    upload_uuids: List[str] = Field(..., description="文件上传UUID")


class TaskProgressData(BaseModel):
    """任务进度数据模型"""
    task_uuid: str = Field(..., description="任务UUID")
    step: str = Field(..., description="当前步骤")
    progress: int = Field(..., description="进度百分比")
    message: str = Field(..., description="进度消息")
    timestamp: str = Field(..., description="时间戳")


class RecoveryInfo(BaseModel):
    """恢复信息模型"""
    task_uuid: str
    upload_uuid: str
    current_progress: int
    last_message: str
    recovery_point: Optional[str] = None
    document_uuid: Optional[str] = None
    available_files: dict = {}

