import os
import json
import time
import logging
import httpx
from urllib.parse import urlsplit, urlunsplit
from typing import List, Dict, Any, Optional
from app.config import settings

logger = logging.getLogger(__name__)

def resolve_llm_endpoint(base_url: str) -> str:
    """安全解析 LLM endpoint，保留 query 参数并规整 /chat/completions 路径"""
    p = urlsplit(base_url.strip())
    path = p.path.rstrip("/")
    if not path.endswith("/chat/completions"):
        path = f"{path}/chat/completions"
    return urlunsplit((p.scheme, p.netloc, path, p.query, p.fragment))

def clean_openai_base_url(url: str) -> str:
    """规整 OpenAI SDK base_url，移除结尾的 /chat/completions"""
    clean = url.strip().rstrip("/")
    if clean.endswith("/chat/completions"):
        clean = clean[:-len("/chat/completions")].rstrip("/")
    return clean

class LLMGatewayClient:
    """
    符合竞赛平台规范的官方 LLM Gateway 适配器。
    特性：
    1. 动态自适应读取运行时环境变量 (PLATFORM_* 优先于 CHALLENGE_*)；
    2. 严格携带 X-Session-ID 请求头，支撑平台全链路会话审计；
    3. 优先使用官方 OpenAI SDK 调用（以便 agenthack.interceptor 自动采集 agent.llm Span、用量与 Token），
       支持 response_format 不兼容时自愈剔除重试，并保底降级至原生 httpx。
    4. 纯轻量化低内存常驻。
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

        # 1. 优先使用 OpenAI SDK 调用（配合 agenthack 自动采集 agent.llm 实际任务 Trace 与 Token 计量）
        try:
            import openai
            clean_url = clean_openai_base_url(base_url)
            client = openai.OpenAI(
                base_url=clean_url,
                api_key=api_key,
                timeout=70.0,
                max_retries=1
            )
            create_kwargs: Dict[str, Any] = {
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "extra_headers": {"X-Session-ID": current_session}
            }
            if response_format:
                create_kwargs["response_format"] = response_format

            try:
                resp = client.chat.completions.create(**create_kwargs)
                content = resp.choices[0].message.content or ""
                return content
            except Exception as e_openai_call:
                # 若平台网关报 400 不支持 response_format，自动剔除重试
                if response_format and ("response_format" in str(e_openai_call).lower() or "400" in str(e_openai_call)):
                    create_kwargs.pop("response_format", None)
                    resp = client.chat.completions.create(**create_kwargs)
                    return resp.choices[0].message.content or ""
                raise e_openai_call
        except Exception as e_sdk:
            logger.warning(f"OpenAI SDK invocation fell back to httpx: {e_sdk}")

        # 2. 原生 httpx 降级调用保底
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
                elif resp.status_code == 400 and response_format:
                    # 剔除 response_format 重试
                    payload.pop("response_format", None)
                    resp = self.client.post(url, headers=headers, json=payload)
                    if resp.status_code == 200:
                        data = resp.json()
                        return data["choices"][0]["message"]["content"]
                    raise RuntimeError(f"LLM Gateway HTTP 400: {resp.text}")
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
