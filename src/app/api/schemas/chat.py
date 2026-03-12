from pydantic import BaseModel
from typing import Optional


class Message(BaseModel):
    """消息模型，用于接收用户输入"""

    text: Optional[str] = None
    upload_uuids: list[str]
    session_uuid: Optional[str] = None


class ExplainMessage(BaseModel):
    """解释消息模型"""
    text: str
    #context: str
    upload_uuids: list[str]
    session_uuid: Optional[str] = None


class TranslateMessage(BaseModel):
    """翻译消息模型"""
    text: str
    #context: str
    source_language: str
    target_language: str
    upload_uuids: list[str]
    session_uuid: Optional[str] = None

class PageTranslateMessage(BaseModel):
    """页面翻译消息模型"""
    page_number: int
    source_language: str
    target_language: str
    upload_uuids: list[str]
    session_uuid: Optional[str] = None


class ConversationMessage(BaseModel):
    """对话消息模型"""
    role: str  # "user" 或 "assistant"
    content: str


class ConversationTopicRequest(BaseModel):
    """生成对话标题的请求模型"""
    messages: list[ConversationMessage]

