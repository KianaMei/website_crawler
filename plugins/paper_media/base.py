"""
纸媒插件公共基础模块
提供所有纸媒插件共用的基础类、工具函数等
"""

from typing import TypeVar, Generic

# 模拟 runtime.Args 类型
T = TypeVar('T')

class Args(Generic[T]):
    """模拟 Args 类"""
    def __init__(self, input_data=None, logger=None):
        self.input = input_data
        self.logger = logger
from pydantic import BaseModel, Field
from typing import Optional, List, Tuple
import logging
import re
import datetime
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup
import time
import random


class News(BaseModel):
    title: str
    url: str
    origin: str
    summary: str
    publish_date: str


class PaperInput(BaseModel):
    max_items: int = Field(default=10, ge=1, le=50, description="最多抓取条数")
    since_days: int = Field(default=3, ge=1, le=365, description="近 N 天窗口")
    date: Optional[str] = Field(default=None, description="指定日期（YYYY-MM-DD）")


class PaperOutput(BaseModel):
    news_list: Optional[List[News]] = Field(default=None, description="新闻列表")
    status: str = Field(default="OK", description="响应状态标记")
    err_code: Optional[str] = Field(default=None, description="错误码（可选）")
    err_info: Optional[str] = Field(default=None, description="错误信息（可选）")


def fetch_url(url: str) -> str:
    """统一的URL抓取函数，支持智能编码检测和重试机制"""
    DEFAULT_HEADERS = {
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36',
        'Accept-Language': 'zh-CN,zh;q=0.8,en-US;q=0.5,en;q=0.3',
        'Accept-Encoding': 'gzip, deflate',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
    }
    retries = 3
    delay = 1.0
    sess = requests.Session()
    sess.headers.update(DEFAULT_HEADERS)
    sess.trust_env = False
    
    for attempt in range(retries):
        try:
            resp = sess.get(url, timeout=20, verify=False, proxies={'http': None, 'https': None})
            resp.raise_for_status()
            ct = resp.headers.get('content-type', '') or ''
            data = resp.content

            def _norm(cs: str) -> str:
                cs = (cs or '').strip().strip('"\'').lower()
                return 'gb18030' if cs in ('gb2312','gb-2312','gbk') else ('utf-8' if cs in ('utf8','utf-8') else (cs or 'utf-8'))

            def _enc_from_meta(b: bytes) -> Optional[str]:
                m = re.search(br'charset\s*=\s*["\']?([a-zA-Z0-9_\-]+)', b[:4096], re.IGNORECASE)
                if m:
                    try:
                        return _norm(m.group(1).decode('ascii', errors='ignore'))
                    except Exception:
                        return None
                return None

            def _enc_from_header() -> Optional[str]:
                m = re.search(r'charset=([^;\s]+)', ct, re.IGNORECASE)
                if m:
                    return _norm(m.group(1))
                return _norm(resp.encoding) if resp.encoding else None

            cands: List[str] = []
            for c in (_enc_from_meta(data), resp.apparent_encoding and _norm(resp.apparent_encoding), _enc_from_header(), 'utf-8','gb18030'):
                if c and c not in cands:
                    cands.append(c)  # type: ignore[arg-type]

            best_txt = None
            best_bad = 10**9
            for ec in cands:
                try:
                    txt = data.decode(ec, errors='replace')
                    bad = txt.count('\ufffd')
                    if bad < best_bad:
                        best_txt = txt
                        best_bad = bad
                        if bad == 0:
                            break
                except Exception:
                    continue
            return best_txt or data.decode('utf-8', errors='ignore')
        except requests.RequestException:
            if attempt < retries - 1:
                time.sleep(delay * (1 + random.random() * 0.5))
                continue
            raise


def today_parts():
    """获取今天的年月日"""
    today = datetime.date.today()
    return f"{today.year}", f"{today.month:02d}", f"{today.day:02d}"


def find_available_date(get_pages_func, date: Optional[str], max_back_days: int = 7) -> Tuple[str, str, str]:
    """智能查找可用日期"""
    # 如果用户指定了日期，优先尝试
    if date:
        try:
            y, m, d = date.split('-')
            if get_pages_func(y, m, d):
                return y, m, d
        except Exception:
            pass
    
    # 从今天开始向前查找
    y0, m0, d0 = today_parts()
    base_date = datetime.date(int(y0), int(m0), int(d0))
    for i in range(max_back_days + 1):
        day = base_date - datetime.timedelta(days=i)
        y, m, d = f"{day.year}", f"{day.month:02d}", f"{day.day:02d}"
        try:
            if get_pages_func(y, m, d):
                return y, m, d
        except Exception:
            continue
    return y0, m0, d0


def safe_handler(origin_name: str):
    """装饰器：为纸媒处理函数提供统一的错误处理"""
    def decorator(handler_func):
        def wrapper(args: Args[PaperInput]) -> PaperOutput:
            logger = getattr(args, "logger", logging.getLogger(__name__))
            
            # 容忍缺失的 args.input 或字段
            inp_obj = getattr(args, "input", None)
            if isinstance(inp_obj, dict):
                max_items = int(inp_obj.get("max_items") or 10)
                date_str = inp_obj.get("date")
            else:
                max_items = int((getattr(inp_obj, "max_items", None) or 10))
                date_str = getattr(inp_obj, "date", None)
            
            try:
                return handler_func(args, max_items, date_str, origin_name, logger)
            except Exception as e:
                logger.exception(f"{origin_name} handler failed")
                return PaperOutput(
                    news_list=None, 
                    status="ERROR", 
                    err_code="PLUGIN_ERROR", 
                    err_info=str(e)
                )
        return wrapper
    return decorator