# 网站爬取聚合 API（website_crawler）

统一抓取多来源新闻并以一致的数据模型返回，基于 FastAPI 对外提供 HTTP 接口。覆盖来源：
- CCTV 新闻联播
- Aibase AI 每日简报
- 纸媒：人民日报/光明日报/经济日报/求是/新华每日电讯/经济参考报
- 政府部委：国家发改委、交通运输部、商务部
- 行业协会/商会：全国工商联（ACFIC）、中物联（CFLP）、ChinaISA 门户


## 快速开始
- 运行环境：Python ≥ 3.13（建议 3.11+/3.13）
- 安装依赖（任选其一）
  - pip
    - Windows PowerShell
      - `python -m venv .venv`
      - `.venv\\Scripts\\activate`
      - `python -m pip install -U pip`
      - `pip install .`
  - uv（可选，若已安装 uv）
    - `uv venv`
    - `uv pip install -e .`
- 运行服务
  - `uvicorn main:app --host 0.0.0.0 --port 8000 --reload`
  - 打开文档：`http://127.0.0.1:8000/docs`（Swagger）或 `http://127.0.0.1:8000/redoc`
- 可选依赖：若要使用"商务部"接口（需要动态渲染），请安装 Playwright：
  - `pip install playwright`
  - `python -m playwright install chromium`


## 统一响应模型
所有接口返回统一的 NewsResponse：

```json
{
  "status": "OK | EMPTY | ERROR",
  "news_list": [
    {
      "title": "标题",
      "url": "详情页链接",
      "origin": "来源（站点/栏目）",
      "summary": "简要内容（适当截断）",
      "publish_date": "YYYY-MM-DD"
    }
=======
# Website Crawler · 站点抓取聚合服务

基于 FastAPI 的新闻抓取聚合服务，统一输出结构化 JSON，包含：
- 央视新闻联播每日新闻
- Aibase 每日 AI 新闻
- 报纸新闻（人民日报/光明日报/经济日报/求是/新华每日电讯/经济参考报）
- 政务新闻（国家发改委栏目）

提供统一的数据模型（Pydantic）与 REST API，并附架构示意图（`docs/diagrams/index.html`）。

## 更新亮点（近期）
- 新增报纸源：新华每日电讯（mrdx.cn）、经济参考报（dz.jjckb.cn）
- 工商联（AssocChamber）完善：新增"解读"频道（jd），API 文案中文化，并统一返回结构
- CFLP（中国物流与采购联合会）：合并"大宗商品"为资讯子栏目；新增 since_days 近 N 天过滤与分页提前停止；详情日期兜底；资讯类降权排序
- 新增中国钢铁工业协会（ChinaISA）爬虫：统一 AJAX 接口模拟、支持"统计发布/行业分析/价格指数"三大类的子栏目递归抓取；新增精简路由 `/api/chinaisa/news`、`/api/chinaisa/sections`

## 目录结构（当前）
```
website_crawler/
├─ main.py                  # FastAPI 应用入口，注册路由
├─ api/                     # API 路由
│  ├─ cctv_news_api.py
│  ├─ ai_news_api.py
│  ├─ paper_news_api.py
│  ├─ gov_news_api.py
│  └─ assoc_chamber_api.py  # 工商联/协会（ACFIC、CFLP、ChinaISA）
├─ cctv_news/               # 央视新闻爬虫
├─ ai_news/                 # Aibase 每日 AI 爬虫
├─ paper_news/              # 报纸新闻聚合与来源适配
├─ gov_news/                # 政务新闻（发改委等）
├─ AssocChamber/            # 行业/协会：
│  ├─ acfic_policy_crawler.py   # 全联政策
│  ├─ cflp_crawler.py           # 物流与采购联合会
│  └─ chinaisa_crawler.py       # 中国钢铁工业协会（含子栏目）
├─ model/                   # 统一响应模型（Pydantic）
│  └─ response/
└─ utils/                   # HTTP/UA 等工具
```

## 环境要求
- Python 3.10+（开发环境 3.12/3.13 均可）
- Windows/macOS/Linux

## 安装与运行
1) 虚拟环境
```
python -m venv .venv
# Windows PowerShell
. .venv/Scripts/Activate.ps1
python -m pip install --upgrade pip
```

2) 使用 uv 同步依赖（推荐，已在 pyproject.toml 声明）
```
pip install uv
uv sync
```

3) 启动服务
```
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

4) 打开接口文档
- Swagger UI: http://127.0.0.1:8000/docs
- ReDoc: http://127.0.0.1:8000/redoc

## 统一返回模型
```
NewsResponse {
  status: "OK" | "ERROR" | "EMPTY",
  err_code: string | null,
  err_info: string | null,
  news_list: [
    {
      title: string,
      url: string,
      origin: string,
      summary: string,
      publish_date: "YYYY-MM-DD"
    }, ...
  ] | null
}
```

## API 一览与规范（统一返回 NewsResponse）

- GET `/api/get_daily_cctv_news`
  - 用途：获取《新闻联播》（前一日）
  - 入参：无
  - 返回：NewsResponse（示例）
```
{
  "status": "OK",
  "news_list": [
    {"title":"我国取得重大科技突破","url":"https://tv.cctv.com/...","origin":"新闻联播","summary":"摘要……","publish_date":"2025-09-18"}
>>>>>>> 129ab969faef3e50a363b109c271382f7fe42f70
  ],
  "err_code": null,
  "err_info": null
}
```
<<<<<<< HEAD
- status：OK 有数据；EMPTY 已成功但无数据；ERROR 出错（查看 err_code/err_info）
- 数据模型定义：`model/response/news.py:1`，`model/response/news_response.py:1`


## 路由前缀与文档
- 所有接口均带统一前缀：`/api`
- 交互式文档内已分组展示：CCTV/AI/纸媒/政府/行业协会


## 接口清单与参数

### 1) AI 每日简报
- 路径：`GET /api/get_daily_ai_news`
- 入参：无
- 出参：NewsResponse（Aibase 当日要闻聚合，publish_date=当天）
- 代码：`api/ai_news_api.py:1`

### 2) CCTV 新闻联播摘要
- 路径：`GET /api/get_daily_cctv_news`
- 入参：无
- 出参：NewsResponse（取前一日联播各条新闻，publish_date=昨天）
- 代码：`api/cctv_news_api.py:1`

### 3) 纸媒新闻（多来源汇总）
- 路径：`GET /api/get_daily_paper_news`
- 入参（Query）：
  - `source`：纸媒来源，默认 `peopledaily`
    - 可选：`peopledaily | guangming | economic | qiushi | xinhua | jjckb`
  - `max_items`：返回数量上限，默认 `10`，范围 1–50
  - `date`：特定日期 `YYYY-MM-DD`，不传则自动寻找最近一期
- 出参：NewsResponse（每条为对应报刊的单篇文章）
- 代码：`api/paper_news_api.py:1`，聚合实现 `paper_news/paper_news_crawler.py:1`

### 4) 国家发改委（政策类聚合）
- 路径：`GET /api/get_daily_ndrc_news`
- 入参（Query）：
  - `categories`：多选参数，默认 `fzggwl`。支持 CSV 与重复参数写法，可选：
    - `fzggwl` 发展改革委（综合）
    - `ghxwj` 规范性文件
    - `ghwb` 规划文本
    - `gg` 公告
    - `tz` 通知
  - `max_pages`：翻页深度（1–10，默认 1）
  - `max_items`：条数上限（1–100，默认 10）
- 出参：NewsResponse（origin 对应栏目名；summary 为正文摘要）
- 代码：`api/gov_news_api.py:1`，爬虫 `gov_news/ndrc_news_crawler.py:1`

### 5) 交通运输部（要闻）
- 路径：`GET /api/get_transport_gov_news`
- 入参：无
- 出参：NewsResponse（近两日要闻）
- 代码：`api/gov_news_api.py:1`，爬虫 `gov_news/transport_news_crawler.py:1`

### 6) 商务部（领导/部领导活动）
- 路径：`GET /api/get_commerce_gov_news`
- 入参：无
- 出参：NewsResponse（近几日领导/部领导活动）
- 说明：依赖 Playwright 动态渲染，请安装"可选依赖"章节所述组件
- 代码：`api/gov_news_api.py:1`，爬虫 `gov_news/commerce_news_crawler.py:1`

### 7) 全联 ACFIC（政策信息）
- 路径：`GET /api/get_acfic_policies`
- 入参（Query）：
  - `channels`：多选参数，默认 `zy,bw,df,qggsl,jd`。支持 CSV 与重复参数写法，可选：
    - `zy` 中央
    - `bw` 部委
    - `df` 地方
    - `qggsl` 全联自有
    - `jd` 解读
  - `max_pages`：翻页深度（1–10，默认 1）
  - `max_items`：条数上限（1–100，默认 5）
- 出参：NewsResponse（origin 已在 API 层本地化为中文）
- 代码：`api/assoc_chamber_api.py:1`，爬虫 `AssocChamber/acfic_policy_crawler.py:1`

### 8) 中物联 CFLP（政策/资讯）
- 路径：`GET /api/get_cflp_news`
- 入参（Query）：
  - `channels`：多选参数，默认 `zcfg,zixun`。支持 CSV 与重复参数写法，可选：
    - `zcfg` 政策法规
    - `zixun` 资讯（兼容 `dzsp` → `zixun`）
  - `max_pages`：翻页深度（1–10，默认 1）
  - `max_items`：上限（1–100，默认 8）
  - `since_days`：仅取近 N 天的数据（1–60，默认 7）
- 出参：NewsResponse（资讯会按类别降权与日期排序；政策保持列表顺序）
- 代码：`api/assoc_chamber_api.py:1`，爬虫 `AssocChamber/cflp_crawler.py:1`

### 9) ChinaISA 报栏抓取
- 路径：`GET /api/chinaisa/news`
- 入参（Query）：
  - `columns`：columnId 的 CSV；不传则使用内置的 8 个常用栏目
  - `page`：页码，默认 1（1–50）
  - `size`：每页条数，默认 20（1–100）
  - `max`：总条数上限，默认 60（1–1000）
  - `since_days`：仅取近 N 天（可选，1–60）
  - `max_pages`：最大翻页数，默认 3（1–10）
  - `include_subtabs`：是否包含子页（默认 true，如统计分析/企业信息/价格指数等）
- 出参：NewsResponse
- 获取可用栏目与分组：见下一个接口 `/api/chinaisa/sections`
- 代码：`api/assoc_chamber_api.py:1`，爬虫 `AssocChamber/chinaisa_crawler.py:1`

### 10) ChinaISA 栏目结构
- 路径：`GET /api/chinaisa/sections`
- 入参（Query）：
  - `include_subtabs`：是否包含子页（默认 true）
- 出参：
  - `{ "sections": { <columnId>: {"name": 名称, ...}, ... }, "groups": [ {"id": <重要分组 id>, "name": 名称, ...}, ... ] }`
- 用法：先调用本接口确认 `columns` 可选值，再调用 `/api/chinaisa/news`
- 代码：`api/assoc_chamber_api.py:1`


## 调用示例

### 多选参数使用说明
部分接口支持 **CSV 与重复参数** 两种多选写法：
- CSV 写法：`categories=ghxwj,gg`
- 重复参数：`categories=ghxwj&categories=gg`
- 两种写法可以混用：`categories=ghxwj&categories=gg,tz`

### 具体接口示例
- 获取 Aibase 当日简报
  - `curl "http://127.0.0.1:8000/api/get_daily_ai_news"`
- 获取人民日报（最近一期）最多 5 条
  - `curl "http://127.0.0.1:8000/api/get_daily_paper_news?source=peopledaily&max_items=5"`

### 发改委（NDRC）示例
- CSV 写法：获取"规范性文件+公告"，翻页 2 页，共计最多 20 条
  - `curl "http://127.0.0.1:8000/api/get_daily_ndrc_news?categories=ghxwj,gg&max_pages=2&max_items=20"`
- 重复参数：获取"规范性文件+公告+通知"，翻页 3 页
  - `curl "http://127.0.0.1:8000/api/get_daily_ndrc_news?categories=ghxwj&categories=gg&categories=tz&max_pages=3&max_items=30"`

### 全联（ACFIC）示例
- CSV 写法：获取"中央+部委+地方"政策信息
  - `curl "http://127.0.0.1:8000/api/get_acfic_policies?channels=zy,bw,df&max_items=10"`
- 重复参数：获取"全联自有+解读"政策信息
  - `curl "http://127.0.0.1:8000/api/get_acfic_policies?channels=qggsl&channels=jd&max_items=8"`

### 中物联（CFLP）示例
- CSV 写法：获取"政策法规+资讯"，近 7 天最多 8 条
  - `curl "http://127.0.0.1:8000/api/get_cflp_news?channels=zcfg,zixun&since_days=7&max_items=8"`
- 重复参数：仅获取"资讯"（兼容 dzsp 映射）
  - `curl "http://127.0.0.1:8000/api/get_cflp_news?channels=zixun&since_days=7&max_items=8"`
- 兼容写法：使用 dzsp（会自动映射为 zixun）
  - `curl "http://127.0.0.1:8000/api/get_cflp_news?channels=dzsp&since_days=7&max_items=8"`


## 错误与边界
- 站点结构变化或临时不可达会导致 `status=ERROR/EMPTY`，请查看 `err_code/err_info`
- 频率建议：尊重对方站点的 robots 与访问负载，避免高并发抓取
- 网络/代理：默认不走系统代理（`utils.get_html_from_url(no_proxy=True)`），如需代理请自行扩展
- 编码：对常见的 `gbk/gb2312/gb18030/utf-8` 已做自动检测与兼容


## 开发说明
- 入口：`main.py:1`（注册路由、启用 OpenAPI 文档）
- 路由聚合：`api/__init__.py:1`
- 工具：`utils/tool.py:1`（请求、编码、拼接等）
- 模型：`model/response/*.py`
- 依赖声明：`pyproject.toml:1`（如使用商务部接口，请另外安装 Playwright）


## 许可与致谢
- 仅用于技术研究与信息聚合，严禁用于任何违反对方站点使用条款的行为
- 内容版权归原作者/网站所有
=======

- GET `/api/get_daily_ai_news`
  - 用途：获取 AI 新闻（当天）
  - 入参：无
  - 返回：NewsResponse（示例）
```
{
  "status":"OK",
  "news_list":[
    {"title":"大模型落地应用进展","url":"https://news.aibase.com/zh/daily/...","origin":"Aibase 每日 AI","summary":"摘要……","publish_date":"2025-09-19"}
  ],
  "err_code":null,
  "err_info":null
}
```

- GET `/api/get_daily_paper_news`
  - 用途：获取报纸新闻（可指定日期）
  - 入参：
    - `source`: `peopledaily|guangming|economic|qiushi|xinhua|jjckb`（默认 `peopledaily`）
    - `max_items`: 1–50（默认 10）
    - `date`: `YYYY-MM-DD`（可选，不填自动选择最近一期）
  - 返回：NewsResponse（示例）
```
{
  "status":"OK",
  "news_list":[
    {"title":"高质量发展迈出新步伐","url":"http://paper.people.com.cn/...","origin":"人民日报","summary":"摘要……","publish_date":"2025-09-19"}
  ],
  "err_code":null,
  "err_info":null
}
```

- GET `/api/get_daily_ndrc_news`
  - 用途：获取国家发改委栏目（可选分类）
  - 入参：
    - `categories`: `fzggwl,ghxwj,ghwb,gg,tz`（CSV，多选）
    - `max_pages`: 1–10（默认 1）
    - `max_items`: 1–100（默认 10）
  - 返回：NewsResponse（示例）
```
{
  "status":"OK",
  "news_list":[
    {"title":"关于印发有关文件的通知","url":"https://www.ndrc.gov.cn/...","origin":"规范性文件","summary":"摘要……","publish_date":"2025-09-18"}
  ],
  "err_code":null,
  "err_info":null
}
```

- GET `/api/get_acfic_policies`
  - 用途：全联政策聚合（中央/部委/地方/全联/解读）
  - 入参：
    - `channels`: `zy,bw,df,qggsl,jd`（CSV，默认全选）
    - `max_pages`: 1–10（默认 1）
    - `max_items`: 1–100（默认 5）
  - 返回：NewsResponse（示例）
```
{
  "status":"OK",
  "news_list":[
    {"title":"关于…的通知","url":"https://www.acfic.org.cn/...","origin":"全联-中央","summary":"摘要……","publish_date":"2025-09-16"}
  ],
  "err_code":null,
  "err_info":null
}
```

- GET `/api/get_cflp_news`
  - 用途：中国物流与采购联合会（政策/资讯）
  - 入参：
    - `channels`: `zcfg,zixun`（CSV，默认 `zcfg,zixun`）
    - `max_pages`: 1–10（默认 1）
    - `max_items`: 1–100（默认 8）
    - `since_days`: 1–60（默认 7；近 N 天并用于分页提前停止）
  - 返回：NewsResponse（示例）
```
{
  "status":"OK",
  "news_list":[
    {"title":"行业热点资讯…","url":"http://www.chinawuliu.com.cn/zixun/...","origin":"中国物流与采购联合会-资讯","summary":"摘要……","publish_date":"2025-09-19"}
  ],
  "err_code":null,
  "err_info":null
}
```

### ChinaISA（中国钢铁工业协会）

- GET `/api/chinaisa/news`
  - 用途：抓取指定栏目或默认 8 个栏目；支持递归抓取"统计发布/行业分析/价格指数"的子栏目
  - 入参：
    - `columns`: 栏目 ID（CSV）。如不传则抓取默认 8 个主栏目。
    - `page`: 页号（默认 1）
    - `size`: 每页条数（默认 20，1–100）
    - `max`: 返回上限（默认 60）
    - `since_days`: 近 N 天（可选）
    - `max_pages`: 最大翻页（默认 3）
    - `include_subtabs`: 是否包含子栏目（默认 true，仅对统计发布/行业分析/价格指数生效）
  - 说明：不要在文档硬编码栏目 ID，请先调用 `/api/chinaisa/sections` 获取实时映射，然后将其中的 ID 传给本接口。
  - 返回：NewsResponse

- GET `/api/chinaisa/sections`
  - 用途：返回主栏目 → 子栏目结构
  - 入参：
    - `include_subtabs`: 是否进行实时发现（默认 true）
  - 返回字段：
    - `sections`: 所有主栏目，含 `name`、`baseline_subtabs`（固化）与 `subtabs`（实时）及 `added/missing`
    - `groups`: 仅包含三大主类（统计发布/行业分析/价格指数）的相同结构，便于前端渲染
  - 注意：本 README 不展示任何实际栏目 ID，避免失效或误用。请以接口返回为准。



## 设计与实现要点
- 解析：BeautifulSoup + 针对性选择器，尽量稳健；必要时后备方案
- HTTP：自定义 UA、超时与重试；可禁用系统代理并开启证书校验，避免被本机代理劫持
- 统一模型：所有来源统一映射到 News/NewsResponse
- 校验与快照：`gov_news/snapshots` 提供本地快照用于人工核验

## 常见问题（FAQ）
- Q: 返回为空/站点变动导致解析失败？
  - A: 先缩小 `max_pages`/`max_items` 重试，必要时调整解析选择器。
- Q: 如何指定报纸日期？
  - A: `/api/get_daily_paper_news` 提供 `date=YYYY-MM-DD` 参数；若该期缺页会自动在最近 7 天内回退。
- Q: 发改委栏目如何多选？
  - A: `categories` 以逗号分隔传入，如 `ghxwj,gg`。

## 许可与合规
- 本项目仅用于学习与研究，请遵守目标站点 robots 与访问频率限制。
>>>>>>> 129ab969faef3e50a363b109c271382f7fe42f70