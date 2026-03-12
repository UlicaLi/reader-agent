import logging
from fastapi import Request, APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from google.adk.sessions import DatabaseSessionService
from google.adk.runners import Runner
from google.adk.agents.run_config import RunConfig, StreamingMode
from google.genai import types
from agent import agent
from app.api.schemas.chat import Message, ExplainMessage, TranslateMessage, ConversationTopicRequest, PageTranslateMessage
from app.service.document_service import calculateFontSize
from app.config import APP_NAME, TRANSLATION_LABELS
from app.db.session import SessionLocal
from app.db.models import Document
from agent.sub_agents.conversation_topic_agent.agent import conversation_topic
from agent.sub_agents.summary_agent.agent import summary_agent
from agent.sub_agents.explain_agent.agent import explain_agent
from agent.sub_agents.translate_agent.agent import translate_agent
from agent.sub_agents.anki_agent.agent import anki_agent
from agent.sub_agents.mindmap_agent.agent import mindmap_agent
from agent.sub_agents.question_agent.agent import question_agent
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, BaseMessage
# 导入数据库相关模块
from app.db import get_db, Document, Page, Chunk, Question, Block, Translation
# 导入创建document记录所需的函数
from app.service.document_service import get_upload_info, create_document_record, download_file_from_minio, cleanup_temp_files
import json
import uuid
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])


async def get_document_uuids_from_upload_uuids(upload_uuids: list[str]) -> list[str]:
    """
    根据upload_uuids查询对应的document_uuids
    
    Args:
        upload_uuids: 上传UUID列表
        
    Returns:
        document_uuids: 文档UUID列表
    """
    if not upload_uuids:
        return []
    
    db = SessionLocal()
    try:
        document_uuids = []
        for upload_uuid in upload_uuids:
            doc = db.query(Document).filter(Document.upload_uuid == upload_uuid).first()
            if doc:
                document_uuids.append(doc.uuid)
        return document_uuids
    finally:
        db.close()


async def get_or_create_session(
    session_service: DatabaseSessionService,
    request_state,
    document_uuids: list[str],
    session_uuid: str = None,
):
    """获取或创建会话，并更新会话状态"""
    user_uuid = request_state.current_user["user_uuid"]
    session_state = {
        "device": request_state.device,
        "app_version": request_state.app_version,
        "client_location": request_state.client_location,
        "client_time": request_state.client_time,
        "document_uuids": document_uuids,
        "user_uuid": user_uuid,
    }
    if not session_uuid:
        session = await session_service.create_session(
            app_name=APP_NAME, user_id=user_uuid, state=session_state
        )
    else:
        session = await session_service.get_session(
            app_name=APP_NAME,
            user_id=user_uuid,
            session_id=session_uuid,
        )
        if not session:
            session = await session_service.create_session(
                app_name=APP_NAME, user_id=user_uuid, state=session_state
            )
        else:
            session.state.update(session_state)
            await session_service.update_session(session)
    return session


async def check_document_access(document_uuids: list[str]):
    """检查文档访问权限和状态"""
    if not document_uuids:
        return

    db = SessionLocal()
    try:
        # 查询所有请求的文档
        documents = db.query(Document).filter(
            Document.uuid.in_(document_uuids),
            Document.deleted_at.is_(None)  # 排除已删除的文档
        ).all()
        
        # 检查是否有文档未找到
        found_uuids = {doc.uuid for doc in documents}
        missing_uuids = set(document_uuids) - found_uuids
        
        if missing_uuids:
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "documents_not_found",
                    "message": "部分文件未上传或不存在",
                    "missing_documents": list(missing_uuids)
                }
            )
        
        # 检查文档是否已处理完成
        not_ready_documents = []
        for doc in documents:
            if not doc.is_ready:
                not_ready_documents.append({
                    "uuid": doc.uuid,
                    "filename": doc.filename
                })
        
        if not_ready_documents:
            raise HTTPException(
                status_code=422,
                detail={
                    "error": "documents_not_ready",
                    "message": "部分文件还未处理完成，请稍后再试",
                    "not_ready_documents": not_ready_documents
                }
            )
            
    finally:
        db.close()


@router.post("/chat")
async def chat(request: Request, message: Message) -> StreamingResponse:
    logger.info(f"chat request: {message.model_dump_json(exclude_none=True, by_alias=True)}")
    text = message.text

    session_uuid = message.session_uuid
    session_service = DatabaseSessionService(db_url="sqlite:///./agent_session.db")
    user_uuid = request.state.current_user["user_uuid"]
    upload_uuids = message.upload_uuids
    
    # 根据upload_uuids，通过document表查询document_uuids
    document_uuids = await get_document_uuids_from_upload_uuids(upload_uuids)

    await check_document_access(document_uuids)

    session = await get_or_create_session(
        session_service, request.state, document_uuids, session_uuid
    )

    async def event_generator():
        runner = Runner(
            agent=agent.root_agent,
            app_name=APP_NAME,
            session_service=session_service,
        )
        events_async = runner.run_async(
            session_id=session.id,
            user_id=user_uuid,
            run_config=RunConfig(
                streaming_mode=StreamingMode.SSE,
                max_llm_calls=150,
            ),
            new_message=types.Content(role="user", parts=[types.Part(text=text)]),
        )

        async for event in events_async:
            if not event.partial:
                logger.info(event.model_dump_json(exclude_none=True, by_alias=True))

            yield "data:" + event.model_dump_json(
                exclude_none=True, by_alias=True
            ) + "\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


def convert_to_base_messages(messages: list) -> list[BaseMessage]:
    """
    将API请求中的消息转换为LangChain BaseMessage格式
    
    Args:
        messages: API请求中的消息列表
        
    Returns:
        BaseMessage格式的消息列表
    """
    base_messages = []
    
    for msg in messages:
        if msg.role == "user":
            base_messages.append(HumanMessage(content=msg.content))
        elif msg.role == "assistant":
            base_messages.append(AIMessage(content=msg.content))
        elif msg.role == "system":
            base_messages.append(SystemMessage(content=msg.content))
    
    return base_messages


@router.post("/conversation/topic")
async def generate_conversation_topic(request: ConversationTopicRequest):
    logger.info(f"generate_conversation_topic request: {request.model_dump_json(exclude_none=True, by_alias=True)}")
    try:
        # 验证消息数量
        if len(request.messages) < 1:
            raise HTTPException(
                status_code=400, 
                detail="至少需要一条消息来生成标题"
            )
        
        # 转换消息格式
        base_messages = convert_to_base_messages(request.messages)
        
        # 调用标题生成agent
        full_response = ""
        async for chunk in conversation_topic(base_messages):
            full_response += chunk
        
        logger.info(f"Agent返回的原始响应: {full_response}")
        
        # 解析JSON响应
        try:
            # 尝试解析JSON格式的响应
            response_data = json.loads(full_response.strip())
            topic = response_data.get("topic", "新对话")
        except json.JSONDecodeError:
            # 如果不是JSON格式，尝试直接提取标题
            topic = full_response.strip()
            # 移除可能的引号和多余字符
            topic = topic.strip('"').strip("'").strip()
            if not topic or len(topic) > 50:
                topic = "新对话"
        
        logger.info(f"最终生成的标题: {topic}")
        
        return {"topic": topic}
        
    except HTTPException:
        # 重新抛出HTTP异常
        raise
    except Exception as e:
        logger.error(f"生成对话标题时发生错误: {str(e)}", exc_info=True)
        
        # 返回错误响应，但不抛出异常，让前端可以继续工作
        return {"topic": "新对话"}


@router.post("/explain")
async def explain(request: Request, message: ExplainMessage) -> StreamingResponse:
    # 调用explain agent生成解释并返回
    # text = f"explain the text based on context, <text>{message.text}</text>, <context>{message.context}</context>"
    text = f"explain the text based on the document, <text>{message.text}</text>"
    session_uuid = message.session_uuid
    session_service = DatabaseSessionService(db_url="sqlite:///./agent_session.db")
    user_uuid = request.state.current_user["user_uuid"]

    upload_uuids = message.upload_uuids
    # 根据upload_uuids，通过document表查询document_uuids
    document_uuids = await get_document_uuids_from_upload_uuids(upload_uuids)

    # await check_document_access(document_uuids)

    session = await get_or_create_session(
        session_service, request.state, document_uuids, session_uuid,
    )

    async def event_generator():
        runner = Runner(
            agent=explain_agent,
            app_name=APP_NAME,
            session_service=session_service,
        )
        
        events_async = runner.run_async(
            session_id=session.id,
            user_id=user_uuid,
            run_config=RunConfig(
                streaming_mode=StreamingMode.SSE,
                max_llm_calls=150,
            ),
            new_message=types.Content(role="user", parts=[types.Part(text=text)]),
        )

        async for event in events_async:
            if not event.partial:
                logger.info(event.model_dump_json(exclude_none=True, by_alias=True))

                yield "data:" + event.model_dump_json(
                    exclude_none=True, by_alias=True
                ) + "\n\n"
        
    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.post("/summary")
async def summary(request: Request, message: Message) -> StreamingResponse:
    logger.info(f"summary request: {message.model_dump_json(exclude_none=True, by_alias=True)}")
    # 调用summary agent生成摘要并返回
    text = message.text
    session_uuid = message.session_uuid
    session_service = DatabaseSessionService(db_url="sqlite:///./agent_session.db")
    user_uuid = request.state.current_user["user_uuid"]

    upload_uuids = message.upload_uuids
    # 根据upload_uuids，通过document表查询document_uuids
    document_uuids = await get_document_uuids_from_upload_uuids(upload_uuids)

    # await check_document_access(document_uuids)

    session = await get_or_create_session(
        session_service, request.state, document_uuids, session_uuid
    )

    async def event_generator():
        runner = Runner(
            agent=summary_agent,
            app_name=APP_NAME,
            session_service=session_service,
        )
        
        events_async = runner.run_async(
            session_id=session.id,
            user_id=user_uuid,
            run_config=RunConfig(
                streaming_mode=StreamingMode.SSE,
                max_llm_calls=150,
            ),
            new_message=types.Content(role="user", parts=[types.Part(text=text)]),
        )

        async for event in events_async:
            if not event.partial:
                logger.info(event.model_dump_json(exclude_none=True, by_alias=True))
                # 只返回最终的非部分结果
                yield "data:" + event.model_dump_json(
                    exclude_none=True, by_alias=True
                ) + "\n\n"
        
    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.post("/translate")
async def translate(request: Request, message: TranslateMessage) -> StreamingResponse:
    # 调用translate agent生成翻译并返回
    # text = f"translate the text based on context, <source_language>{message.source_language}</source_language>, <target_language>{message.target_language}</target_language>, <text>{message.text}</text>, <context>{message.context}</context>"
    text = f"translate the text, <source_language>{message.source_language}</source_language>, <target_language>{message.target_language}</target_language>, <text>{message.text}</text>"
    session_uuid = message.session_uuid
    session_service = DatabaseSessionService(db_url="sqlite:///./agent_session.db")
    user_uuid = request.state.current_user["user_uuid"]

    upload_uuids = message.upload_uuids
    # 根据upload_uuids，通过document表查询document_uuids
    document_uuids = await get_document_uuids_from_upload_uuids(upload_uuids)

    # await check_document_access(document_uuids)

    session = await get_or_create_session(
        session_service, request.state, document_uuids, session_uuid
    )

    async def event_generator():
        runner = Runner(
            agent=translate_agent,
            app_name=APP_NAME,
            session_service=session_service,
        )
        
        events_async = runner.run_async(
            session_id=session.id,
            user_id=user_uuid,
            run_config=RunConfig(
                streaming_mode=StreamingMode.SSE,
                max_llm_calls=150,
            ),
            new_message=types.Content(role="user", parts=[types.Part(text=text)]),
        )

        async for event in events_async:
            if not event.partial:
                logger.info(event.model_dump_json(exclude_none=True, by_alias=True))

                yield "data:" + event.model_dump_json(
                    exclude_none=True, by_alias=True
                ) + "\n\n"
        
    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.post("/card")
async def card(request: Request, message: Message) -> StreamingResponse:
    logger.info(f"card request: {message.model_dump_json(exclude_none=True, by_alias=True)}")
    # 调用anki agent生成知识卡片并返回
    text = f"generate anki cards of the full decument, your answer can only conatin the anki cards, Do not include other irrelevant information."
    session_uuid = message.session_uuid
    session_service = DatabaseSessionService(db_url="sqlite:///./agent_session.db")
    user_uuid = request.state.current_user["user_uuid"]

    upload_uuids = message.upload_uuids
    # 根据upload_uuids，通过document表查询document_uuids
    document_uuids = await get_document_uuids_from_upload_uuids(upload_uuids)

    await check_document_access(document_uuids)

    session = await get_or_create_session(
        session_service, request.state, document_uuids, session_uuid
    )

    async def event_generator():
        runner = Runner(
            agent=anki_agent,
            app_name=APP_NAME,
            session_service=session_service,
        )
        
        events_async = runner.run_async(
            session_id=session.id,
            user_id=user_uuid,
            run_config=RunConfig(
                streaming_mode=StreamingMode.SSE,
                max_llm_calls=150,
            ),
            new_message=types.Content(role="user", parts=[types.Part(text=text)]),
        )

        async for event in events_async:
            if not event.partial:
                logger.info(event.model_dump_json(exclude_none=True, by_alias=True))

            yield "data:" + event.model_dump_json(
                exclude_none=True, by_alias=True
            ) + "\n\n"
        
    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.post("/mindmap")
async def mindmap(request: Request, message: Message) -> StreamingResponse:
    logger.info(f"mindmap request: {message.model_dump_json(exclude_none=True, by_alias=True)}")
    # 调用mindmap agent生成思维导图并返回
    text = f"generate mindmap of the full decument, your answer can only conatin the mindmap, Do not include other irrelevant information."
    session_uuid = message.session_uuid
    session_service = DatabaseSessionService(db_url="sqlite:///./agent_session.db")
    user_uuid = request.state.current_user["user_uuid"]

    upload_uuids = message.upload_uuids
    # 根据upload_uuids，通过document表查询document_uuids
    document_uuids = await get_document_uuids_from_upload_uuids(upload_uuids)

    await check_document_access(document_uuids)

    session = await get_or_create_session(
        session_service, request.state, document_uuids, session_uuid
    )

    async def event_generator():
        runner = Runner(
            agent=mindmap_agent,
            app_name=APP_NAME,
            session_service=session_service,
        )
        
        events_async = runner.run_async(
            session_id=session.id,
            user_id=user_uuid,
            run_config=RunConfig(
                streaming_mode=StreamingMode.SSE,
                max_llm_calls=150,
            ),
            new_message=types.Content(role="user", parts=[types.Part(text=text)]),
        )

        async for event in events_async:
            if not event.partial:
                logger.info(event.model_dump_json(exclude_none=True, by_alias=True))

            yield "data:" + event.model_dump_json(
                exclude_none=True, by_alias=True
            ) + "\n\n"
        
    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.post("/overview")
async def overview(request: Request, message: Message) -> StreamingResponse:
    logger.info(f"overview request: {message.model_dump_json(exclude_none=True, by_alias=True)}")
    # 调用summary agent生成概要并返回
    text = f"generate summary of the full decument, your answer can only conatin the summary, Do not include other irrelevant information. Always response in Chinese."
    session_uuid = message.session_uuid
    session_service = DatabaseSessionService(db_url="sqlite:///./agent_session.db")
    user_uuid = request.state.current_user["user_uuid"]

    upload_uuids = message.upload_uuids
    # 根据upload_uuids，通过document表查询document_uuids
    document_uuids = await get_document_uuids_from_upload_uuids(upload_uuids)

    await check_document_access(document_uuids)

    session = await get_or_create_session(
        session_service, request.state, document_uuids, session_uuid
    )

    async def event_generator():
        runner = Runner(
            agent=summary_agent,
            app_name=APP_NAME,
            session_service=session_service,
        )
        
        events_async = runner.run_async(
            session_id=session.id,
            user_id=user_uuid,
            run_config=RunConfig(
                streaming_mode=StreamingMode.SSE,
                max_llm_calls=150,
            ),
            new_message=types.Content(role="user", parts=[types.Part(text=text)]),
        )

        async for event in events_async:
            if not event.partial:
                logger.info(event.model_dump_json(exclude_none=True, by_alias=True))
                # 只返回最终的非部分结果
                yield "data:" + event.model_dump_json(
                    exclude_none=True, by_alias=True
                ) + "\n\n"
        
    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.post("/question")
async def question(request: Request, message: Message) -> StreamingResponse:
    logger.info(f"question request: {message.model_dump_json(exclude_none=True, by_alias=True)}")
    # 调用question agent生成推荐问题列表并保存到数据库
    text = f"generate question list of the full decument, your answer can only conatin the question list, Do not include other irrelevant information. Always response in Chinese."
    session_uuid = message.session_uuid
    session_service = DatabaseSessionService(db_url="sqlite:///./agent_session.db")
    user_uuid = request.state.current_user["user_uuid"]

    upload_uuids = message.upload_uuids
    # 根据upload_uuids，通过document表查询document_uuids
    document_uuids = await get_document_uuids_from_upload_uuids(upload_uuids)

    await check_document_access(document_uuids)

    session = await get_or_create_session(
        session_service, request.state, document_uuids, session_uuid
    )

    async def event_generator():
        runner = Runner(
            agent=question_agent,
            app_name=APP_NAME,
            session_service=session_service,
        )
        
        events_async = runner.run_async(
            session_id=session.id,
            user_id=user_uuid,
            run_config=RunConfig(
                streaming_mode=StreamingMode.SSE,
                max_llm_calls=150,
            ),
            new_message=types.Content(role="user", parts=[types.Part(text=text)]),
        )

        async for event in events_async:
            if not event.partial:
                logger.info(event.model_dump_json(exclude_none=True, by_alias=True))

            yield "data:" + event.model_dump_json(
                exclude_none=True, by_alias=True
            ) + "\n\n"
        
    return StreamingResponse(event_generator(), media_type="text/event-stream")


# 获取当前页码block，若不存在则返回None
async def is_page_blocks_exist(document_uuid: str, page_number: int) -> bool:
    db = SessionLocal()
    try:
        # 根据page_number查询page
        page = db.query(Page).filter(
            Page.document_uuid == document_uuid,
            Page.page_number == page_number,
            Page.deleted_at.is_(None)
        ).first()
        
        if not page:
            return False

        return True
    except Exception as e:
        logger.error(f"检查页面blocks是否存在时发生错误: {str(e)}")
        return False
    finally:
        db.close()


async def get_page_blocks(document_uuid: str, page_number: int):
    """获取页面块"""
    try:
        db_gen = get_db()
        session = next(db_gen)

        # 根据page_number查询page
        page = session.query(Page).filter(
            Page.document_uuid == document_uuid,
            Page.page_number == page_number,
            Page.deleted_at.is_(None)
        ).first()
        
        if not page:
            logger.warning(f"页面不存在: document_uuid={document_uuid}, page_number={page_number}")
            return []
        
        # 根据page_uuid查询blocks
        blocks = session.query(Block).filter(
            Block.document_uuid == document_uuid,
            Block.page_uuid == page.uuid,
            Block.deleted_at.is_(None),
            Block.label.in_(TRANSLATION_LABELS)
        ).all()
        
        logger.info(f"获取页面 {page_number} 的{len(blocks)}个文本块")
        return blocks
        
    except Exception as e:
        logger.error(f"获取页面块时发生未知错误: {str(e)}")
        return None
    finally:
        if 'session' in locals():
            session.close()


async def create_document_record_async(user_uuid: str, upload_uuid: str) -> str:
    # 如果没有document记录，创建一个
    try:
        # 获取上传文件信息
        upload_info = get_upload_info(upload_uuid)
        logger.info(f"upload_info: {upload_info}")
        if not upload_info:
            raise HTTPException(
                status_code=404,
                detail="上传信息不存在"
            )
        
        # 下载文件到本地（用于获取PDF页数）
        temp_task_uuid = str(uuid.uuid4())
        file_path = download_file_from_minio(upload_info, temp_task_uuid)
        logger.info(f"file_path: {file_path}")
        
        # 创建document记录
        document_uuid = str(uuid.uuid4())
        document = create_document_record(
            uuid_str=document_uuid,
            user_uuid=user_uuid,
            upload_info=upload_info,
            file_path=file_path,
            task_uuid=temp_task_uuid
        )
        
        # 清理临时文件
        cleanup_temp_files(file_path)
        logger.info(f"成功创建document记录: {document_uuid}")

        return document_uuid
    except Exception as e:
        logger.error(f"创建document记录失败: {e}")
        raise


async def create_page_blocks(document_uuid: str, page_number: int):
    # 调用单页面OCR接口，生成blocks
    try:
        from app.service.processing_service import process_single_page_ocr
        if document_uuid:
            ocr_result = await process_single_page_ocr(document_uuid, page_number)
            logger.info(f"单页面OCR处理完成: {ocr_result.get('success', False)}")
        else:
            logger.error("无法获取document_uuid，跳过OCR处理")
    except Exception as e:
        logger.error(f"单页面OCR处理失败: {e}")
        # TODO: 处理OCR失败


async def create_translation_record(block_uuid: str, lang: str, content: str):
    db = SessionLocal()
    try:
        # 先检查是否已存在该记录，如果存在则更新，否则创建新记录
        existing_translation = db.query(Translation).filter(
            Translation.block_uuid == block_uuid,
            Translation.lang == lang,
            Translation.deleted_at.is_(None)
        ).first()
        
        if existing_translation:
            # 更新现有记录
            existing_translation.content = content
            existing_translation.updated_at = datetime.now()
        else:
            # 创建新记录
            translation = Translation(
                block_uuid=block_uuid,
                lang=lang,
                content=content
            )
            db.add(translation)
        
        db.commit()
    except Exception as e:
        logger.error(f"创建翻译记录失败: {e}")
        db.rollback()
    finally:
        db.close()


async def get_translation_content(block_uuid: str, lang: str):
    db = SessionLocal()
    try:
        translation = db.query(Translation).filter(
            Translation.block_uuid == block_uuid, 
            Translation.lang == lang,
            Translation.deleted_at.is_(None)  # 排除已删除的翻译记录
        ).first()
        return translation.content if translation else None
    except Exception as e:
        logger.error(f"获取翻译记录失败: {e}")
        return None
    finally:
        db.close()


async def calc_block_font_size(block_uuid: str, trans_content: str):
    db = SessionLocal()
    try:
        block = db.query(Block).filter(Block.uuid == block_uuid, Block.deleted_at.is_(None)).first()
        font_size_px = calculateFontSize(trans_content, block.bbox_width, block.bbox_height)
        block.font_size_px = font_size_px
        db.commit()
        return font_size_px
    except Exception as e:
        logger.error(f"更新block字体大小失败: {e}")
        db.rollback()
        return None
    finally:
        db.close()


async def page_translate_event_generator(document_uuid: str, blocks: list[Block], message: PageTranslateMessage, user_uuid: str, request_state):
    session_service = DatabaseSessionService(db_url="sqlite:///./agent_session.db")
    session = await get_or_create_session(session_service, request_state, [document_uuid], message.session_uuid)

    for block in blocks:
        new_font_size_px = None
        # 首先检查数据库中是否已有该block的翻译记录
        existing_translation = await get_translation_content(block.uuid, message.target_language)
        
        if existing_translation:
            # 如果有翻译记录，直接使用缓存的翻译内容
            logger.info(f"使用缓存的翻译内容: block_uuid={block.uuid}, lang={message.target_language}")
            full_translation = existing_translation
            new_font_size_px = block.font_size_px
        else:
            # 如果没有翻译记录，调用agent进行翻译
            logger.info(f"调用agent进行翻译: block_uuid={block.uuid}, lang={message.target_language}")
            text = f"**DO NOT USE ANY TOOLS**, just **DIRECTLY** translate the content I give you, <source_language>{message.source_language}</source_language>, <target_language>{message.target_language}</target_language>, <content>{block.content}</content>"
            
            runner = Runner(
                agent=translate_agent,
                app_name=APP_NAME,
                session_service=session_service,
            )
            
            events_async = runner.run_async(
                session_id=session.id,
                user_id=user_uuid,
                run_config=RunConfig(
                    streaming_mode=StreamingMode.SSE,
                    max_llm_calls=150,
                ),
                new_message=types.Content(role="user", parts=[types.Part(text=text)]),
            )

            full_translation = ""
            async for event in events_async:
                if hasattr(event, 'partial') and event.partial == False:
                    if hasattr(event.content, 'parts') and event.content.parts:
                        for part in event.content.parts:
                            if hasattr(part, 'text') and part.text:
                                full_translation = part.text
            
            # 翻译完成后，将结果保存到数据库
            if full_translation.strip():
                await create_translation_record(block.uuid, message.target_language, full_translation.strip())
                logger.info(f"翻译结果已保存到数据库: block_uuid={block.uuid}, lang={message.target_language}")
                origin_font_size_px = await calc_block_font_size(block.uuid, block.content)
                logger.info(f"原始字体大小: block_uuid={block.uuid}, font_size_px={origin_font_size_px}")
                trans_font_size_px = await calc_block_font_size(block.uuid, full_translation.strip())
                logger.info(f"翻译后字体大小: block_uuid={block.uuid}, font_size_px={trans_font_size_px}")
                new_font_size_px = min(origin_font_size_px, trans_font_size_px)
                logger.info(f"更新block字体大小: block_uuid={block.uuid}, font_size_px={new_font_size_px}")

        result = {
            "page_num": message.page_number,
            "trans_content": full_translation.strip() if full_translation else block.content,
            "label": block.label or "text",
            "font_size_px": float(new_font_size_px) if new_font_size_px is not None else None,
            "bbox_left_ratio": float(block.bbox_left_ratio) if block.bbox_left_ratio is not None else None,
            "bbox_top_ratio": float(block.bbox_top_ratio) if block.bbox_top_ratio is not None else None,
            "bbox_width": float(block.bbox_width) if block.bbox_width is not None else None,
            "bbox_height": float(block.bbox_height) if block.bbox_height is not None else None,
        }
        
        # 以SSE格式返回当前block的结果
        yield f"data: {json.dumps(result, ensure_ascii=False)}\n\n"


@router.post("/page/translate")
async def page_translate(request: Request, message: PageTranslateMessage) -> StreamingResponse:
    user_uuid = request.state.current_user["user_uuid"]
    upload_uuids = message.upload_uuids
    document_uuids = await get_document_uuids_from_upload_uuids(upload_uuids)
    document_uuid = document_uuids[0] if document_uuids else None

    if not document_uuid:
        logger.info(f"document_uuid不存在，开始创建document记录: user_uuid={user_uuid}, upload_uuids={upload_uuids}")
        document_uuid = await create_document_record_async(user_uuid, upload_uuids[0])

    if not await is_page_blocks_exist(document_uuid, message.page_number):
        logger.info(f"页面blocks不存在，开始创建页面blocks: document_uuid={document_uuid}, page_number={message.page_number}")
        await create_page_blocks(document_uuid, message.page_number)

    blocks = await get_page_blocks(document_uuid, message.page_number)
    if not blocks:
        # 如果没有找到blocks，返回空结果
        async def empty_generator():
            yield "data: {\"error\": \"No blocks found for this page\"}\n\n"
        return StreamingResponse(empty_generator(), media_type="text/event-stream")
        
    return StreamingResponse(page_translate_event_generator(document_uuid, blocks, message, user_uuid, request.state), media_type="text/event-stream")