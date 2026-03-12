from agent.sub_agents.anki_agent import config, prompt
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

llm = LiteLlm(model=config.ANKI_MODEL_NAME, api_key=config.ANKI_API_KEY)

anki_agent = Agent(
    name="anki_agent",
    description="anki_agent",
    model=llm,
    instruction=prompt.ANKI_INSTRUCTION,
    tools=[
        seek_chunks,
        get_chunk_content,
        search_chunks,
        get_page_content,
        get_document_metadata,
        count_chunks,
    ],
)