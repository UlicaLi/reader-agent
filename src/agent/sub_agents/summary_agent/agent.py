from agent.sub_agents.summary_agent import config, prompt
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

llm = LiteLlm(model=config.SUMMARY_MODEL_NAME, api_key=config.SUMMARY_API_KEY)

summary_agent = Agent(
    name="summary_agent",
    description="summary_agent",
    model=llm,
    instruction=prompt.SUMMARY_INSTRUCTION,
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
