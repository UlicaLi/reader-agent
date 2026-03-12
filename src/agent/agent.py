import arrow
import jinja2
from agent import prompt
from google.adk.agents import Agent
from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.models.lite_llm import LiteLlm
from agent.config import ROOT_API_KEY, ROOT_MODEL_NAME
from agent.sub_agents.summary_agent.agent import summary_agent
from agent.sub_agents.translate_agent.agent import translate_agent
from agent.sub_agents.question_agent.agent import question_agent
from agent.sub_agents.mindmap_agent.agent import mindmap_agent
from agent.sub_agents.anki_agent.agent import anki_agent
from agent.sub_agents.explain_agent.agent import explain_agent
from agent.tools import (
    seek_chunks,
    get_chunk_content,
    search_chunks,
    get_page_content,
    get_document_metadata,
    count_chunks,
    get_document_summary,
)

llm = LiteLlm(model=ROOT_MODEL_NAME, api_key=ROOT_API_KEY)


ROOT_INSTRUCTION_TEMPLATE = jinja2.Template(prompt.ROOT_INSTRUCTION)
GLOBAL_INSTRUCTION_TEMPLATE = jinja2.Template(prompt.GLOBAL_INSTRUCTION)


def global_instruction(context: ReadonlyContext) -> str:
    client_time_now = context.state.get(
        "client_time_now", arrow.now().format("YYYY-MM-DD HH:mm:ss")
    )
    return GLOBAL_INSTRUCTION_TEMPLATE.render(client_time_now=client_time_now)


def root_instruction(context: ReadonlyContext) -> str:
    print("root_instruction", context.state)
    return ROOT_INSTRUCTION_TEMPLATE.render()


root_agent = Agent(
    name="root_agent",
    description="root_agent",
    model=llm,
    global_instruction=global_instruction,
    instruction=root_instruction,
    tools=[
        seek_chunks,
        get_chunk_content,
        search_chunks,
        get_page_content,
        get_document_metadata,
        count_chunks,
        get_document_summary,
    ],
    sub_agents=[summary_agent, translate_agent, question_agent, mindmap_agent, anki_agent, explain_agent],
)
