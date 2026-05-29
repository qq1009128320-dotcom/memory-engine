"""
记忆引擎 — 共享工具函数（P2-9: 提取重复函数到统一模块）

避免在多个文件中重复实现相同函数：
- _now(): 获取当前时间字符串
- _sha256(): 计算 SHA256 哈希
- parse_extraction_result(): 解析 LLM 提取结果
- _empty_result(): 返回空结果字典
"""
import hashlib
from datetime import datetime, timezone


def now() -> str:
    """获取当前 UTC 时间字符串（ISO 格式）。"""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def sha256(text: str) -> str:
    """计算文本的 SHA256 哈希值。"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def parse_extraction_result(text: str) -> dict:
    """解析 LLM 提取结果的文本，返回结构化字典。
    
    支持格式：
    - "客户: 腾讯, 部门: 云与智慧产业事业群"
    - "客户=腾讯; 部门=云与智慧产业事业群"
    - JSON 格式
    """
    import json
    import re
    
    text = text.strip()
    
    # 尝试解析 JSON
    if text.startswith("{"):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
    
    # 解析 "key: value" 或 "key=value" 格式
    result = {}
    # 匹配 "key: value" 或 "key=value"
    pattern = r'(\w+)\s*[:=]\s*([^,;]+)'
    matches = re.findall(pattern, text)
    for key, value in matches:
        result[key.strip()] = value.strip()
    
    return result if result else {"status": "empty"}


def empty_result() -> dict:
    """返回空结果字典（用于表示未找到数据）。"""
    return {"status": "empty", "message": "未找到相关数据"}
