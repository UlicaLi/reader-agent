from agent.sub_agents.mindmap_agent import config, prompt
from google.adk.agents import Agent
from google.adk.models.lite_llm import LiteLlm
from agent.tools import (
    seek_chunks,
    get_chunk_content,
    search_chunks,
    get_page_content,
    get_document_metadata,
    count_chunks,
    get_document_summary,
)

llm = LiteLlm(model=config.MINDMAP_MODEL_NAME, api_key=config.MINDMAP_API_KEY)

mindmap_agent = Agent(
    name="mindmap_agent",
    description="mindmap_agent",
    model=llm,
    instruction=prompt.MINDMAP_INSTRUCTION,
    tools=[
        seek_chunks,
        get_chunk_content,
        search_chunks,
        get_page_content,
        get_document_metadata,
        count_chunks,
        get_document_summary,
    ],
)