from agent.sub_agents.translate_agent import config, prompt
from google.adk.agents import Agent
from google.adk.models.lite_llm import LiteLlm
from agent.tools import (
    seek_chunks,
    get_chunk_content,
    search_chunks,
    get_page_content,
    get_document_metadata,
)

llm = LiteLlm(model=config.TRANSLATE_MODEL_NAME, api_key=config.TRANSLATE_API_KEY)

translate_agent = Agent(
    name="translate_agent",
    description="translate_agent",
    model=llm,
    instruction=prompt.TRANSLATE_INSTRUCTION,
    tools=[
        seek_chunks,
        get_chunk_content,
        search_chunks,
        get_page_content,
        get_document_metadata,
    ],
)