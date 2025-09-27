"""
经济参考报独立插件

每个插件文件都需要导出名为 `handler` 的函数，作为工具入口。
"""

from runtime import Args
from typing import List, Tuple
import re
from urllib.parse import urljoin
from bs4 import BeautifulSoup

# 独立模块，包含所有必要的依赖
from pydantic import BaseModel, Field
from typing import Optional, List, Tuple
import logging
import re
import datetime
import requests
import time
import random


class News(BaseModel):
    title: str
    url: str
    origin: str
    summary: str
    publish_date: str


class PaperInput(BaseModel):
    max_items: Optional[int] = Field(default=None, description="最大抓取条数，None 表示不限制")
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
                raw_max = inp_obj.get("max_items")
                date_str = inp_obj.get("date")
            else:
                raw_max = getattr(inp_obj, "max_items", None)
                date_str = getattr(inp_obj, "date", None)

            def _to_max(m):
                try:
                    if m is None:
                        return None
                    ms = str(m).strip().lower()
                    if ms in ("", "none", "null"):
                        return None
                    v = int(m)
                    return v if v > 0 else None
                except Exception:
                    return None

            max_items = _to_max(raw_max)
            
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


Metadata = {
    "name": "get_jjckb_news",
    "description": "获取经济参考报新闻",
    "input": PaperInput.model_json_schema(),
    "output": PaperOutput.model_json_schema(),
}


def pick_first_node(root: str) -> Tuple[str, str]:
    """选择第一个可用的版面节点"""
    for name in ['node_2.htm', 'node_1.htm', 'node_3.htm']:
        url = urljoin(root, name)
        try:
            html = fetch_url(url)
            if 'pageLink' in html or 'ul02_l' in html or 'MAP NAME="pagepicmap"' in html:
                return url, html
        except Exception:
            continue
    
    for i in range(1, 12):
        url = urljoin(root, f'node_{i}.htm')
        try:
            html = fetch_url(url)
            if 'pageLink' in html or 'ul02_l' in html:
                return url, html
        except Exception:
            pass
    return '', ''


def get_page_list(year: str, month: str, day: str):
    """获取经济参考报指定日期的版面列表"""
    root = f"{'http://dz.jjckb.cn/www/pages/webpage2009/html'.rstrip('/')}/{year}-{month}/{day}/"
    start_url, html = pick_first_node(root)
    if not html:
        return []
    
    soup = BeautifulSoup(html, 'html5lib')
    items = []
    
    for a in soup.find_all('a', id='pageLink', href=True):
        href = a['href'].strip()
        name = a.get_text(strip=True) or href
        absu = urljoin(start_url, href)
        valid_name = ''.join(ch for ch in name if ch not in r'\/:*?"<>|')
        items.append((absu, valid_name))
    
    if not items:
        seen = set()
        for a in soup.find_all('a', href=True):
            href = a['href'].strip()
            if not re.search(r'node_\d+\.htm$', href):
                continue
            absu = urljoin(start_url, href)
            if absu in seen:
                continue
            seen.add(absu)
            name = a.get_text(strip=True) or href
            valid_name = ''.join(ch for ch in name if ch not in r'\/:*?"<>|')
            items.append((absu, valid_name))
    
    if start_url and not any(u == start_url for u, _ in items):
        items.insert(0, (start_url, 'A01'))
    return items


def get_title_list(year: str, month: str, day: str, page_url: str):
    """获取指定版面的文章链接列表"""
    html = fetch_url(page_url)
    soup = BeautifulSoup(html, 'html.parser')
    links = []
    seen = set()
    
    for li in soup.select('ul.ul02_l li'):
        a = li.find('a', href=True)
        if not a:
            continue
        href = a['href'].strip()
        if not href or not href.endswith('.htm'):
            continue
        absu = urljoin(page_url, href)
        if absu in seen:
            continue
        seen.add(absu)
        links.append(absu)
    
    if not links:
        for area in soup.find_all('area', href=True):
            href = area['href'].strip()
            if not href or not href.endswith('.htm'):
                continue
            absu = urljoin(page_url, href)
            if absu in seen:
                continue
            seen.add(absu)
            links.append(absu)
    
    if not links:
        for a in soup.find_all('a', href=True):
            href = a['href'].strip()
            if not re.search(r'content_\d+\.htm$', href):
                continue
            absu = urljoin(page_url, href)
            if absu in seen:
                continue
            seen.add(absu)
            links.append(absu)
    return links


def is_advertisement(title: str, body: str) -> bool:
    """检测是否为广告内容 - 增强版广告过滤器"""
    if not title or not body:
        return True
    
    title_clean = title.strip()
    body_clean = body.strip()
    
    # 1. 空内容或极短内容
    if len(title_clean) <= 3 or len(body_clean) <= 20:
        return True
    
    # 2. 典型广告标题模式（更精确的正则）
    ad_title_patterns = [
        r'^[\w\s]*(?:科技|电子|网络|软件|信息|数码)(?:有限公司|股份有限公司|集团|企业|公司)[\w\s]*$',
        r'^[\w\s]*(?:招聘|诚聘|招募|求职|面试)[\w\s]*$', 
        r'^[\w\s]*(?:转让|出售|求购|代理|加盟|合作|代办)[\w\s]*$',
        r'^[\w\s]*(?:声明|启事|通告|公告|公示|通知)[\w\s]*$',
        r'^[\w\s]*(?:广告|宣传|推广|促销|优惠)[\w\s]*$',
        r'^[\w\s]*(?:电话|手机|联系方式|微信|QQ)[:：]?\s*\d+[\w\s]*$',  # 包含联系方式
        r'^[\w\s]*(?:价格|报价|优惠|折扣|特价)[\w\s]*$',
    ]
    
    for pattern in ad_title_patterns:
        if re.match(pattern, title_clean, re.IGNORECASE):
            return True
    
    # 3. 正文广告内容检测
    ad_body_patterns = [
        r'(?:联系电话|咨询电话|热线电话)[:：]?\s*\d{3,4}[-\s]?\d{7,8}',
        r'(?:手机|电话|微信|QQ)[:：]?\s*\d{11}',
        r'(?:网址|官网|网站)[:：]?\s*(?:www\.|http)',
        r'(?:价格|报价|售价)[:：]?\s*\d+(?:元|万|千)',
        r'(?:优惠|折扣|特价|促销|活动)(?:价格?|中|进行|开始)',
        r'(?:欢迎|竭诚为|真诚为|服务|咨询).*(?:客户|用户|朋友)',
        r'(?:质量保证|信誉第一|诚信经营|专业服务)',
    ]
    
    ad_content_count = 0
    for pattern in ad_body_patterns:
        if re.search(pattern, body_clean, re.IGNORECASE):
            ad_content_count += 1
            if ad_content_count >= 2:  # 多个广告特征
                return True
    
    # 4. 内容质量检测（更严格）
    chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', body_clean))
    total_chars = len(body_clean)
    
    # 中文字符比例太低
    if total_chars > 0 and chinese_chars / total_chars < 0.6:
        return True
    
    # 中文字符绝对数量太少
    if chinese_chars < 30:
        return True
    
    # 5. 新闻内容特征检测（扩展关键词）
    news_keywords = [
        '报道', '记者', '消息', '新闻', '据悉', '了解到', '获悉', '采访', '调查',
        '表示', '认为', '指出', '强调', '透露', '介绍', '解释', '分析', '预测',
        '政府', '部门', '机构', '企业', '市场', '经济', '发展', '政策', '改革',
        '会议', '论坛', '发布会', '研讨会', '座谈会', '调研', '视察', '检查',
        '数据', '统计', '调查', '研究', '报告', '白皮书', '方案', '规划',
        '年', '月', '日', '今年', '去年', '明年', '近期', '目前', '未来'
    ]
    
    news_keyword_count = sum(1 for keyword in news_keywords if keyword in body_clean)

    # 4.1 高质量内容兜底：正文较长、中文比例高且包含足够新闻关键词时，不判为广告
    chinese_ratio = (chinese_chars / total_chars) if total_chars > 0 else 0
    if len(body_clean) >= 300 and chinese_ratio >= 0.75 and news_keyword_count >= 3:
        return False
    
    # 如果新闻关键词太少且内容较短，可能是广告
    if news_keyword_count < 2 and len(body_clean) <= 200:
        return True
    
    # 6. 重复内容检测（典型广告模式）
    lines = body_clean.split('\n')
    if len(lines) > 1:
        line_lengths = [len(line.strip()) for line in lines if line.strip()]
        if line_lengths:
            # 放宽行长差异规则，仅针对很短的文本触发
            max_len, min_len = max(line_lengths), min(line_lengths)
            if (
                len(body_clean) <= 200 and
                max_len > 0 and
                (min_len / max_len) < 0.15 and
                len(line_lengths) <= 3
            ):
                return True
    
    # 7. 内容重复度检测
    words = re.findall(r'[\u4e00-\u9fff]+', body_clean)
    if len(words) > 5:
        unique_words = set(words)
        repetition_ratio = 1 - (len(unique_words) / len(words))
        # 提高重复率阈值并只在较短内容时触发，避免误杀新闻
        if len(body_clean) <= 600 and repetition_ratio > 0.85:
            return True
    
    return False


def parse_article(html: str):
    """解析经济参考报文章内容"""
    soup = BeautifulSoup(html, 'html.parser')
    raw = soup.decode()
    m = re.search(r'<founder-title>(.*?)</founder-title>', raw, flags=re.I | re.S)
    title = ''
    if m:
        title = BeautifulSoup(m.group(1), 'html.parser').get_text(strip=True)
    
    if not title:
        for tag in ['h1', 'h2', 'h3', 'title']:
            t = soup.find(tag)
            if t and t.get_text(strip=True):
                title = t.get_text(strip=True)
                break
    title_valid = ''.join(ch for ch in title if ch not in r'\/:*?"<>|')
    
    body = ''
    fcontent = soup.find('founder-content')
    if fcontent:
        ps = [p.get_text(strip=True) for p in fcontent.find_all('p') if p.get_text(strip=True)]
        if not ps:
            txt = fcontent.get_text("\n", strip=True)
            body = '\n'.join([line for line in txt.split('\n') if line.strip()])
        else:
            body = '\n'.join(ps)
    
    if not body:
        selectors_primary = [
            '#content', '#ozoom', 'div.content', 'div.article', 'td.black14', '#mdf', '#detail'
        ]
        selectors_extra = [
            '#contentText', '#contenttext', '#ContentBody', '#Zoom', '#zoom',
            '#text', 'div#text', '#content_main', '#article', '#Article',
            '#articleContent', '#article-content', 'div.article-content',
            '.TRS_Editor', 'section.article', 'article.article', 'div#newsContent',
            'div#Cnt-Main-Article-QQ', '#artibody', '#Content', '.contentText'
        ]
        for sel in selectors_primary + selectors_extra:
            el = soup.select_one(sel)
            if not el:
                continue
            ps = [p.get_text(strip=True) for p in el.find_all('p') if p.get_text(strip=True)]
            if ps:
                body = '\n'.join(ps)
                break
            # 段落为空时，直接取容器文本
            txt = el.get_text("\n", strip=True)
            txt_lines = [line for line in (txt or '').split('\n') if line.strip()]
            if txt_lines and len(''.join(txt_lines)) >= 60:
                body = '\n'.join(txt_lines)
                break
    
    if not body:
        # 兜底：在候选容器中选择中文文本最长的块
        candidates = []
        for tag_name in ['article', 'section', 'main', 'div', 'td']:
            for node in soup.find_all(tag_name):
                # 跳过明显的导航/脚注区域
                id_cls = ' '.join(filter(None, [node.get('id', ''), ' '.join(node.get('class', []))]))
                if re.search(r'(footer|header|nav|menu|breadcrumb|comment|copyright|share)', id_cls, re.I):
                    continue
                text = node.get_text('\n', strip=True)
                if not text:
                    continue
                # 统计中文字符数量及比例
                chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
                total_chars = len(text)
                if total_chars == 0:
                    continue
                chinese_ratio = chinese_chars / total_chars
                if chinese_chars >= 100 and chinese_ratio >= 0.5:
                    candidates.append((chinese_chars, text))
        if candidates:
            candidates.sort(key=lambda x: x[0], reverse=True)
            body = candidates[0][1]
        else:
            # 最后兜底：整页文本中提取中文行
            page_text = soup.get_text('\n', strip=True)
            lines = [ln.strip() for ln in (page_text or '').split('\n')]
            chinese_lines = [ln for ln in lines if len(re.findall(r'[\u4e00-\u9fff]', ln)) >= max(5, int(len(ln) * 0.4))]
            if chinese_lines:
                body = '\n'.join(chinese_lines)
    
    content_full = (title + '\n' + body) if title else body
    # 输出完整正文作为 summary（不做截断）
    summary = body
    return content_full, title_valid, title, body, summary


def analyze_content_debug(title: str, body: str) -> dict:
    """调试用：分析内容特征"""
    chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', body))
    total_chars = len(body)
    news_keywords = [
        '报道', '记者', '消息', '新闻', '据悉', '了解到', '获悉', '采访', '调查',
        '表示', '认为', '指出', '强调', '透露', '介绍', '解释', '分析', '预测',
        '政府', '部门', '机构', '企业', '市场', '经济', '发展', '政策', '改革'
    ]
    news_keyword_count = sum(1 for keyword in news_keywords if keyword in body)
    
    return {
        'title_len': len(title),
        'body_len': len(body),
        'chinese_chars': chinese_chars,
        'chinese_ratio': chinese_chars / total_chars if total_chars > 0 else 0,
        'news_keywords': news_keyword_count
    }


@safe_handler("经济参考报")
def handler(args: Args[PaperInput], max_items: Optional[int], date_str: str, origin_name: str, logger) -> PaperOutput:
    """经济参考报新闻抓取处理函数 - 增强广告过滤版"""
    y, m, d = find_available_date(get_page_list, date_str)
    news_list: List[News] = []
    ad_count = 0
    total_count = 0
    
    target_str = "不限" if max_items is None else str(max_items)
    logger.info(f"开始抓取 {origin_name} {y}-{m}-{d} 的新闻，目标数量: {target_str}")
    
    for page_url, page_name in get_page_list(y, m, d):
        if max_items is not None and len(news_list) >= max_items:
            break
        logger.info(f"处理版面: {page_name} - {page_url}")
        
        for url in get_title_list(y, m, d, page_url):
            if max_items is not None and len(news_list) >= max_items:
                break
            
            total_count += 1
            try:
                html = fetch_url(url)
                _, _, title, body, summary = parse_article(html)
                
                # 内容分析（调试用）
                content_info = analyze_content_debug(title or '', body or '')
                
                # 广告过滤检查
                if is_advertisement(title or '', body or ''):
                    ad_count += 1
                    logger.info(f"[广告过滤] {title[:30]}... | "
                              f"标题长度:{content_info['title_len']}, "
                              f"正文长度:{content_info['body_len']}, "
                              f"中文比例:{content_info['chinese_ratio']:.2f}, "
                              f"新闻关键词:{content_info['news_keywords']}")
                    continue
                
                # 只保留有效内容
                if title and body and len(title.strip()) > 3 and len(body.strip()) > 30:
                    news_list.append(News(
                        title=title.strip(), 
                        url=url, 
                        origin=origin_name, 
                        summary=summary or body or '', 
                        publish_date=f"{y}-{m}-{d}"
                    ))
                    logger.info(f"[有效新闻] {title[:40]}... | "
                              f"正文长度:{content_info['body_len']}, "
                              f"新闻关键词:{content_info['news_keywords']}")
                else:
                    ad_count += 1
                    logger.info(f"[内容过短] {title or '无标题'}... | "
                              f"标题长度:{len(title or '')}, 正文长度:{len(body or '')}")
                    
            except Exception as e:
                logger.warning(f"解析文章失败 {url}: {e}")
                continue
    
    logger.info(f"抓取完成: 总文章数:{total_count}, 有效新闻:{len(news_list)}, 过滤广告:{ad_count}")
    
    status = 'OK' if news_list else 'EMPTY'
    return PaperOutput(
        news_list=news_list or None, 
        status=status, 
        err_code=None if news_list else 'NO_VALID_CONTENT', 
        err_info=None if news_list else f'从{total_count}篇文章中过滤了{ad_count}条广告，无有效新闻内容'
    )