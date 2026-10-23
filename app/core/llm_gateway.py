import os
import json
import time
import httpx
from urllib.parse import urlsplit, urlunsplit
from typing import List, Dict, Any, Optional
from app.config import settings

def resolve_llm_endpoint(base_url: str) -> str:
    """安全解析 LLM endpoint，保留 query 参数并规整 /chat/completions 路径"""
    p = urlsplit(base_url.strip())
    path = p.path.rstrip("/")
    if not path.endswith("/chat/completions"):
        path = f"{path}/chat/completions"
    return urlunsplit((p.scheme, p.netloc, path, p.query, p.fragment))

class LLMGatewayClient:
    """
    符合竞赛平台规范的官方 LLM Gateway 适配器。
    特性：
    1. 动态自适应读取运行时环境变量 (PLATFORM_* 优先于 CHALLENGE_*)；
    2. 严格携带 X-Session-ID 请求头，支撑平台全链路会话审计；
    3. 支持指数退避重试（针对 429 与 5xx 异常）；
    4. 纯轻量化 httpx 实现，低内存常驻。
    """
    def __init__(self):
        self.client = httpx.Client(
            timeout=httpx.Timeout(connect=10.0, read=70.0, write=10.0, pool=10.0),
            limits=httpx.Limits(max_keepalive_connections=5, max_connections=10)
        )

    def chat_completion(
        self,
        messages: List[Dict[str, str]],
        session_id: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
        response_format: Optional[Dict[str, str]] = None
    ) -> str:
        current_session = (
            session_id
            or os.environ.get("PLATFORM_SESSION_ID")
            or os.environ.get("CHALLENGE_SESSION_ID")
            or getattr(settings, "effective_session_id", "default_session")
        )
        base_url = (
            os.environ.get("PLATFORM_LLM_URL")
            or getattr(settings, "effective_llm_base_url", "https://api.deepseek.com/v1")
        )
        api_key = (
            os.environ.get("PLATFORM_API_KEY")
            or getattr(settings, "effective_llm_api_key", "EMPTY")
        )
        model = (
            os.environ.get("PLATFORM_LLM_MODEL")
            or getattr(settings, "effective_llm_model", "deepseek-chat")
        )
        url = resolve_llm_endpoint(base_url)
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "X-Session-ID": current_session
        }
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens
        }
        if response_format:
            payload["response_format"] = response_format

        max_retries = 2
        backoff = 1.5
        for attempt in range(max_retries):
            try:
                resp = self.client.post(url, headers=headers, json=payload)
                if resp.status_code == 200:
                    data = resp.json()
                    return data["choices"][0]["message"]["content"]
                elif resp.status_code in [429, 500, 502, 503, 504]:
                    time.sleep(backoff ** attempt)
                    continue
                else:
                    raise RuntimeError(f"LLM Gateway HTTP {resp.status_code}: {resp.text}")
            except (httpx.RequestError, httpx.TimeoutException) as e:
                if attempt == max_retries - 1:
                    raise RuntimeError(f"LLM Gateway Connection Failed after retries: {str(e)}")
                time.sleep(backoff ** attempt)

        raise RuntimeError("LLM Gateway Max Retries Exceeded")
