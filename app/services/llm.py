"""OpenAI 兼容的模型调用。

用户 API Key 只作为函数参数在本进程内存中使用：
不写日志、不写数据库、不放进异常消息。
"""
from __future__ import annotations

import json
from collections.abc import Iterable, Iterator, Sequence
from urllib.parse import urlparse

import requests

from ..config import settings


class LLMError(Exception):
    """带用户可读中文信息的模型调用错误。"""

    def __init__(self, message: str, status: int = 0):
        super().__init__(message)
        self.message = message
        self.status = status


def normalize_base_url(value: str | None) -> str:
    url = (value or settings.llm_base_url).strip().rstrip("/")
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise LLMError("模型服务地址无效，请检查 Base URL")
    if parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise LLMError("出于安全考虑，远程模型服务必须使用 HTTPS")
    if url.endswith("/chat/completions"):
        url = url[: -len("/chat/completions")]
    return url


def validate_config(key: str, model: str) -> None:
    if not key or len(key) < 8 or len(key) > 300:
        raise LLMError("请填写有效的 API Key")
    if not model or len(model) > 120 or any(ch.isspace() for ch in model):
        raise LLMError("请填写有效的模型 ID")


def _headers(key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "User-Agent": settings.user_agent,
    }


def _endpoint(base_url: str | None) -> str:
    return f"{normalize_base_url(base_url)}/chat/completions"


def _map_status(status: int) -> str:
    if status == 401:
        return "API Key 无效或已过期"
    if status == 403:
        return "API Key 无权访问该模型"
    if status == 404:
        return "模型或接口地址不存在，请检查模型 ID 与 Base URL"
    if status == 429:
        return "请求过于频繁或额度不足，请稍后再试"
    if 500 <= status < 600:
        return "模型服务暂时不可用，请稍后再试"
    return f"模型服务返回错误（HTTP {status}）"


def _message_text(message: dict) -> str:
    """取出正文；推理模型（deepseek-r1 / qwen-thinking 等）只给 reasoning_content 时退回思考内容。

    这类模型如果只返回思考过程、content 为空，前端会看到「空回答」，
    所以这里明确兜底，并在两者都为空时给出可操作的报错。
    """
    for field in ("content", "reasoning_content", "reasoning"):
        value = message.get(field)
        if isinstance(value, list):  # 少数兼容层返回分段数组
            value = "".join(
                str(part.get("text", "")) if isinstance(part, dict) else str(part)
                for part in value
            )
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def chat(
    messages: Sequence[dict[str, str]],
    *,
    key: str,
    model: str,
    base_url: str | None = None,
    temperature: float = 0.2,
    timeout: int = 90,
    json_mode: bool = False,
    max_tokens: int | None = None,
) -> str:
    validate_config(key, model)
    payload: dict = {
        "model": model,
        "messages": list(messages),
        "temperature": temperature,
        "stream": False,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    if max_tokens:
        payload["max_tokens"] = max_tokens
    try:
        response = requests.post(
            _endpoint(base_url),
            headers=_headers(key),
            json=payload,
            timeout=timeout,
        )
    except requests.Timeout:
        raise LLMError("模型响应超时，请稍后重试或更换模型") from None
    except requests.RequestException:
        raise LLMError("无法连接模型服务，请检查网络与 Base URL") from None
    if response.status_code >= 400:
        raise LLMError(_map_status(response.status_code), response.status_code)
    try:
        data = response.json()
        message = data["choices"][0]["message"]
    except (ValueError, KeyError, IndexError, TypeError):
        raise LLMError("模型返回内容无法解析") from None
    content = _message_text(message if isinstance(message, dict) else {})
    if not content:
        raise LLMError(
            "模型返回了空内容：如果用的是推理模型（如 deepseek-reasoner），"
            "请换成普通对话模型（如 deepseek-chat、gpt-4.1-mini）后重试"
        )
    return content


def stream_chat(
    messages: Sequence[dict[str, str]],
    *,
    key: str,
    model: str,
    base_url: str | None = None,
    temperature: float = 0.2,
    timeout: int = 120,
) -> Iterator[str]:
    """逐段产出回答文本；上游异常会以 LLMError 抛出。"""
    validate_config(key, model)
    payload = {
        "model": model,
        "messages": list(messages),
        "temperature": temperature,
        "stream": True,
    }
    try:
        response = requests.post(
            _endpoint(base_url),
            headers={**_headers(key), "Accept": "text/event-stream"},
            json=payload,
            timeout=timeout,
            stream=True,
        )
    except requests.Timeout:
        raise LLMError("模型响应超时，请稍后重试") from None
    except requests.RequestException:
        raise LLMError("无法连接模型服务，请检查网络与 Base URL") from None
    if response.status_code >= 400:
        raise LLMError(_map_status(response.status_code), response.status_code)
    produced = False
    try:
        for raw in response.iter_lines(decode_unicode=False):
            if not raw:
                continue
            line = raw.decode("utf-8", "ignore").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                payload = json.loads(data)
            except json.JSONDecodeError:
                continue
            choices = payload.get("choices") or []
            if not choices:
                continue
            delta = choices[0].get("delta") or {}
            piece = delta.get("content")
            if isinstance(piece, str) and piece:
                produced = True
                yield piece
    except requests.RequestException:
        raise LLMError("模型连接中断，请重试") from None
    finally:
        response.close()
    if not produced:
        raise LLMError("模型没有返回内容，请更换模型或稍后重试")


def parse_json_object(text: str) -> dict:
    """从模型输出中稳健地截取 JSON 对象（用于审核/词汇等结构化任务）。"""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:]
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end <= start:
        raise LLMError("模型未按 JSON 格式返回内容")
    try:
        data = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError:
        raise LLMError("模型返回的 JSON 无法解析") from None
    if not isinstance(data, dict):
        raise LLMError("模型返回结构不正确")
    return data


def parse_json_array(text: str) -> list:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:]
    start = cleaned.find("[")
    end = cleaned.rfind("]")
    if start < 0 or end <= start:
        raise LLMError("模型未按 JSON 数组格式返回内容")
    try:
        data = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError:
        raise LLMError("模型返回的 JSON 无法解析") from None
    if not isinstance(data, list):
        raise LLMError("模型返回结构不正确")
    return data


def stream_pieces(text: str, size: int = 8) -> Iterable[str]:
    """把已生成文本切块，用于前端打字机效果。"""
    for i in range(0, len(text), size):
        yield text[i : i + size]
