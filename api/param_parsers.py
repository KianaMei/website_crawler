from typing import List, Optional, Dict, Any
from fastapi import HTTPException, Query
from model.enums import NDRCCategory, ACFICChannel, CFLPChannel


def parse_multi_select(
    values: Optional[List[str]],
    enum_cls: type,
    param_name: str,
    default_list: List[str],
    alias_map: Optional[Dict[str, str]] = None,
) -> List[str]:
    """
    解析多选参数，支持 CSV 与重复参数混合使用。

    Args:
        values: FastAPI 解析的查询参数列表（可能为 None 或 []）
        enum_cls: 枚举类（NDRCCategory/ACFICChannel/CFLPChannel）
        param_name: 参数名，用于错误信息
        default_list: 默认值列表
        alias_map: 别名映射（如 dzsp -> zixun）

    Returns:
        合法的字符串值列表

    Raises:
        HTTPException(400): 非法值时抛出，包含允许值与示例
    """
    # 1. 处理空值：返回默认值
    if not values:
        return default_list

    # 2. 合并所有值（FastAPI 已处理重复参数为列表）
    combined_values: List[str] = []
    for val in values:
        if not val:
            continue
        # 支持 CSV 格式：按逗号分隔并去空格
        for item in val.split(','):
            stripped = item.strip()
            if stripped:
                combined_values.append(stripped)

    # 3. 去重（保留顺序）
    seen = set()
    unique_values = []
    for val in combined_values:
        if val not in seen:
            seen.add(val)
            unique_values.append(val)

    # 4. 应用别名映射
    if alias_map:
        mapped_values = []
        for val in unique_values:
            mapped_val = alias_map.get(val, val)
            if mapped_val not in mapped_values:
                mapped_values.append(mapped_val)
        unique_values = mapped_values

    # 5. 校验枚举值
    valid_values = [e.value for e in enum_cls]
    invalid_values = [val for val in unique_values if val not in valid_values]

    if invalid_values:
        raise HTTPException(
            status_code=400,
            detail=(
                f"参数 {param_name} 存在非法值: {', '.join(invalid_values)}。 "
                f"允许取值: {', '.join(sorted(valid_values))}。 "
                f"示例: {param_name}={'&'.join(param_name + '=' + v for v in default_list[:2])} "
                f"或 {param_name}={','.join(default_list[:2])}"
            )
        )

    # 6. 返回校验后的值列表（为空时用默认值）
    return unique_values if unique_values else default_list