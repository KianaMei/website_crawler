import re
import json
import time
import random
from typing import Dict, List, Optional, Tuple

import requests


DEFAULT_PAGE = "https://index.mysteel.com/price/getChartMultiCity_1_0.html"
API_URL = "https://index.mysteel.com/zs/newprice/getBaiduChartMultiCity.ms"
API_VERSION = "1.0.0"
APP_KEY = "47EE3F12CF0C443F8FD51EFDA73AC815"
APP_SEC = "3BA6477330684B19AA6AF4485497B5F2"

UA_LIST = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:131.0) Gecko/20100101 Firefox/131.0",
]


_CITY_FALLBACK = {
    "上海": "15278",
    "北京": "15472",
    "南京": "15407",
    "天津": "15480",
    "唐山": "15605",
    "广州": "15738",
    "杭州": "15372",
    "宁波": "15584",
}

_SPEC_VALUE_OVERRIDES = {
    ("螺纹钢", "HRB400E 20MM"): "HRB400E_Φ20",
}


def _download_baidu_data(session: requests.Session, timeout: int = 20) -> str:
    url = "https://a.mysteelcdn.com/jgzs/jg/v1/js/baiduData.js?v=20220905"
    r = session.get(url, timeout=timeout, verify=False, proxies={"http": None, "https": None})
    r.raise_for_status()
    data = r.content
    # 优先 gb18030，再退 utf-8
    for ec in ("gb18030", "utf-8"):
        try:
            return data.decode(ec, errors="replace")
        except Exception:
            continue
    return r.text or ""


def get_city_code_map(session: Optional[requests.Session] = None, timeout: int = 20) -> Dict[str, str]:
    """解析 baiduData.js，返回 城市->编码 映射；若失败，回退常用城市集。"""
    close_after = False
    if session is None:
        session = requests.Session()
        session.trust_env = False
        close_after = True
    try:
        text = _download_baidu_data(session, timeout=timeout)
        # 匹配 “城市:编码”
        rx = re.compile(r"([\u4e00-\u9fa5]{2,}):([0-9]{3,6})")
        m = rx.findall(text)
        out: Dict[str, str] = {}
        for name, code in m:
            if name not in out:
                out[name] = code
        # 合并回退集
        out.update({k: v for k, v in _CITY_FALLBACK.items() if k not in out})
        return out
    except Exception:
        return dict(_CITY_FALLBACK)
    finally:
        if close_after:
            session.close()


class MysteelClient:
    def __init__(self, user_agent: Optional[str] = None, log_file: Optional[str] = None):
        self.session = requests.Session()
        self.session.trust_env = False
        self.ua = user_agent or random.choice(UA_LIST)
        # 日志文件（默认写入 mysteel/request_log.txt）
        self.log_file = log_file or "mysteel/request_log.txt"

    def _log(self, message: str) -> None:
        try:
            import os
            os.makedirs("mysteel", exist_ok=True)
            ts = time.strftime("%Y-%m-%d %H:%M:%S")
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(f"[{ts}] {message}\n")
        except Exception:
            pass

    def _base_headers(self) -> Dict[str, str]:
        return {
            "User-Agent": self.ua,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.6",
            "Connection": "keep-alive",
            "Referer": "https://index.mysteel.com/",
        }

    def warm(self, url: str = DEFAULT_PAGE, timeout: int = 20) -> None:
        """Cookie 预热：访问页面和同域资源，获取必要 Cookie。"""
        headers = self._base_headers()
        # 主页
        self._log(f"WARM GET {url}")
        self.session.get(url, headers=headers, timeout=timeout, verify=False, proxies={"http": None, "https": None})
        # 根域
        self._log("WARM GET https://index.mysteel.com/")
        self.session.get("https://index.mysteel.com/", headers=headers, timeout=timeout, verify=False, proxies={"http": None, "https": None})
        # favicon（同域资源）
        self._log("WARM GET https://index.mysteel.com/favicon.ico")
        self.session.get("https://index.mysteel.com/favicon.ico", headers=headers, timeout=timeout, verify=False, proxies={"http": None, "https": None})

    def warm_via_browser(self, url: str = DEFAULT_PAGE, wait_ms: int = 10000, browser: str = "auto", headless: bool = False) -> bool:
        """半自动浏览器预热：
        - 使用 Selenium 打开页面，等待 JS 执行并写入 Cookie；
        - 将浏览器 Cookie 注入到 requests Session；
        - 返回是否成功。
        说明：本方法仅在本机可用 Selenium 且浏览器可用时生效；否则返回 False，不抛异常。
        """
        try:
            import time as _t
            try:
                # 优先 Chrome
                if browser in ("auto", "chrome"):
                    from selenium import webdriver as _wd
                    from selenium.webdriver.chrome.options import Options as _ChromeOptions
                    co = _ChromeOptions()
                    if headless:
                        co.add_argument("--headless=new")
                    co.add_argument("--disable-gpu")
                    co.add_argument("--no-sandbox")
                    co.add_argument("--disable-dev-shm-usage")
                    self._log("browser-warm: launching Chrome")
                    drv = _wd.Chrome(options=co)
                else:
                    raise ImportError
            except Exception:
                # 退回 Edge
                from selenium import webdriver as _wd
                from selenium.webdriver.edge.options import Options as _EdgeOptions
                eo = _EdgeOptions()
                if headless:
                    eo.add_argument("--headless=new")
                eo.add_argument("--disable-gpu")
                eo.add_argument("--no-sandbox")
                eo.add_argument("--disable-dev-shm-usage")
                self._log("browser-warm: launching Edge")
                drv = _wd.Edge(options=eo)

            drv.set_page_load_timeout(max(15, int(wait_ms/1000) + 8))
            drv.get(url)
            # 等待页面与脚本加载更充分：优先等待 $.getSign 出现，再兜底按照时间
            deadline = _t.time() + (wait_ms/1000.0)
            expected = {"WM_NI", "WM_NIKE", "WM_TID", "gdxidpyhxdE"}
            seen_expected = set()
            while _t.time() < deadline:
                try:
                    # 检查 getSign 是否就绪
                    ready = drv.execute_script("return !!(window.$ && $.getSign);")
                except Exception:
                    ready = False
                # 收集当前 cookies
                try:
                    for ck in drv.get_cookies():
                        n = ck.get("name") or ""
                        if n in expected:
                            seen_expected.add(n)
                except Exception:
                    pass
                if ready and seen_expected == expected:
                    break
                _t.sleep(0.5)
            # 读取 cookies
            got = 0
            for ck in drv.get_cookies():
                name = ck.get("name"); value = ck.get("value"); domain = ck.get("domain") or "index.mysteel.com"
                if not name or value is None:
                    continue
                try:
                    self.session.cookies.set(name, value, domain=domain)
                    got += 1
                except Exception:
                    continue
            self._log(f"browser-warm: injected cookies={got} expected_present={sorted(list(seen_expected))}")
            drv.quit()
            return got > 0
        except Exception as e:
            self._log(f"browser-warm failed: {e}")
            return False

    @staticmethod
    def _compute_sign(path: str, ts: int) -> str:
        raw = f"path{path}timestamp{ts}version{API_VERSION}{APP_SEC}"
        import hashlib
        return hashlib.md5(raw.encode("utf-8")).hexdigest().upper()

    def _api_headers(self, ts: int, sign: str) -> Dict[str, str]:
        return {
            "version": API_VERSION,
            "appKey": APP_KEY,
            "timestamp": str(ts),
            "sign": sign,
            "User-Agent": self.ua,
            "Referer": DEFAULT_PAGE,
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "X-Requested-With": "XMLHttpRequest",
            "Origin": "https://index.mysteel.com",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.6",
        }

    @staticmethod
    def _path_from_api(url: str) -> str:
        m = re.search(r"\.com(\S*)\.ms", url)
        if not m:
            return "/zs/newprice/getBaiduChartMultiCity.ms"
        return m.group(1) + ".ms"

    @staticmethod
    def _parse_json_or_jsonp(text: str) -> Dict:
        if not text:
            return {}
        m = re.match(r"\s*\w+\((.*)\)\s*;?\s*$", text, re.DOTALL)
        if m:
            body = m.group(1)
        else:
            body = text
        try:
            return json.loads(body)
        except Exception:
            return {}

    def _call_api(self, params: Dict[str, str], timeout: int = 20, override_headers: Optional[Dict[str, str]] = None) -> Dict:
        path = self._path_from_api(API_URL)
        ts = int(time.time() * 1000)
        sign = self._compute_sign(path, ts)
        headers = self._api_headers(ts, sign)
        if override_headers:
            headers.update(override_headers)
        # 记录请求
        try:
            from urllib.parse import urlencode
            qs = urlencode(params, doseq=True, encoding="utf-8")
        except Exception:
            qs = str(params)
        self._log(f"API GET {API_URL}?{qs}")
        self._log(f"HEADERS version={headers.get('version')} appKey={headers.get('appKey')} ts={headers.get('timestamp')} sign={headers.get('sign')[:8]}...")
        r = self.session.get(
            API_URL,
            params=params,
            headers=headers,
            timeout=timeout,
            verify=False,
            proxies={"http": None, "https": None},
            allow_redirects=True,
        )
        r.raise_for_status()
        txt = r.text or ""
        self._log(f"RESP status={r.status_code} len={len(txt)}")
        if txt:
            try:
                preview = txt[:200].replace("\n", " ") if isinstance(txt, str) else ""
            except Exception:
                preview = ""
            self._log(f"RESP body.head={preview}")
        if not txt:
            return {}
        obj = self._parse_json_or_jsonp(txt)
        if isinstance(obj, dict):
            msg = obj.get("message")
            data_len = len(obj.get("data") or [])
            self._log(f"RESP parsed message={msg} data_len={data_len}")
        return obj if isinstance(obj, dict) else {}

    def get_multi_city_price(
        self,
        *,
        catalog: str,
        spec: str,
        cities: List[str],
        start: Optional[str] = None,
        end: Optional[str] = None,
        timeout: int = 20,
        warm: bool = True,
        per_city_fallback: bool = True,
        extra_cookies: Optional[str] = None,
        override_headers: Optional[Dict[str, str]] = None,
        browser_warm: bool = True,
        browser_wait_ms: int = 4000,
        browser: str = "auto",
        browser_headless: bool = False,
        browser_fetch: bool = False,
    ) -> Dict:
        """获取多城市价格曲线，必要时逐城合并。
        返回 dict: { 'data': [...], 'unit': '...' } 或 {}。
        """
        if warm:
            try:
                self.warm(DEFAULT_PAGE, timeout=timeout)
            except Exception:
                pass
        # 尝试浏览器预热
        if browser_warm:
            ok = self.warm_via_browser(DEFAULT_PAGE, wait_ms=browser_wait_ms, browser=browser, headless=browser_headless)
            self._log(f"browser-warm ok={ok}")
        # 注入额外 Cookie（来自浏览器抓包）
        if extra_cookies:
            try:
                for item in extra_cookies.split(';'):
                    if not item.strip():
                        continue
                    if '=' not in item:
                        continue
                    k, v = item.strip().split('=', 1)
                    k = k.strip()
                    v = v.strip()
                    # Cookie 必须是 ASCII，若包含非 ASCII 则百分号编码
                    try:
                        v.encode('latin-1')
                    except Exception:
                        from urllib.parse import quote
                        v = quote(v, safe='')
                    self.session.cookies.set(k, v, domain='index.mysteel.com')
                self._log("extra cookies applied")
            except Exception:
                self._log("extra cookies apply failed")

        # 参数组装：API 期望 "展示_:_值" 的格式
        cat_pair = f"{catalog}_:_{catalog}"
        spec_value = self._resolve_spec_value(catalog, spec, timeout=timeout)
        spec_pair = f"{spec}_:_{spec_value}" if spec_value else f"{spec}_:_{spec}"

        # 多城请求
        params = {
            "catalog": cat_pair,
            "city": ",".join(cities),
            "spec": spec_pair,
            "callback": "json",
            "v": str(int(time.time() * 1000)),
        }
        if start and end:
            params["startTime"] = start
            params["endTime"] = end
        # 若提供了覆盖 timestamp，则令 v 与之保持一致
        if override_headers and override_headers.get("timestamp"):
            params["v"] = str(override_headers.get("timestamp"))

        try:
            obj = self._call_api(params, timeout=timeout, override_headers=override_headers)
        except requests.RequestException:
            obj = {}

        if obj.get("data"):
            self._log(f"MULTI-CITY OK cities={len(cities)} data_len={len(obj.get('data') or [])}")
            return obj

        # 页内 fetch（同源）回退：先多城，再逐城
        if browser_fetch:
            self._log("browser-fetch: trying multi-city")
            try:
                bf = self._browser_fetch_data(
                    catalog=catalog,
                    spec=spec_pair,
                    city=",".join(cities),
                    start=start,
                    end=end,
                    browser=browser,
                    headless=browser_headless,
                    wait_ms=browser_wait_ms,
                )
            except Exception as e:
                self._log(f"browser-fetch multi failed: {e}")
                bf = {}
            if bf.get("data"):
                return bf

            merged_b: List[Dict] = []
            unit_b: Optional[str] = None
            for c in cities[:6]:
                self._log(f"browser-fetch single {c}")
                try:
                    o = self._browser_fetch_data(
                        catalog=catalog,
                        spec=spec_pair,
                        city=c,
                        start=start,
                        end=end,
                        browser=browser,
                        headless=browser_headless,
                        wait_ms=browser_wait_ms,
                    )
                except Exception as e:
                    self._log(f"browser-fetch single failed {c}: {e}")
                    o = {}
                if o.get("data"):
                    if unit_b is None:
                        unit_b = o.get("unit") or None
                    merged_b.extend(o.get("data") or [])
            if merged_b:
                return {"data": merged_b, "unit": unit_b}

        # 逐城回退
        if not per_city_fallback:
            return obj if isinstance(obj, dict) else {}

        unit: Optional[str] = None
        merged: List[Dict] = []
        for c in cities[:6]:
            p = params.copy()
            p["city"] = c
            self._log(f"SINGLE-CITY FETCH {c}")
            try:
                o = self._call_api(p, timeout=timeout, override_headers=override_headers)
            except requests.RequestException:
                o = {}
            if o.get("data"):
                if unit is None:
                    unit = o.get("unit") or None
                for it in (o.get("data") or []):
                    merged.append(it)
            time.sleep(0.2)
        if merged:
            self._log(f"SINGLE-CITY MERGED count={len(merged)} unit={unit}")
            return {"data": merged, "unit": unit}
        return obj if isinstance(obj, dict) else {}

    def _resolve_spec_value(self, breed_name: str, spec_display: str, timeout: int = 20) -> Optional[str]:
        """从 baiduData.js 中解析某品类下规格展示 -> 规格值（如 'HRB400E 20MM' -> 'HRB400E_Φ20'）。"""
        # 先走强制覆盖，以避免编码歧义
        ov = _SPEC_VALUE_OVERRIDES.get((breed_name, spec_display))
        if ov:
            self._log(f"spec-map: override '{spec_display}' -> '{ov}'")
            return ov
        try:
            text = _download_baidu_data(self.session, timeout=timeout)
        except Exception:
            self._log("spec-map: download baiduData.js failed")
            return None
        try:
            # 直接全局匹配 name/value（不依赖中文品类名，以避免编码误差）
            spec_rx = re.compile(r"\{\s*'name'\s*:\s*'([^']+)'\s*,\s*'value'\s*:\s*'([^']+)'\s*\}")
            for nm, val in spec_rx.findall(text):
                if nm.strip() == spec_display.strip():
                    self._log(f"spec-map: matched '{nm}' -> '{val}' (global)")
                    return val.strip()
            self._log(f"spec-map: no match for spec '{spec_display}' (global)")
        except Exception:
            self._log("spec-map: parse error")
            return None
        return None

    def _browser_fetch_data(
        self,
        *,
        catalog: str,
        spec: str,
        city: str,
        start: Optional[str],
        end: Optional[str],
        browser: str = "auto",
        headless: bool = False,
        wait_ms: int = 8000,
    ) -> Dict:
        """使用 Selenium 在页面内以同源 fetch 方式获取 JSON。spec、catalog 需要传入 "展示_:_值" 格式。"""
        from selenium import webdriver as _wd
        import json as _json
        import time as _t

        # 启动浏览器
        drv = None
        try:
            if browser in ("auto", "chrome"):
                try:
                    from selenium.webdriver.chrome.options import Options as _ChromeOptions
                    co = _ChromeOptions()
                    if headless:
                        co.add_argument("--headless=new")
                    co.add_argument("--disable-gpu")
                    co.add_argument("--no-sandbox")
                    co.add_argument("--disable-dev-shm-usage")
                    self._log("browser-fetch: launching Chrome")
                    drv = _wd.Chrome(options=co)
                except Exception:
                    drv = None
            if drv is None:
                from selenium.webdriver.edge.options import Options as _EdgeOptions
                eo = _EdgeOptions()
                if headless:
                    eo.add_argument("--headless=new")
                eo.add_argument("--disable-gpu")
                eo.add_argument("--no-sandbox")
                eo.add_argument("--disable-dev-shm-usage")
                self._log("browser-fetch: launching Edge")
                drv = _wd.Edge(options=eo)

            drv.set_page_load_timeout(max(15, int(wait_ms/1000) + 8))
            drv.get(DEFAULT_PAGE)
            # 等待 $.getSign
            deadline = _t.time() + (wait_ms/1000.0)
            while _t.time() < deadline:
                try:
                    ready = drv.execute_script("return !!(window.$ && $.getSign);")
                except Exception:
                    ready = False
                if ready:
                    break
                _t.sleep(0.2)

            # 模拟一次页面交互：写入隐藏域并触发 change（有助于页面脚本刷新内部状态）
            try:
                drv.execute_script(
                    """
                    (function(catalog, spec, city){
                        try {
                            var bv=document.getElementById('breedValue'); if(bv) bv.value=catalog;
                            var sv=document.getElementById('specValue'); if(sv) sv.value=spec;
                            var cv=document.getElementById('cityValue'); if(cv) cv.value=city;
                            if (window.jQuery) {
                                try{ jQuery('#breedValue,#specValue,#cityValue').trigger('change'); }catch(e){}
                            }
                            if (window.multiCitySelect && typeof multiCitySelect.bindValue==='function'){
                                try{ multiCitySelect.bindValue(catalog.split('_:_')[0]+'_:_'+catalog.split('_:_')[0], spec, city); }catch(e){}
                            }
                        } catch(e){}
                    })(arguments[0], arguments[1], arguments[2]);
                    """,
                    catalog, spec, city
                )
                _t.sleep(1.0)
            except Exception as _e:
                self._log(f"browser-fetch simulate interaction failed: {_e}")

            # 执行异步 JS 发起 fetch
            script = """
            var catalog = arguments[0];
            var city = arguments[1];
            var spec = arguments[2];
            var start = arguments[3];
            var end = arguments[4];
            var cb = arguments[5];
            (async () => {
              try {
                const href = '//index.mysteel.com/zs/newprice/getBaiduChartMultiCity.ms';
                const ok = () => (typeof window !== 'undefined') && window.$ && $.getSign;
                let tries = 0;
                while (!ok() && tries < 100) { await new Promise(r => setTimeout(r, 100)); tries++; }
                if (!ok()) { cb(JSON.stringify({})); return; }
                // 预取一个同源资源，帮助写入更多 Cookie
                try { await fetch('/zs/newprice/mysteel.htm', {cache:'no-store'}); } catch (e) {}
                const m = href.match(/\.com(\S*)\.ms/);
                const path = (m ? m[1] : '/zs/newprice/getBaiduChartMultiCity') + '.ms';
                const APP_KEY = '47EE3F12CF0C443F8FD51EFDA73AC815';
                const APP_SEC = '3BA6477330684B19AA6AF4485497B5F2';
                const VERSION = '1.0.0';
                const signArr = $.getSign(APP_SEC, path);
                const sign = signArr[0];
                const ts = String(signArr[1]);
                const headers = { 'version': VERSION, 'appKey': APP_KEY, 'timestamp': ts, 'sign': sign };
                const p = new URLSearchParams();
                p.set('catalog', catalog);
                p.set('city', city);
                p.set('spec', spec);
                p.set('callback', 'json');
                p.set('v', ts);
                if (start && end) { p.set('startTime', start); p.set('endTime', end); }
                const url = href + '?' + p.toString();
                // 使用 jQuery.ajax 以便自动带上 X-Requested-With
                const text = await new Promise((resolve) => {
                  $.ajax({
                    type: 'GET', url: url, headers: headers, dataType: 'text', timeout: 20000,
                    success: function(data){ resolve(String(data||'')); },
                    error: function(){ resolve(''); }
                  });
                });
                const m2 = text.match(/^\s*\w+\((.*)\)\s*;?\s*$/s);
                const body = m2 ? m2[1] : text;
                cb(body);
              } catch (e) { cb(JSON.stringify({})); }
            })();
            """
            body = drv.execute_async_script(script, catalog, city, spec, start or '', end or '')
            try:
                obj = _json.loads(body)
            except Exception:
                obj = {}
            drv.quit()
            self._log(f"browser-fetch result keys={list(obj.keys()) if isinstance(obj, dict) else None}")
            return obj if isinstance(obj, dict) else {}
        except Exception as e:
            try:
                if drv:
                    drv.quit()
            except Exception:
                pass
            self._log(f"browser-fetch exception: {e}")
            return {}


if __name__ == "__main__":
    # Minimal manual probe:
    client = MysteelClient()
    try:
        code_map = get_city_code_map(client.session)
        cities = [f"上海:{code_map.get('上海','15278')}", f"杭州:{code_map.get('杭州','15372')}"]
        resp = client.get_multi_city_price(catalog="螺纹钢", spec="HRB400E_20MM", cities=cities, warm=True)
        data = resp.get("data") or []
        print("series", len(data))
        if data:
            first = data[0]
            print(first.get("name"), len(first.get("dateValueMap") or []))
    except Exception as e:
        print("probe error", e)
