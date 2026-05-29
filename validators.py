"""
MCP 工具参数校验
"""

import re
from typing import Any


class ValidationError(ValueError):
    pass


def validate_not_empty(value: str, name: str) -> str:
    """确保字符串不为空。"""
    if not value or not value.strip():
        raise ValidationError(f"{name} 不能为空")
    return value.strip()


def validate_length(value: str, name: str, max_len: int = 50000) -> str:
    """限制字符串长度，超长自动截断。"""
    if len(value) > max_len:
        return value[:max_len]
    return value


def validate_safe_text(value: str, name: str) -> str:
    """过滤特殊字符，防止注入和破坏。"""
    # 移除 NULL 字节和不可打印控制字符（保留换行和制表符）
    # P1-3: 扩展控制字符范围，包含 DEL 和 C1 控制字符
    cleaned = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]', '', value)
    # 过滤 Unicode 零宽字符（U+200B-U+200D, U+FEFF）
    cleaned = re.sub(r'[\u200b-\u200d\uFEFF]', '', cleaned)
    if cleaned != value:
        raise ValidationError(f"{name} 包含非法控制字符")
    return cleaned


def validate_enum(value: str, name: str, allowed: list[str]) -> str:
    """确保值在允许范围内。"""
    if value not in allowed:
        raise ValidationError(f"{name} 必须在 {allowed} 中，收到: {value!r}")
    return value


def validate_int_range(value: int, name: str, min_val: int = 1, max_val: int = 100) -> int:
    """限制整数范围。"""
    if value < min_val or value > max_val:
        raise ValidationError(f"{name} 必须在 {min_val}-{max_val} 之间，收到: {value}")
    return value


def validate_scope(value: str) -> str:
    """验证 scope 参数格式（P3-1: 完整文档注释）。
    
    支持的格式：
    - personal: 个人级别（默认）
    - team: 团队级别
    - team:<name>: 特定团队（如 team:finance）
    - organization: 组织级别
    
    示例：
        validate_scope("personal")  # → "personal"
        validate_scope("team:finance")  # → "team:finance"
        validate_scope("invalid")  # → ValidationError
    
    Args:
        value: scope 字符串值
        
    Returns:
        验证后的 scope 字符串
        
    Raises:
        ValidationError: 格式无效时抛出
    """
    if value in ALLOWED_SCOPES:
        return value
    if value.startswith("team:"):
        return value
    raise ValidationError(f"scope 格式无效: {value!r}，允许: {ALLOWED_SCOPES} 或 'team:<部门>'")


def validate_coerce_int(value: Any, name: str, default: int = 0) -> int:
    """尝试将输入转为整数，失败返回默认值。"""
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


# 预定义允许值
ALLOWED_CATEGORIES     = ["field_alias", "date_rule", "naming", "policy", "format"]
ALLOWED_SEVERITIES     = ["minor", "major", "critical"]
ALLOWED_ERROR_CATEGORIES = ["field_selection", "logic_error", "scope_error", "omission"]
ALLOWED_ENTITY_TYPES   = ["person", "department", "client", "policy", "document", "field", "project"]
ALLOWED_SCOPES         = ["personal", "team", "organization"]
ALLOWED_RELATIONS      = ["belongs_to", "manages", "alias_of", "depends_on", "owns", "approves", "works_in"]
# 新增 auto_fetch / feishu，兼容飞书同步场景
ALLOWED_SOURCE_TYPES = ["manual", "extracted", "corrected", "auto_fetch", "feishu",
                        "feishu:doc", "feishu:base", "doc", "table", "file"]
