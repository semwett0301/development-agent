from pydantic import BaseModel


class CodingEvent(BaseModel):
    body: str | None = None
