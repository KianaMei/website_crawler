from typing import Optional, List
from pydantic import BaseModel, Field

from .news import News

class NewsResponse(BaseModel):
    news_list: Optional[List[News]] = Field(default=None, description="新闻列表")
    status: str = Field(default="OK", description="响应状态标识")
    err_code: Optional[str] = Field(default=None, description="错误代码")
    err_info: Optional[str] = Field(default=None, description="错误信息")
