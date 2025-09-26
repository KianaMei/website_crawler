# 纸媒独立插件模块

这个模块将原来的大型 `paper_news.py` 插件拆分为独立的纸媒插件，每个报纸都有自己的插件文件，可以独立运行。

## 📁 目录结构

```
plugins/paper_media/
├── __init__.py              # 模块初始化
├── base.py                  # 公共基础类和工具函数
├── aggregator.py            # 聚合插件（兼容原有接口）
├── peopledaily.py           # 人民日报独立插件
├── guangming.py             # 光明日报独立插件  
├── economic.py              # 经济日报独立插件
├── xinhua.py                # 新华每日电讯独立插件
├── jjckb.py                 # 经济参考报独立插件
├── qiushi.py                # 求是独立插件
├── test_plugins.py          # 插件测试脚本
└── README.md                # 本文档
```

## 🚀 使用方式

### 1. 使用单个插件

```python
from plugins.paper_media.peopledaily import handler, Metadata
from plugins.paper_media.base import Args

# 创建参数
args = Args({
    'max_items': 5,
    'date': '2024-09-25',  # 可选指定日期
    'since_days': 3
})

# 调用插件
result = handler(args)

if result.status == 'OK':
    for news in result.news_list:
        print(f"标题: {news.title}")
        print(f"链接: {news.url}")
        print(f"摘要: {news.summary[:100]}...")
        print("-" * 50)
```

### 2. 使用聚合插件

```python
from plugins.paper_media.aggregator import handler as agg_handler
from plugins.paper_media.base import Args

# 获取所有纸媒新闻
args = Args({
    'source': 'all',      # 或指定 'peopledaily', 'guangming' 等
    'max_items': 10,
    'date': None          # 自动选择最近可用日期
})

result = agg_handler(args)
```

## 📋 支持的报纸

| 插件文件 | 报纸名称 | 描述 |
|---------|---------|------|
| `peopledaily.py` | 人民日报 | 中国共产党中央委员会机关报 |
| `guangming.py` | 光明日报 | 中央主要新闻媒体 |
| `economic.py` | 经济日报 | 国务院主管的经济类日报 |
| `xinhua.py` | 新华每日电讯 | 新华社主办的综合性日报 |
| `jjckb.py` | 经济参考报 | 新华社主管的经济类报纸 |
| `qiushi.py` | 求是 | 中共中央主办的理论期刊 |

## 🔧 插件架构

### 基础组件 (`base.py`)

- **Args**: 模拟运行时参数类
- **News**: 新闻数据模型
- **PaperInput/PaperOutput**: 标准输入输出模型
- **fetch_url()**: 智能编码检测的URL抓取
- **find_available_date()**: 智能日期查找
- **safe_handler()**: 统一错误处理装饰器

### 插件规范

每个插件都遵循相同的结构：

1. **Metadata**: 插件元信息
2. **get_page_list()**: 获取版面列表
3. **get_title_list()**: 获取文章链接列表
4. **parse_article()**: 解析文章内容
5. **handler()**: 主处理函数

### 输入参数

```python
{
    'max_items': int,        # 最大抓取条数 (1-50)
    'date': str,             # 指定日期 'YYYY-MM-DD' (可选)
    'since_days': int        # 时间窗口天数 (1-365)
}
```

### 输出格式

```python
{
    'news_list': [           # 新闻列表
        {
            'title': str,    # 标题
            'url': str,      # 链接
            'origin': str,   # 来源报纸
            'summary': str,  # 摘要
            'publish_date': str  # 发布日期 'YYYY-MM-DD'
        }
    ],
    'status': str,           # 'OK' | 'EMPTY' | 'ERROR'
    'err_code': str,         # 错误码 (可选)
    'err_info': str          # 错误信息 (可选)
}
```

## 🧪 测试

### 运行所有插件测试

```bash
cd /path/to/project
python -m plugins.paper_media.test_plugins
```

### 测试单个插件

```python
python test_single_plugin.py
```

## ⚡ 性能特点

1. **独立性**: 每个插件可单独使用，互不影响
2. **容错性**: 单个插件失败不影响其他插件
3. **智能编码**: 自动检测和处理各种编码
4. **重试机制**: 网络请求失败自动重试
5. **日期智能**: 自动查找可用的报纸日期

## 🔄 兼容性

- ✅ 完全兼容原有 `paper_news.py` 的功能
- ✅ 支持相同的输入输出格式
- ✅ 保持相同的错误处理方式
- ✅ 可以无缝替换原有插件

## 📝 开发指南

### 添加新报纸插件

1. 复制现有插件模板
2. 实现三个核心函数：
   - `get_page_list(year, month, day)`
   - `get_title_list(year, month, day, page_url)`
   - `parse_article(html)`
3. 使用 `@safe_handler()` 装饰器
4. 更新 `aggregator.py` 中的 `SOURCE_MAP`

### 调试技巧

- 使用 `fetch_url()` 统一抓取网页
- 利用 `find_available_date()` 处理日期问题
- 通过日志记录调试信息
- 测试时使用小的 `max_items` 值

## 🚨 注意事项

1. **网站结构变化**: 各报纸网站可能更新结构，需要及时适配
2. **访问频率**: 避免过于频繁的请求，建议加入适当延迟
3. **编码问题**: 使用 `fetch_url()` 可以自动处理大部分编码问题
4. **错误处理**: 使用 `safe_handler` 装饰器确保异常安全

## 📊 与原版对比

| 特性 | 原版 paper_news.py | 独立插件模块 |
|------|-------------------|-------------|
| 代码结构 | 单文件800+行 | 多文件模块化 |
| 可维护性 | 较难维护 | 易于维护 |
| 独立性 | 紧耦合 | 完全独立 |
| 测试性 | 难以单独测试 | 可独立测试 |
| 扩展性 | 需修改主文件 | 只需添加新插件 |
| 容错性 | 一个失败全部失败 | 独立容错 |

通过这种重构，我们获得了更好的代码组织、更强的可维护性和更高的开发效率！