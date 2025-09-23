import os
from datetime import datetime
from typing import Dict, Any
import contextlib

import pytest
from fastapi.testclient import TestClient

import main
from test.utils_report import write_markdown_section, write_raw_json


@pytest.fixture(scope="session")
def client() -> TestClient:
    return TestClient(main.app)


@pytest.fixture(scope="session")
def report_paths(tmp_path_factory):
    # 始终写入仓库相对的 test/reports 目录，便于用户查看
    base_dir = os.path.join(os.path.dirname(__file__), "reports")
    os.makedirs(base_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_md = os.path.join(base_dir, f"real_crawl_report_{ts}.md")
    raw_dir = os.path.join(base_dir, "raw")
    # 初始化 Markdown 报告文件
    # 使用 UTF-8 BOM，确保在部分 Windows 编辑器中不出现乱码
    with open(report_md, "w", encoding="utf-8-sig") as f:
        f.write(f"# 实时抓取测试报告\n\n生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    return {"md": report_md, "raw": raw_dir, "ts": ts}

def _record(title: str, name: str, report_paths: Dict[str, str], payload: Dict[str, Any]):
    write_markdown_section(report_paths["md"], title, payload)
    ts_name = f"{name}_{report_paths['ts']}"
    write_raw_json(report_paths["raw"], ts_name, payload)


@pytest.fixture(scope="session", autouse=True)
def capture_logs(report_paths):
    log_file = os.path.join(report_paths["raw"], f"test_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")
    with open(log_file, "w", encoding="utf-8") as f:
        with contextlib.redirect_stdout(f), contextlib.redirect_stderr(f):
            yield


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
    "guangming",
    "economic",
    "qiushi",
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


@pytest.mark.parametrize("category", ["fzggwl", "ghxwj", "ghwb", "gg", "tz"])
def test_ndrc_single_category(client: TestClient, report_paths, category: str):
    r = client.get(
        "/api/get_daily_ndrc_news",
        params={"categories": category, "max_pages": 1, "max_items": 3},
    )
    assert r.status_code in (200, 500)
    data = r.json()
    _record(f"发改委政策 - {category}", f"ndrc_{category}", report_paths, data)
    if r.status_code == 200:
        assert set(data.keys()) >= {"status", "news_list", "err_code", "err_info"}


def test_transport_news(client: TestClient, report_paths):
    r = client.get("/api/get_transport_gov_news")
    assert r.status_code in (200, 500, 404)
    data = r.json()
    _record("交通运输部新闻", "transport_news", report_paths, data)
    if r.status_code == 200:
        assert set(data.keys()) >= {"status", "news_list", "err_code", "err_info"}


def test_commerce_news(client: TestClient, report_paths):
    r = client.get("/api/get_commerce_gov_news")
    assert r.status_code in (200, 500, 404)
    data = r.json()
    _record("商务部新闻", "commerce_news", report_paths, data)
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


@pytest.mark.parametrize("channel", ["zy", "qggsl", "jd"])
def test_acfic_single_channel(client: TestClient, report_paths, channel: str):
    r = client.get(
        "/api/get_acfic_policies",
        params={"channels": channel, "max_pages": 1, "max_items": 3},
    )
    assert r.status_code in (200, 500)
    data = r.json()
    _record(f"工商联政策 - {channel}", f"acfic_{channel}", report_paths, data)
    if r.status_code == 200:
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
    # 该接口返回包含 sections/groups 的字典；记录原始返回便于排查
    assert r.status_code in (200,)
    data = r.json()
    ts_name = f"chinaisa_sections_{report_paths['ts']}"
    write_raw_json(report_paths["raw"], ts_name, data)
    # 同时在 Markdown 中追加一个简要汇总块
    from test.utils_report import _ensure_dir
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
