import os
import json
import pytest
import httpx
from unittest.mock import patch
from fastapi.testclient import TestClient

from server import app, get_telemetry
from app.core.llm_gateway import LLMGatewayClient
from app.handlers.reproduction_handler import ReproductionHandler
from app.config import settings

client = TestClient(app)

def test_health_telemetry_configured():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data.get("status") == "healthy"
    assert data.get("telemetry_configured") is True

def test_llm_gateway_telemetry_span_emission():
    tel = get_telemetry()
    if not tel:
        pytest.skip("agenthack telemetry not available in this environment")

    # Mock Gateway response
    def mock_gw(request):
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-test-01",
                "object": "chat.completion",
                "model": "deepseek-chat",
                "choices": [{
                    "index": 0,
                    "message": {"role": "assistant", "content": "mocked answer"},
                    "finish_reason": "stop"
                }],
                "usage": {
                    "prompt_tokens": 120,
                    "completion_tokens": 60,
                    "total_tokens": 180
                }
            }
        )

    mock_transport = httpx.MockTransport(mock_gw)
    gw = LLMGatewayClient()
    gw.client = httpx.Client(transport=mock_transport)

    with tel.session(task_id="A-01", task_type="Chat", session_id="sess-llm-trace-01") as sess:
        assert sess.counters["llm_call_count"] == 0
        resp_text = gw.chat_completion(
            messages=[{"role": "user", "content": "test question"}],
            session_id="sess-llm-trace-01"
        )
        assert resp_text == "mocked answer"
        assert sess.counters["llm_call_count"] >= 1
        assert sess.counters["total_input_tokens"] >= 120
        assert sess.counters["total_output_tokens"] >= 60

def test_reproduction_llm_telemetry_span_emission(tmp_path, monkeypatch):
    tel = get_telemetry()
    if not tel:
        pytest.skip("agenthack telemetry not available in this environment")

    monkeypatch.setattr(settings, "WORKSPACE_OUTPUT", str(tmp_path))
    handler = ReproductionHandler()
    work_dir = tmp_path / "repro_work"
    work_dir.mkdir(parents=True, exist_ok=True)

    def mock_gw(request):
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-repro-01",
                "choices": [{
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": "```python\ndef run_experiment(request):\n    return {'status': 'completed'}\n```"
                    },
                    "finish_reason": "stop"
                }],
                "usage": {
                    "prompt_tokens": 200,
                    "completion_tokens": 100,
                    "total_tokens": 300
                }
            }
        )

    mock_transport = httpx.MockTransport(mock_gw)
    monkeypatch.setattr("httpx.Client.post", lambda self, url, **kwargs: mock_transport.handle_request(httpx.Request("POST", url, **kwargs)))

    with tel.session(task_id="D-01", task_type="Reproduction", session_id="sess-repro-trace-01") as sess:
        assert sess.counters["llm_call_count"] == 0
        res = handler._call_platform_llm("Generate exp", work_dir=work_dir, session_id="sess-repro-trace-01", timeout=60)
        assert res["choices"][0]["finish_reason"] == "stop"
        assert sess.counters["llm_call_count"] >= 1
        assert sess.counters["total_input_tokens"] >= 200

def test_server_solve_headers_and_trace_context(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "WORKSPACE_OUTPUT", str(tmp_path))
    monkeypatch.setenv("TEAM_ID", "team_trace_test")

    payload = {
        "case_id": "A-01",
        "function": "Chat",
        "title": "量子纠缠",
        "input": "请分析量子纠缠在量子密钥分发中的作用机理",
        "materials": [],
        "constraints": [],
        "expected_output": "",
        "output_schema_ref": "Chat"
    }

    mock_resp = json.dumps({
        "answer": "量子密钥分发基于量子不可克隆定理与纠缠态关联测量，能够实现无条件安全的对称密钥协商机制。",
        "clarifying_question": "请问本研究所拟采用的光学纠缠源保真度与信道衰减补偿范围如何限定？"
    }, ensure_ascii=False)

    with patch("app.core.llm_gateway.LLMGatewayClient.chat_completion", return_value=mock_resp):
        response = client.post(
            "/solve",
            json=payload,
            headers={
                "X-Session-ID": "test-trace-session",
                "traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
            }
        )

    assert response.status_code == 200
    data = response.json()
    assert data["case_id"] == "A-01"
    assert "answer" in data
    assert "clarifying_question" in data
    # 验证链路审计响应头
    if "X-Trace-ID" in response.headers:
        assert response.headers["X-Trace-ID"] == "4bf92f3577b34da6a3ce929d0e0e4736"
    if "X-Session-ID" in response.headers:
        assert response.headers["X-Session-ID"] == "test-trace-session"
