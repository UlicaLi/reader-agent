from agent.sub_agents.question_agent import config, prompt
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

llm = LiteLlm(model=config.QUESTION_MODEL_NAME, api_key=config.QUESTION_API_KEY)

question_agent = Agent(
    name="question_agent",
    description="question_agent",
    model=llm,
    instruction=prompt.QUESTION_INSTRUCTION,
    tools=[
        seek_chunks,
        get_chunk_content,
        search_chunks,
        get_page_content,
        get_document_metadata,
        count_chunks,
    ],
)