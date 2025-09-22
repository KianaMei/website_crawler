from datetime import datetime
from pydantic import BaseModel


class News(BaseModel):
    title: str
    url: str
    origin: str
    summary: str
    publish_date: str

