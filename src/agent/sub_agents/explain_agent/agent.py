from agent.sub_agents.explain_agent import config, prompt
from google.adk.agents import Agent
from google.adk.models.lite_llm import LiteLlm
from agent.tools import (
    seek_chunks,
    get_chunk_content,
    search_chunks,
    get_page_content,
    get_document_metadata,
    count_chunks,
)

llm = LiteLlm(model=config.EXPLAIN_MODEL_NAME, api_key=config.EXPLAIN_API_KEY)

explain_agent = Agent(
    name="explain_agent",
    description="explain_agent",
    model=llm,
    instruction=prompt.EXPLAIN_INSTRUCTION,
    tools=[
        seek_chunks,
        get_chunk_content,
        search_chunks,
        get_page_content,
        get_document_metadata,
        count_chunks,
    ],
)