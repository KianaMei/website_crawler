# 网站抓取聚合 API（website_crawler）

统一抓取多来源新闻数据，并以统一数据结构返回，使用 FastAPI 提供 HTTP 接口。

- CCTV 新闻联播要闻
- Aibase AI 每日资讯
- 纸媒要闻：人民日报/光明日报/经济日报/求是/新华每日电讯/经济参考报
- 政府要闻：国家发展改革委/交通运输部/商务部
- 行业协会/商会：全国工商联（ACFIC）/中国物流与采购联合会（CFLP）/中国信息安全认证中心（ChinaISA）


## 环境与安装
- Python >= 3.13（pyproject 要求）；建议 3.13
- 安装方式（二选一）
  - pip
    - Windows PowerShell
      - `python -m venv .venv`
      - `.venv\\Scripts\\activate`
      - `python -m pip install -U pip`
      - `pip install .`
  - uv（推荐，已在 pyproject 配置清华镜像）
    - `uv venv`
    - `uv pip install -e .`

可选依赖（仅当使用商务部动态抓取时需要 Playwright）：
- `pip install playwright`
- `python -m playwright install chromium`


## 运行
- 启动服务：
  - `uvicorn main:app --host 0.0.0.0 --port 8000 --reload`
- 文档地址：
  - Swagger: `http://127.0.0.1:8000/docs`
  - ReDoc:   `http://127.0.0.1:8000/redoc`


## 统一响应模型
所有接口返回 NewsResponse：

```json
{
  "status": "OK | EMPTY | ERROR",
  "news_list": [
    {
      "title": "标题",
      "url": "详情页链接",
      "origin": "来源站点/栏目",
      "summary": "摘要（可能为正文前若干字符）",
      "publish_date": "YYYY-MM-DD"
    }
  ],
  "err_code": null,
  "err_info": null
}
```


## API 速览与示例
以下示例均基于本地默认端口 `8000`。

- GET `/api/get_daily_ai_news`
  - 作用：抓取 Aibase AI 每日资讯
  - 示例：
    - `curl "http://127.0.0.1:8000/api/get_daily_ai_news"`

- GET `/api/get_daily_paper_news`
  - 作用：抓取纸媒要闻（可指定来源/日期）
  - 参数：
    - `source`: `peopledaily|guangming|economic|qiushi|xinhua|jjckb`（默认 `peopledaily`）
    - `max_items`: 1–50（默认 10）
    - `date`: `YYYY-MM-DD`（可选；不填则寻找最近可用日期）
  - 示例：
    - `curl "http://127.0.0.1:8000/api/get_daily_paper_news?source=peopledaily&max_items=5"`

- GET `/api/get_daily_ndrc_news`
  - 作用：抓取国家发展改革委分类要闻（多选）
  - 参数：
    - `categories`: `fzggwl,ghxwj,ghwb,gg,tz`（CSV，多选）
    - `max_pages`: 1–10（默认 1）
    - `max_items`: 1–100（默认 10）
  - 示例：
    - `curl "http://127.0.0.1:8000/api/get_daily_ndrc_news?categories=fzggwl,ghxwj&max_items=8"`

- GET `/api/get_transport_gov_news`
  - 作用：抓取交通运输部“交通要闻”（近 N 天）
  - 示例：
    - `curl "http://127.0.0.1:8000/api/get_transport_gov_news"`

- GET `/api/get_commerce_gov_news`
  - 作用：抓取商务部“领导/部领导活动”动态
  - 说明：依赖 Playwright；需先安装浏览器内核（见上）
  - 示例：
    - `curl "http://127.0.0.1:8000/api/get_commerce_gov_news"`

- GET `/api/get_acfic_policies`
  - 作用：抓取全国工商联政策/资讯（多频道）
  - 参数：
    - `channels`: `zy,bw,df,qggsl,jd`（CSV；为空表示默认全选部分）
    - `max_pages`: 1–10（默认 1）
    - `max_items`: 1–100（默认 5）
  - 示例：
    - `curl "http://127.0.0.1:8000/api/get_acfic_policies?channels=zy,qggsl,jd&max_items=8"`

- GET `/api/get_cflp_news`
  - 作用：抓取中国物流与采购联合会 政策/资讯
  - 参数：
    - `channels`: `zcfg,zixun`（CSV；支持别名 `dzsp -> zixun`）
    - `max_pages`: 1–10（默认 1）
    - `max_items`: 1–100（默认 8）
    - `since_days`: 1–60（默认 7；超出 N 天将停止翻页）
  - 示例：
    - `curl "http://127.0.0.1:8000/api/get_cflp_news?channels=zcfg,zixun&since_days=7&max_items=8"`

- GET `/api/chinaisa/news`
  - 作用：抓取 ChinaISA 指定栏目（支持子页签统计/行业信息/价格指数等）
  - 参数：
    - `columns`: 栏目 columnId CSV；留空使用内建默认集合
    - `page`: 1–50（默认 1）
    - `size`: 1–100（默认 20）
    - `max`: 1–1000（默认 60）
    - `since_days`: 1–60（可选）
    - `max_pages`: 1–10（默认 3）
    - `include_subtabs`: 是否包含子页签（默认 true）
  - 示例：
    - `curl "http://127.0.0.1:8000/api/chinaisa/news?page=1&size=10&max=20&max_pages=2&include_subtabs=true"`

- GET `/api/chinaisa/sections`
  - 作用：返回 ChinaISA 栏目结构映射；包含 baseline_subtabs 与实时抓取结果对比
  - 参数：
    - `include_subtabs`: 是否包含子页签（默认 true）
  - 示例：
    - `curl "http://127.0.0.1:8000/api/chinaisa/sections?include_subtabs=true"`


## 目录结构（简要）
```
website_crawler/
├─ main.py                  # FastAPI 应用入口，注册路由
├─ api/                     # API 路由层
│  ├─ cctv_news_api.py
│  ├─ ai_news_api.py
│  ├─ paper_news_api.py
│  ├─ gov_news_api.py
│  └─ assoc_chamber_api.py
├─ cctv_news/               # CCTV 新闻爬虫
├─ ai_news/                 # Aibase 每日 AI 资讯爬虫
├─ paper_news/              # 纸媒聚合抓取实现
├─ gov_news/                # 政府要闻爬虫（发改委/交通/商务）
├─ AssocChamber/            # 行业/商会（ACFIC/CFLP/ChinaISA）
├─ model/                   # 统一响应模型（Pydantic）
│  └─ response/
├─ utils/                   # HTTP/编码/工具函数
└─ test/                    # 端到端在线抓取测试（生成报告）
```


## 测试与报告
项目包含一个“在线抓取与记录”的测试，便于观察真实站点的抓取效果与失败原因：

- 运行：`pytest -q`
- 报告位置：`test/reports/`
  - Markdown 汇总：如 `real_crawl_report_YYYYMMDD_HHMMSS.md`
  - 原始 JSON：存放在 `test/reports/raw/`

说明：测试会对真实站点发起请求，受网络、站点结构变化、频率限制等影响，出现 `status=EMPTY/ERROR` 时请查看 `err_code/err_info` 与原始 JSON。


## 使用建议与注意事项
- 网络/代理
  - 默认不使用系统代理（utils 中 `get_html_from_url(no_proxy=True)`），若需要可自行扩展或在调用侧控制代理。
  - 部分站点对 HTTP/2、编码、重定向较敏感；已在实现中做常见容错（编码优先级、容器选择器兜底等）。
- 可选依赖
  - 商务部接口需要 Playwright；未安装时相关路由不可用或返回错误。
- 站点结构变更
  - 目标站点改版可能导致解析失败；欢迎根据出错信息定位选择器并调整相应爬虫模块。


## 免责声明
- 本项目仅用于技术研究与信息聚合演示，不对数据的时效性、完整性与准确性作任何保证。
- 请遵守目标站点的使用条款与 robots 约束，合理控制抓取频率与并发。

