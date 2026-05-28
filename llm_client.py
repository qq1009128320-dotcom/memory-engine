"""
Shared LLM client — used by run_extraction.py and summary_tree.py.

Eliminates duplicated call_llm() functions.
"""
import httpx
from config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, LLM_MAX_TOKENS, LLM_TIMEOUT


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
) -> str:
    """Call DeepSeek LLM API and return response text.

    Args:
        prompt: User prompt
        system_prompt: System role instruction
        model: Override LLM_MODEL from config
        max_tokens: Override LLM_MAX_TOKENS from config
        temperature: Sampling temperature (0-1)
        timeout: Override LLM_TIMEOUT from config

    Returns:
        LLM response text

    Raises:
        LLMError: If API key missing or API call fails
    """
    if not LLM_API_KEY:
        raise LLMError("DEEPSEEK_API_KEY 未设置，请检查 .env 文件")

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
        return data["choices"][0]["message"]["content"].strip()
    except httpx.HTTPStatusError as e:
        raise LLMError(f"LLM API HTTP {e.response.status_code}: {e.response.text[:200]}") from e
    except httpx.RequestError as e:
        raise LLMError(f"LLM API request failed: {e}") from e
