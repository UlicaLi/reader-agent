from agent.sub_agents.advanced_translate_agent import config
from google.adk.agents import SequentialAgent, ParallelAgent, LlmAgent
from google.adk.tools import google_search
from google.adk.models.lite_llm import LiteLlm
from agent.sub_agents.advanced_translate_agent import prompt
from agent.sub_agents.advanced_translate_agent.models import TermsResult, GlossaryResult
from agent.sub_agents.advanced_translate_agent.tools import tavily_search

term_llm = LiteLlm(model=config.TRANSLATE_MODEL_NAME, api_key=config.TRANSLATE_API_KEY)
translate_llm = LiteLlm(model=config.TRANSLATE_MODEL_NAME, api_key=config.TRANSLATE_API_KEY)
glossary_llm = LiteLlm(model=config.TRANSLATE_MODEL_NAME, api_key=config.TRANSLATE_API_KEY)
critique_llm = LiteLlm(model=config.TRANSLATE_MODEL_NAME, api_key=config.TRANSLATE_API_KEY)
refine_llm = LiteLlm(model=config.TRANSLATE_MODEL_NAME, api_key=config.TRANSLATE_API_KEY)

term_agent = LlmAgent(
    name="TermAgent",
    description="A agent that generates a term of the text",
    model=term_llm,
    instruction=prompt.TERM_INSTRUCTION,
    output_key="term",
    output_schema=TermsResult,
)

glossary_agent = LlmAgent(
    name="GlossaryAgent",
    description="A agent that generates a glossary of the text",
    model=glossary_llm,
    instruction=prompt.GLOSSARY_INSTRUCTION,
    output_key="glossary",
    # 使用了 tools 后，output_schema 会报错，所以注释掉
    # output_schema=GlossaryResult,
    tools=[
        tavily_search
    ]
)

basic_translate_agent = LlmAgent(
    name="BasicTranslateAgent",
    description="A agent that translates text from one language to another",
    model=translate_llm,
    instruction=prompt.BASIC_TRANSLATE_INSTRUCTION,
    output_key="basic_translate",
)

critique_agent = LlmAgent(
    name="CritiqueAgent",
    description="A agent that critiques the translation",
    model=critique_llm,
    instruction=prompt.CRITIQUE_INSTRUCTION,
    # output_key="critique",
)

refine_agent = LlmAgent(
    name="RefineAgent",
    description="A agent that refines the translation",
    model=refine_llm,
    instruction=prompt.REFINE_INSTRUCTION,
)

translate_agent = SequentialAgent(
    name="TranslateAndRefine",
    sub_agents=[
        ParallelAgent(
            name="BasicTranslateAndGlossary",
            sub_agents=[
                SequentialAgent(
                    name="TermAndGlossary",
                    sub_agents=[
                        term_agent,
                        glossary_agent
                    ],
                ),
                basic_translate_agent,
            ],
        ),
        critique_agent,
        refine_agent,
    ],
)

# translate_agent = basic_translate_agent
