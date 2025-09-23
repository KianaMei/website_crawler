import os
from datetime import datetime
from typing import Dict, Any

import pytest
from fastapi.testclient import TestClient

import main
from test.utils_report import write_markdown_section, write_raw_json


@pytest.fixture(scope="session")
def client() -> TestClient:
    return TestClient(main.app)


@pytest.fixture(scope="session")
def report_paths(tmp_path_factory):
    # Always write to repo-relative test/reports for user visibility
    base_dir = os.path.join(os.path.dirname(__file__), "reports")
    os.makedirs(base_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_md = os.path.join(base_dir, f"real_crawl_report_{ts}.md")
    raw_dir = os.path.join(base_dir, "raw")
    # Initialize MD
    # 使用 UTF-8 BOM，确保在部分 Windows 编辑器中不出现乱码
    with open(report_md, "w", encoding="utf-8-sig") as f:
        f.write(f"# 实时抓取测试报告\n\n生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    return {"md": report_md, "raw": raw_dir}


def _record(title: str, name: str, report_paths: Dict[str, str], payload: Dict[str, Any]):
    write_markdown_section(report_paths["md"], title, payload)
    write_raw_json(report_paths["raw"], name, payload)


def test_cctv_news(client: TestClient, report_paths):
    r = client.get("/api/get_daily_cctv_news")
    assert r.status_code in (200, 500, 404)
    data = r.json()
    _record("CCTV 新闻联播", "cctv_news", report_paths, data)
    if r.status_code == 200:
        assert set(data.keys()) >= {"status", "news_list", "err_code", "err_info"}


def test_ai_news(client: TestClient, report_paths):
    r = client.get("/api/get_daily_ai_news")
    assert r.status_code in (200, 500, 404)
    data = r.json()
    _record("AI 每日新闻", "ai_news", report_paths, data)
    if r.status_code == 200:
        assert set(data.keys()) >= {"status", "news_list", "err_code", "err_info"}


@pytest.mark.parametrize("source", [
    "peopledaily",
    "xinhua",
    "jjckb",
])
def test_paper_news_variants(client: TestClient, report_paths, source: str):
    r = client.get("/api/get_daily_paper_news", params={"source": source, "max_items": 3})
    assert r.status_code in (200, 500)
    data = r.json()
    _record(f"纸媒新闻 - {source}", f"paper_{source}", report_paths, data)
    if r.status_code == 200:
        assert set(data.keys()) >= {"status", "news_list", "err_code", "err_info"}


def test_ndrc_multi_categories(client: TestClient, report_paths):
    r = client.get(
        "/api/get_daily_ndrc_news",
        params={"categories": "ghxwj,gg", "max_pages": 1, "max_items": 6},
    )
    assert r.status_code in (200, 500)
    data = r.json()
    _record("发改委政策 - ghxwj,gg", "ndrc_ghxwj_gg", report_paths, data)
    if r.status_code == 200:
        assert set(data.keys()) >= {"status", "news_list", "err_code", "err_info"}


def test_acfic_policies_default(client: TestClient, report_paths):
    r = client.get(
        "/api/get_acfic_policies",
        params={"channels": "zy,qggsl,jd", "max_pages": 1, "max_items": 5},
    )
    assert r.status_code in (200, 500)
    data = r.json()
    _record("工商联政策 - zy,qggsl,jd", "acfic_zy_qggsl_jd", report_paths, data)
    assert set(data.keys()) >= {"status", "news_list", "err_code", "err_info"}


@pytest.mark.parametrize("channels", ["zcfg", "zixun", "zcfg,zixun"])
def test_cflp_news_channels(client: TestClient, report_paths, channels: str):
    r = client.get(
        "/api/get_cflp_news",
        params={"channels": channels, "max_pages": 1, "max_items": 5, "since_days": 7},
    )
    assert r.status_code in (200, 500)
    data = r.json()
    _record(f"CFLP - {channels}", f"cflp_{channels.replace(',', '_')}", report_paths, data)
    if r.status_code == 200:
        assert set(data.keys()) >= {"status", "news_list", "err_code", "err_info"}


def test_chinaisa_sections(client: TestClient, report_paths):
    r = client.get("/api/chinaisa/sections", params={"include_subtabs": True})
    # This endpoint returns dict with sections/groups; record raw
    assert r.status_code in (200,)
    data = r.json()
    write_raw_json(report_paths["raw"], "chinaisa_sections", data)
    # Also append a small summary block into MD
    from .utils_report import _ensure_dir
    with open(report_paths["md"], "a", encoding="utf-8") as f:
        f.write("\n\n## ChinaISA 栏目映射\n")
        f.write(f"- sections: {len(data.get('sections') or {})}\n")
        f.write(f"- groups: {len(data.get('groups') or [])}\n")


def test_chinaisa_news_sample(client: TestClient, report_paths):
    r = client.get(
        "/api/chinaisa/news",
        params={"page": 1, "size": 10, "max": 20, "max_pages": 2, "include_subtabs": True},
    )
    assert r.status_code in (200, 500)
    data = r.json()
    _record("ChinaISA 新闻采样", "chinaisa_news", report_paths, data)
    if r.status_code == 200:
        assert set(data.keys()) >= {"status", "news_list", "err_code", "err_info"}
