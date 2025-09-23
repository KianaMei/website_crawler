import os
import json
from datetime import datetime
from typing import Any, Dict, List, Optional


def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def _format_news_items(items: Optional[List[Dict[str, Any]]], max_items: int = 10) -> str:
    if not items:
        return "- (no items)"
    lines: List[str] = []
    for i, n in enumerate(items[:max_items], start=1):
        title = n.get("title") or "(no title)"
        url = n.get("url") or ""
        origin = n.get("origin") or ""
        date = n.get("publish_date") or ""
        summary = (n.get("summary") or "").replace("\n", " ")
        summary = summary[:180] + ("..." if len(summary) > 180 else "")
        lines.append(f"- {i}. [{title}]({url}) · {origin} · {date}\n  - {summary}")
    return "\n".join(lines)


def write_markdown_section(report_path: str, title: str, payload: Dict[str, Any]) -> None:
    _ensure_dir(os.path.dirname(report_path))
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    def _fmt(v: Any) -> str:
        return "-" if v is None else str(v)
    section = [
        f"\n\n## {title}",
        f"- time: {ts}",
        f"- status: {_fmt(payload.get('status'))}",
        f"- err_code: {_fmt(payload.get('err_code'))}",
        f"- err_info: {_fmt(payload.get('err_info'))}",
        f"- count: {len(payload.get('news_list') or [])}",
        "",
        _format_news_items(payload.get("news_list"), max_items=10),
    ]
    # 继续以 UTF-8 追加（头部已写入 BOM），防止 Windows IDE 乱码
    with open(report_path, "a", encoding="utf-8") as f:
        f.write("\n".join(section))


def write_raw_json(out_dir: str, name: str, payload: Dict[str, Any]) -> None:
    _ensure_dir(out_dir)
    fp = os.path.join(out_dir, f"{name}.json")
    with open(fp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
