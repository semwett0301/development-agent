from typing import Literal, Optional

from pydantic import BaseModel


class CodingEvent(BaseModel):
    type: Literal["START", "REDO"]
    repository: str
    issue_number: int
    pull_request_number: Optional[int] = None


class ReviewEvent(BaseModel):
    repository: str
    pull_request_number: int
