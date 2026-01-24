from pydantic import BaseModel
from typing import Any

class ContentSchema(BaseModel):
    key: str
    value: Any

    class Config:
        orm_mode = True
