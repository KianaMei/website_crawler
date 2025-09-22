from typing import Optional, List
from pydantic import BaseModel, Field

from .news import News

class NewsResponse(BaseModel):
    news_list: Optional[List[News]] = Field(default=None, description="The list of news")
    status: str = Field(default="OK", description="Response status flag")
    err_code: Optional[str] = Field(default=None, description="Error code")
    err_info: Optional[str] = Field(default=None, description="Error info")

