from typing import Literal

from pydantic import BaseModel


class CodingEvent(BaseModel):
    type: Literal["START", "REDO"]
    repository: str
    issue_number: int
