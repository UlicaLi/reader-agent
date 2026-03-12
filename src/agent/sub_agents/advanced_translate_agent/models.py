from pydantic import BaseModel, Field

class TermEntry(BaseModel):
    name: str = Field(description="The name of the term")
    keywords: list[str] = Field(description="keywords that you would use in a search engine to get the proper context of the term")

class TermsResult(BaseModel):
    reasoning: str = Field(description="The reasoning of the term")
    items: list[TermEntry] = Field(description="The terms of the text")

class GlossaryEntry(BaseModel):
    term: str = Field(description="The term being defined")
    definition: str = Field(description="Clear and accurate definition of the term")
    context: str = Field(description="Explanation of how the term is used in the specific context")
    synonyms: list[str] = Field(default=[], description="Related terms or synonyms")
    domain: str = Field(description="The field or domain this term belongs to")

class GlossaryResult(BaseModel):
    reasoning: str = Field(description="The reasoning behind the glossary compilation")
    entries: list[GlossaryEntry] = Field(description="List of glossary entries for the terms")
