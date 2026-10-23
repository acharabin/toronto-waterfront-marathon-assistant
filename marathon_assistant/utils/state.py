"""State models used by the agent and its tools."""

from enum import Enum
from pydantic import BaseModel

class RunnerIDType(str, Enum):
    place = "place"
    bib_number = "bib_number"

class SearchQueryVariants(BaseModel):
    queries: list[str]

class AgentContext(BaseModel):
    user_name: str = "123"
