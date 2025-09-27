import argparse
import sys
import os

# Ensure repo root on sys.path
ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from mysteel import MysteelClient, get_city_code_map


def main() -> int:
    ap = argparse.ArgumentParser(description="Probe Mysteel API for a single city")
    ap.add_argument("--city", default="上海", help="城市名，或 形如 名称:编码 的形式（默认: 上海）")
    ap.add_argument("--catalog", default="螺纹钢", help="品类，默认: 螺纹钢")
    ap.add_argument("--spec", default="HRB400E_20MM", help="规格值，默认: HRB400E_20MM")
    ap.add_argument("--start", default=None, help="起始日期 YYYY-MM-DD，可选")
    ap.add_argument("--end", default=None, help="截止日期 YYYY-MM-DD，可选")
    ap.add_argument("--no-warm", action="store_true", help="跳过 Cookie 预热（默认开启预热）")
    # Browser warm options
    ap.add_argument("--no-browser-warm", action="store_true", help="禁用浏览器预热（默认开启）")
    ap.add_argument("--browser-wait-ms", type=int, default=10000, help="浏览器预热等待毫秒，默认 10000")
    ap.add_argument("--browser", default="auto", choices=["auto","chrome","edge"], help="浏览器类型，默认 auto")
    ap.add_argument("--headless", action="store_true", help="浏览器无头模式")
    # Manual injection
    ap.add_argument("--cookie", default=None, help="手动注入 Cookie（整条）")
    ap.add_argument("--ts", default=None, help="覆盖 timestamp（也会对齐到 v）")
    ap.add_argument("--sign", default=None, help="覆盖 sign")
    ap.add_argument("--appKey", default=None, help="覆盖 appKey")
    args = ap.parse_args()

    client = MysteelClient()
    code_map = get_city_code_map(client.session)

    if ":" in args.city:
        city_pair = args.city
    else:
        code = code_map.get(args.city)
        if not code:
            print(f"未找到城市编码: {args.city}")
            print("可用城市样例:", ", ".join(list(code_map.keys())[:16]))
            return 2
        city_pair = f"{args.city}:{code}"

    print(f"catalog={args.catalog} spec={args.spec} city={city_pair}")
    headers_override = {}
    if args.ts: headers_override['timestamp'] = str(args.ts)
    if args.sign: headers_override['sign'] = str(args.sign)
    if args.appKey: headers_override['appKey'] = str(args.appKey)

    resp = client.get_multi_city_price(
        catalog=args.catalog,
        spec=args.spec,
        cities=[city_pair],
        start=args.start,
        end=args.end,
        warm=not args.no_warm,
        per_city_fallback=False,
        extra_cookies=args.cookie,
        override_headers=headers_override or None,
        browser_warm=not args.no_browser_warm,
        browser_wait_ms=args.browser_wait_ms,
        browser=args.browser,
        browser_headless=args.headless,
    )
    data = resp.get("data") or []
    print("series:", len(data))
    if data:
        s0 = data[0]
        dv = s0.get("dateValueMap") or []
        print("name:", s0.get("name"), "points:", len(dv))
        for item in dv[-5:]:
            print(item.get("date"), item.get("value"))
    else:
        print("message:", resp.get("message"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
