"""
Shared LLM client — used by run_extraction.py and summary_tree.py.

Eliminates duplicated call_llm() functions.

P2-5 修复: 添加自动重试机制，指数退避。
P1-⑩ 修复: 添加 Jitter（随机抖动）避免惊群效应。
P1-⑪ 修复: 限制响应体大小，防止内存爆炸。
"""
import httpx
import time
import random
import logging
from config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, LLM_MAX_TOKENS, LLM_TIMEOUT

logger = logging.getLogger("memory_engine.llm_client")

# P1-⑪: 响应体最大长度限制（防止超大响应占用过多内存）
_MAX_RESPONSE_LENGTH = 50000


class LLMError(RuntimeError):
    """Raised when LLM API call fails."""
    pass


def call_llm(
    prompt: str,
    *,
    system_prompt: str = "你是一个精确的AI助手。",
    model: str | None = None,
    max_tokens: int | None = None,
    temperature: float = 0.3,
    timeout: int | None = None,
    max_retries: int = 3,
    retry_delay: float = 1.0,
    max_response_length: int = _MAX_RESPONSE_LENGTH,
) -> str:
    """Call DeepSeek LLM API and return response text.

    Args:
        prompt: User prompt
        system_prompt: System role instruction
        model: Override LLM_MODEL from config
        max_tokens: Override LLM_MAX_TOKENS from config
        temperature: Sampling temperature (0-1)
        timeout: Override LLM_TIMEOUT from config
        max_retries: Maximum retry attempts (default 3)
        retry_delay: Base delay between retries in seconds (default 1.0)
        max_response_length: Maximum response length in characters (default 50000)

    Returns:
        LLM response text (truncated if exceeds max_response_length)

    Raises:
        LLMError: If API key missing or API call fails after all retries
    """
    if not LLM_API_KEY:
        raise LLMError("DEEPSEEK_API_KEY 未设置，请检查 .env 文件")

    last_exc = None
    for attempt in range(max_retries):
        try:
            response = httpx.post(
                f"{LLM_BASE_URL}/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {LLM_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model or LLM_MODEL,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": temperature,
                    "max_tokens": max_tokens or LLM_MAX_TOKENS,
                },
                timeout=timeout or LLM_TIMEOUT,
            )
            response.raise_for_status()
            data = response.json()
            content = data["choices"][0]["message"]["content"].strip()
            # P1-⑪: 限制响应长度
            if len(content) > max_response_length:
                logger.warning(
                    "LLM response truncated from %d to %d chars",
                    len(content), max_response_length
                )
                content = content[:max_response_length]
            return content
        except httpx.HTTPStatusError as e:
            last_exc = e
            # 5xx 错误可重试，4xx 错误（除 429）不可重试
            if e.response.status_code >= 500 or e.response.status_code == 429:
                if attempt < max_retries - 1:
                    # P1-⑩ 修复: 添加 Jitter（随机抖动 0-1s）避免惊群效应
                    jitter = random.uniform(0, 1)
                    delay = retry_delay * (2 ** attempt) + jitter
                    logger.warning(
                        "LLM API HTTP %d, retry %d/%d in %.1fs: %s",
                        e.response.status_code, attempt + 1, max_retries, delay,
                        e.response.text[:100] if e.response.text else str(e),
                    )
                    time.sleep(delay)
                continue
            raise LLMError(f"LLM API HTTP {e.response.status_code}: {e.response.text[:200]}") from e
        except httpx.RequestError as e:
            last_exc = e
            if attempt < max_retries - 1:
                # P1-⑩ 修复: 添加 Jitter
                jitter = random.uniform(0, 1)
                delay = retry_delay * (2 ** attempt) + jitter
                logger.warning(
                    "LLM API request failed, retry %d/%d in %.1fs: %s",
                    attempt + 1, max_retries, delay, str(e),
                )
                time.sleep(delay)
            continue

    raise LLMError(f"LLM API call failed after {max_retries} retries: {last_exc}") from last_exc
