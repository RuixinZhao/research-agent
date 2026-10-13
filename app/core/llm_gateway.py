import os
import json
import time
import httpx
from typing import List, Dict, Any, Optional
from app.config import settings

class LLMGatewayClient:
    """
    符合竞赛平台规范的官方 LLM Gateway 适配器。
    特性：
    1. 动态读取运行时环境变量；
    2. 严格携带 X-Session-ID 请求头；
    3. 支持指数退避重试（针对 429 与 5xx 异常）；
    4. 纯轻量化 httpx 实现，低内存常驻。
    """
    def __init__(self):
        self.base_url = settings.CHALLENGE_LLM_BASE_URL.rstrip("/")
        self.api_key = settings.CHALLENGE_LLM_API_KEY
        self.model = settings.CHALLENGE_LLM_MODEL
        self.default_session_id = settings.CHALLENGE_SESSION_ID
        
        self.client = httpx.Client(
            timeout=httpx.Timeout(connect=10.0, read=90.0, write=10.0, pool=10.0),
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
        current_session = session_id or self.default_session_id
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "X-Session-ID": current_session
        }
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens
        }
        if response_format:
            payload["response_format"] = response_format

        max_retries = 3
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
