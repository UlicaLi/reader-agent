from langchain_openai import ChatOpenAI
from langchain.prompts import PromptTemplate
from agent.sub_agents.conversation_topic_agent.config import CONVERSATION_TOPIC_MODEL_NAME, CONVERSATION_TOPIC_API_KEY, CONVERSATION_TOPIC_API_BASE
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage
import asyncio
from agent.sub_agents.conversation_topic_agent.prompt import CONVERSATION_TOPIC_INSTRUCTION

def format_messages_for_prompt(messages: list[BaseMessage]) -> str:
    """将BaseMessage列表格式化为文本"""
    formatted_lines = []
    
    for msg in messages:
        if isinstance(msg, HumanMessage):
            formatted_lines.append(f"用户: {msg.content}")
        elif isinstance(msg, AIMessage):
            formatted_lines.append(f"助手: {msg.content}")
    
    return "\n".join(formatted_lines)

async def conversation_topic(messages: list[BaseMessage]):
    llm = ChatOpenAI(
        temperature=0,
        model=CONVERSATION_TOPIC_MODEL_NAME,
        openai_api_base=CONVERSATION_TOPIC_API_BASE,
        openai_api_key=CONVERSATION_TOPIC_API_KEY,
        streaming=False
    )
    
    prompt_template = PromptTemplate(
        template=CONVERSATION_TOPIC_INSTRUCTION, 
        input_variables=["text"])

    # 将messages格式化为文本
    conversation_text = format_messages_for_prompt(messages)
    formatted_prompt = prompt_template.format(text=conversation_text)
    
    async for event in llm.astream(formatted_prompt):
        if event.content:
            yield event.content
