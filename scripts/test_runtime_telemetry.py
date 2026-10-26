import sys
import os
import json
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx
from server import app, get_telemetry
from app.core.llm_gateway import LLMGatewayClient
from app.handlers.reproduction_handler import ReproductionHandler

tel = get_telemetry()
print("Telemetry instance:", tel)
print("Telemetry export_enabled:", tel.export_enabled if tel else None)
assert tel is not None, "Telemetry must be initialized!"

# 1. Test LLMGatewayClient with OpenAI SDK
gw = LLMGatewayClient()

with tel.session(task_id="A-01", task_type="Chat", session_id="sess-llm-trace-01") as sess:
    assert sess.counters["llm_call_count"] == 0
    resp_text = gw.chat_completion(
        messages=[{"role": "user", "content": "test question"}],
        session_id="sess-llm-trace-01"
    )
    print("Response text:", resp_text[:60] + "...")
    print("Session counters after chat_completion:", sess.counters)
    assert len(resp_text) > 0
    assert sess.counters["llm_call_count"] >= 1
    assert sess.counters["total_input_tokens"] > 0
    assert sess.counters["total_output_tokens"] > 0

# 2. Test LLMGatewayClient with httpx fallback
def mock_gw(request):
    return httpx.Response(
        200,
        json={
            "id": "chatcmpl-test-fallback",
            "object": "chat.completion",
            "model": "deepseek-chat",
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": "mocked fallback answer"},
                "finish_reason": "stop"
            }],
            "usage": {
                "prompt_tokens": 150,
                "completion_tokens": 75,
                "total_tokens": 225
            }
        }
    )

mock_transport = httpx.MockTransport(mock_gw)
gw_fallback = LLMGatewayClient()
gw_fallback.client = httpx.Client(transport=mock_transport)

import unittest.mock
# Simulate OpenAI SDK failure to test httpx fallback trace generation
with unittest.mock.patch("openai.OpenAI", side_effect=RuntimeError("SDK Unreachable")):
    with tel.session(task_id="A-02", task_type="Chat", session_id="sess-llm-trace-02") as sess2:
        assert sess2.counters["llm_call_count"] == 0
        resp_text2 = gw_fallback.chat_completion(
            messages=[{"role": "user", "content": "test question"}],
            session_id="sess-llm-trace-02"
        )
        print("Fallback response text:", resp_text2)
        print("Session counters after fallback:", sess2.counters)
        assert resp_text2 == "mocked fallback answer"
        assert sess2.counters["llm_call_count"] == 1
        assert sess2.counters["total_input_tokens"] == 150
        assert sess2.counters["total_output_tokens"] == 75

# 3. Test ReproductionHandler
handler = ReproductionHandler()
work_dir = Path("/tmp/repro_test")
work_dir.mkdir(parents=True, exist_ok=True)

def mock_repro_gw(request):
    return httpx.Response(
        200,
        request=request,
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

repro_transport = httpx.MockTransport(mock_repro_gw)
with unittest.mock.patch("httpx.Client.post", lambda self, url, **kwargs: repro_transport.handle_request(httpx.Request("POST", url, **kwargs))):
    with tel.session(task_id="D-01", task_type="Reproduction", session_id="sess-repro-trace-01") as sess3:
        assert sess3.counters["llm_call_count"] == 0
        res = handler._call_platform_llm("Generate exp", work_dir=work_dir, session_id="sess-repro-trace-01", timeout=60)
        assert res["choices"][0]["finish_reason"] == "stop"
        print("Session counters after repro LLM:", sess3.counters)
        assert sess3.counters["llm_call_count"] >= 1
        assert sess3.counters["total_input_tokens"] >= 200

print("\n>>> ALL AGENTRUNTIME TRACE AUDIT TESTS PASSED 100% IN BASE CONTAINER! <<<")
