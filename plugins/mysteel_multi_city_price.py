"""
每个插件文件都需要导出名为 `handler` 的函数，作为工具入口。

参数:
- args: 入口函数的参数对象
- args.input: 输入参数（例如 args.input.xxx）
- args.logger: 日志记录器，由运行时注入

提示: 请在 Metadata 中补充 input/output，有助于 LLM 正确识别并调用工具。

返回:
返回的数据必须与声明的输出参数结构一致。
"""

from runtime import Args
from pydantic import BaseModel, Field
from typing import Optional, List, Dict

import logging
import time
import random
import re
from datetime import datetime, timedelta, timezone

import requests


# Mysteel 多城市价格曲线（与现有插件风格保持一致：requests 同步 + Pydantic I/O）

DEFAULT_PAGE = "https://index.mysteel.com/price/getChartMultiCity_1_0.html"
API_URL = "https://index.mysteel.com/zs/newprice/getBaiduChartMultiCity.ms"
API_VERSION = "1.0.0"
APP_KEY = "47EE3F12CF0C443F8FD51EFDA73AC815"
APP_SEC = "3BA6477330684B19AA6AF4485497B5F2"


# 简易调试输出（直接打印到控制台；同时尽量写入运行时 logger）
DEBUG_MODE = True
_DBG_LOGGER = None  # 由 handler 在 debug=True 时注入


def _dbg(msg: str) -> None:
    if not DEBUG_MODE:
        return
    try:
        print(f"[mysteel] {msg}", flush=True)
        if _DBG_LOGGER is not None:
            try:
                _DBG_LOGGER.info(f"[mysteel] {msg}")
            except Exception:
                pass
    except Exception:
        pass


class PricePoint(BaseModel):
    date: str
    value: Optional[float] = None


class CitySeries(BaseModel):
    breed: str
    spec: str
    city: str
    city_code: Optional[str] = None
    unit: Optional[str] = None
    data: List[PricePoint]


class Input(BaseModel):
    url: Optional[str] = Field(default=DEFAULT_PAGE, description="页面参考地址（说明用途）")
    catalog: str = Field(default="螺纹钢", description="品类/大类（例如 螺纹钢、线材、热轧 等）")
    spec: str = Field(default="HRB400E_20MM", description="规格值（示例 HRB400E_20MM）")
    cities: List[str] = Field(
        default_factory=lambda: [
            "上海:15278",
            "北京:15472",
            "南京:15407",
            "天津:15480",
            "唐山:15605",
            "广州:15738",
        ],
        description="城市列表 name:code，例如 上海:15278；留空将回退为常用城市集",
    )
    days: int = Field(default=30, ge=1, le=365, description="近 N 天（若给出 start_date/end_date 则忽略 days）")
    start_date: Optional[str] = Field(default=None, description="起始日期 YYYY-MM-DD，可选")
    end_date: Optional[str] = Field(default=None, description="截止日期 YYYY-MM-DD，可选")
    debug: bool = Field(default=True, description="是否打印调试信息到终端（默认开启）")
    use_browser_fallback: bool = Field(default=True, description="直连失败时，使用 Playwright 回退抓取")
    browser_timeout_ms: int = Field(default=20000, ge=2000, le=60000, description="浏览器回退的超时时间（毫秒）")


class Output(BaseModel):
    series: Optional[List[CitySeries]] = Field(default=None, description="多城市价格序列")
    status: str = Field(default="OK", description="响应状态标记")
    err_code: Optional[str] = Field(default=None, description="错误码（可选）")
    err_info: Optional[str] = Field(default=None, description="错误信息（可选）")


Metadata = {
    "name": "get_mysteel_multi_city_price",
    "description": "抓取 Mysteel 多城市价格曲线数据（同步 requests，复用前端签名算法）",
    "input": Input.model_json_schema(),
    "output": Output.model_json_schema(),
}


def handler(args: Args[Input]) -> Output:
    """Mysteel 多城市价格（requests 同步）插件"""
    logger = getattr(args, "logger", logging.getLogger(__name__))
    # 启用/关闭调试（兼容 args.input 缺失或为 dict 的情况）
    global DEBUG_MODE, _DBG_LOGGER
    inp = getattr(args, "input", None)
    if isinstance(inp, dict):
        DEBUG_MODE = bool(inp.get("debug", True))
    else:
        DEBUG_MODE = bool(getattr(inp, "debug", True)) if inp is not None else True
    _DBG_LOGGER = logger if DEBUG_MODE else None

    try:
        # 统一读取输入并提供默认值（当缺失或为空时自动回退到默认）
        if isinstance(inp, dict):
            catalog = (inp.get('catalog') or '螺纹钢').strip()
            spec = (inp.get('spec') or 'HRB400E_20MM').strip()
            raw_cities = inp.get('cities')
        else:
            catalog = ((getattr(inp, 'catalog', None)) or '螺纹钢').strip()
            spec = ((getattr(inp, 'spec', None)) or 'HRB400E_20MM').strip()
            raw_cities = getattr(inp, 'cities', None)

        # 兼容 cities 传入字符串或列表；为空时使用默认两城
        if isinstance(raw_cities, str):
            cities = [x.strip() for x in raw_cities.split(',') if x.strip()]
        elif isinstance(raw_cities, list) and raw_cities:
            cities = [str(x).strip() for x in raw_cities if str(x).strip()]
        else:
            cities = [
                "上海:15278",
                "北京:15472",
                "南京:15407",
                "天津:15480",
                "唐山:15605",
                "广州:15738",
            ]

        # 规格容错：将空格替换为下划线，统一大小写格式
        spec = spec.replace(' ', '_').replace('\u3000', '_')
        if not catalog or not spec or not cities:
            return Output(series=None, status="ERROR", err_code="BAD_INPUT", err_info="catalog/spec/cities 不能为空")

        # 解析日期范围（容错缺省）
        if isinstance(inp, dict):
            sd = inp.get('start_date')
            ed = inp.get('end_date')
            days = inp.get('days', 30)
        else:
            sd = getattr(inp, 'start_date', None)
            ed = getattr(inp, 'end_date', None)
            days = getattr(inp, 'days', 30)
        # 是否显式给出起止日期（仅在显式时传给后端；否则让后端按默认范围返回）
        explicit_range = bool(sd and ed)
        start_date, end_date = _resolve_date_range(sd, ed, days)
        _dbg(f"fetch catalog={catalog} spec={spec} cities={len(cities)} range={start_date}..{end_date}")

        # 组装 city 字符串；页面端可选多城市，通常以逗号分隔 name:code
        city_param = ",".join(cities)

        # 调用后端接口（需要 header 签名，与页面 JS 一致）
        data = _fetch_chart_data(
            catalog=catalog,
            city=city_param,
            spec=spec,
            start=(start_date if explicit_range else None),
            end=(end_date if explicit_range else None),
        )

        # 如果合并多城市失败：尝试逐城拉取并合并结果
        if not data or not isinstance(data, dict) or not data.get('data'):
            merged: List[Dict] = []
            unit: Optional[str] = None
            for idx, c in enumerate(cities[:6]):  # 最多取前6个城市以控制体量
                _dbg(f"fallback single-city fetch: {c}")
                d1 = _fetch_chart_data(
                    catalog=catalog,
                    city=c,
                    spec=spec,
                    start=(start_date if explicit_range else None),
                    end=(end_date if explicit_range else None),
                ) or {}
                if d1.get('data'):
                    if unit is None:
                        unit = d1.get('unit') or None
                    # 将该城市系列加入集合
                    for it in (d1.get('data') or []):
                        merged.append(it)
            if merged:
                data = {'data': merged, 'unit': unit}
            else:
                # 浏览器回退：在页面上下文内计算签名与请求，绕过风控
                use_browser = (inp.get('use_browser_fallback', True) if isinstance(inp, dict) else getattr(inp, 'use_browser_fallback', True))
                timeout_ms = (inp.get('browser_timeout_ms', 20000) if isinstance(inp, dict) else getattr(inp, 'browser_timeout_ms', 20000))
                if use_browser:
                    _dbg("no data via requests, trying browser fallback (multi-city)")
                    try:
                        data = _fetch_chart_data_browser(
                            catalog=catalog,
                            city=city_param,
                            spec=spec,
                            start=(start_date if explicit_range else None),
                            end=(end_date if explicit_range else None),
                            timeout_ms=timeout_ms,
                        ) or {}
                    except Exception as _be:
                        _dbg(f"browser fallback multi failed: {_be}")
                        data = {}
                    # 若仍为空，逐城回退（浏览器）
                    if not data or not data.get('data'):
                        merged2: List[Dict] = []
                        unit2: Optional[str] = None
                        for c in cities[:6]:
                            _dbg(f"browser single-city fetch: {c}")
                            try:
                                d2 = _fetch_chart_data_browser(
                                    catalog=catalog,
                                    city=c,
                                    spec=spec,
                                    start=(start_date if explicit_range else None),
                                    end=(end_date if explicit_range else None),
                                    timeout_ms=timeout_ms,
                                ) or {}
                            except Exception as _be2:
                                _dbg(f"browser single failed {c}: {_be2}")
                                d2 = {}
                            if d2.get('data'):
                                if unit2 is None:
                                    unit2 = d2.get('unit') or None
                                for it in (d2.get('data') or []):
                                    merged2.append(it)
                        if merged2:
                            data = {'data': merged2, 'unit': unit2}
                        else:
                            return Output(series=None, status="EMPTY", err_code="NO_DATA", err_info="接口无返回或数据为空")
                else:
                    return Output(series=None, status="EMPTY", err_code="NO_DATA", err_info="接口无返回或数据为空")

        unit = data.get('unit') or None
        # data['data'] 为城市序列，对齐 dateValueMap
        series_out: List[CitySeries] = []
        try:
            items = data.get('data') or []
            for item in items:
                nm = item.get('name') or ''
                # name 形如 "上海" 或 "上海(螺纹钢 HRB400E_20MM)"，这里尽量只取城市名
                city_name = _extract_city_name(nm)
                points: List[PricePoint] = []
                for dv in (item.get('dateValueMap') or []):
                    d = dv.get('date') or ''
                    v = dv.get('value')
                    try:
                        fv = float(v) if v is not None and v != '' else None
                    except Exception:
                        fv = None
                    points.append(PricePoint(date=d, value=fv))
                city_code = _extract_city_code_from_list(cities, city_name)
                series_out.append(CitySeries(breed=catalog, spec=spec, city=city_name, city_code=city_code, unit=unit, data=points))
        except Exception:
            pass

        status = 'OK' if series_out else 'EMPTY'
        return Output(series=series_out or None, status=status, err_code=None if series_out else 'NO_DATA', err_info=None if series_out else 'No series parsed')
    except Exception as e:
        logger.exception("mysteel multi-city plugin failed")
        return Output(series=None, status="ERROR", err_code="PLUGIN_ERROR", err_info=str(e))


def _extract_city_name(name: str) -> str:
    if not name:
        return ''
    # 去除括号内附加信息
    m = re.match(r"^([^()]+)", name.strip())
    return (m.group(1) if m else name).strip()


def _extract_city_code_from_list(cities: List[str], city_name: str) -> Optional[str]:
    try:
        for it in cities:
            if ':' in it:
                nm, code = it.split(':', 1)
                if nm.strip() == city_name:
                    return code.strip()
    except Exception:
        return None
    return None


def _resolve_date_range(start: Optional[str], end: Optional[str], days: int | None) -> tuple[str, str]:
    # 目标：YYYY-MM-DD；若未给出则按北京时区近 N 天
    def _norm(s: Optional[str]) -> Optional[str]:
        if not s:
            return None
        ss = str(s).strip()
        m = re.search(r'(20\d{2})[\./\-/年](\d{1,2})[\./\-/月](\d{1,2})', ss)
        if m:
            y, mo, d = m.groups()
            return f"{y}-{int(mo):02d}-{int(d):02d}"
        m2 = re.fullmatch(r'(20\d{2}-\d{2}-\d{2})', ss)
        return m2.group(1) if m2 else None

    s = _norm(start)
    e = _norm(end)
    if s and e:
        return s, e
    # 默认按 UTC+8
    beijing = timezone(timedelta(hours=8))
    today = datetime.now(beijing).date()
    # days 可能为 None 或无法转为 int，统一容错
    try:
        di = int(days) if days is not None else 30
    except Exception:
        di = 30
    if di < 1:
        di = 1
    if di > 365:
        di = 365
    start_dt = today - timedelta(days=di)
    return start_dt.strftime('%Y-%m-%d'), today.strftime('%Y-%m-%d')


def _compute_sign(path: str) -> tuple[str, str]:
    # getSign: MD5( "path"+path+"timestamp"+ts+"version1.0.0"+APP_SEC ).upper()
    ts = str(int(time.time() * 1000))
    raw = f"path{path}timestamp{ts}version{API_VERSION}{APP_SEC}"
    import hashlib
    sign = hashlib.md5(raw.encode('utf-8')).hexdigest().upper()
    return sign, ts


def _fetch_chart_data(catalog: str, city: str, spec: str, start: Optional[str], end: Optional[str]) -> Dict:
    # 根据前端 JS：signPath 取自 href 中的 .com 之后路径 + '.ms'
    import json
    import urllib.parse as _url

    href = API_URL
    m = re.search(r"\.com(\S*)\.ms", href)
    if not m:
        raise RuntimeError("Bad API_URL format for sign path")
    sign_path = m.group(1) + '.ms'
    sign, ts = _compute_sign(sign_path)

    headers = {
        'version': API_VERSION,
        'appKey': APP_KEY,
        'timestamp': ts,
        'sign': sign,
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36',
        'Referer': DEFAULT_PAGE,
        'Accept': 'application/json, text/javascript, */*; q=0.01',
        'X-Requested-With': 'XMLHttpRequest',
        'Origin': 'https://index.mysteel.com',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.6',
    }

    params = {
        'catalog': catalog,
        'city': city,
        'spec': spec,
        'callback': 'json',
        'v': str(int(time.time() * 1000)),
    }
    if start and end:
        params['startTime'] = start
        params['endTime'] = end

    sess = requests.Session()
    sess.trust_env = False
    for attempt in range(3):
        try:
            resp = sess.get(href, params=params, headers=headers, timeout=20, verify=False, proxies={'http': None, 'https': None}, allow_redirects=True)
            resp.raise_for_status()
            # 服务器返回通常是字符串化 JSON，需要先解码后 JSON.parse
            txt = resp.text or ''
            # 前端 JSON.parse(data)，因此这里 data 可能是字符串化 JSON
            try:
                # 有时会是 JSONP 包裹：json( ... ) 或 callback(...)
                m_jsonp = re.match(r"\s*\w+\((.*)\)\s*;?\s*$", txt, re.DOTALL)
                if m_jsonp:
                    txt2 = m_jsonp.group(1)
                    return json.loads(txt2)
                return json.loads(txt)
            except json.JSONDecodeError:
                # 可能是 callback 包裹或 gbk 编码问题，这里再尝试一次 bytes->decode
                try:
                    content = resp.content
                    # 尝试按 utf-8/gb18030 解码再解析
                    for ec in ('utf-8', 'gb18030'):
                        try:
                            t2 = content.decode(ec, errors='replace')
                            m2 = re.match(r"\s*\w+\((.*)\)\s*;?\s*$", t2, re.DOTALL)
                            if m2:
                                t2 = m2.group(1)
                            return json.loads(t2)
                        except Exception:
                            continue
                except Exception:
                    pass
            return {}
        except requests.RequestException:
            time.sleep(0.8 + random.random() * 0.5)
            continue
    return {}


def _fetch_chart_data_browser(
    *,
    catalog: str,
    city: str,
    spec: str,
    start: Optional[str],
    end: Optional[str],
    timeout_ms: int = 20000,
) -> Dict:
    """在浏览器上下文内调用同源接口，复用页面脚本完成签名与请求。返回 dict（含 data/unit）。"""
    from playwright.sync_api import sync_playwright

    js_fetch = """
    async (catalog, city, spec, start, end) => {
      const href = '//index.mysteel.com/zs/newprice/getBaiduChartMultiCity.ms';
      // 等待 jQuery 与 getSign 就绪
      const ok = () => (typeof window !== 'undefined') && window.$ && $.getSign;
      let tries = 0;
      while (!ok() && tries < 50) { await new Promise(r => setTimeout(r, 100)); tries++; }
      if (!ok()) { return {}; }
      const m = href.match(/\.com(\S*)\.ms/);
      const path = (m ? m[1] : '/zs/newprice/getBaiduChartMultiCity') + '.ms';
      // 与页面一致的 appKey/appSec/version
      const APP_KEY = '47EE3F12CF0C443F8FD51EFDA73AC815';
      const APP_SEC = '3BA6477330684B19AA6AF4485497B5F2';
      const VERSION = '1.0.0';
      const signArr = $.getSign(APP_SEC, path);
      const sign = signArr[0];
      const ts = String(signArr[1]);
      const headers = {
        'version': VERSION,
        'appKey': APP_KEY,
        'timestamp': ts,
        'sign': sign,
      };
      const params = new URLSearchParams();
      params.set('catalog', catalog);
      params.set('city', city);
      params.set('spec', spec);
      params.set('callback', 'json');
      params.set('v', String(Date.now()));
      if (start && end) { params.set('startTime', start); params.set('endTime', end); }
      const url = href + '?' + params.toString();
      const res = await fetch(url, { headers });
      const text = await res.text();
      const m2 = text.match(/^\s*\w+\((.*)\)\s*;?\s*$/s);
      const body = m2 ? m2[1] : text;
      try { return JSON.parse(body); } catch (e) { return {}; }
    }
    """

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            page.set_default_timeout(timeout_ms)
        except Exception:
            pass
        page.goto(DEFAULT_PAGE, wait_until='domcontentloaded')
        # 等待必要脚本加载
        try:
            page.wait_for_function("() => window.$ && $.getSign", timeout=timeout_ms)
        except Exception:
            pass
        data = page.evaluate(js_fetch, catalog, city, spec, start or '', end or '')
        browser.close()
        return data if isinstance(data, dict) else {}
