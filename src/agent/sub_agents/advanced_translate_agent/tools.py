from agent.sub_agents.advanced_translate_agent import config
from langchain_tavily import TavilySearch
from google.adk.tools.langchain_tool import LangchainTool
import os

os.environ["TAVILY_API_KEY"] = config.TAVILY_API_KEY
tavily_langchain_tool = TavilySearch(
    max_results=1,
    search_depth="advanced",
    include_answer=True,
    include_raw_content=True,
)

tavily_search = LangchainTool(tool=tavily_langchain_tool)
