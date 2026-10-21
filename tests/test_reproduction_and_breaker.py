import os
import time
import json
import pytest
from pathlib import Path
from fastapi.testclient import TestClient

from app.config import settings
from app.core.circuit_breaker import (
    TaskTimeoutGuard,
    TaskTimeoutException,
    CircuitBreaker,
    CircuitBreakerOpenException,
)
from app.handlers.reproduction_handler import ReproductionHandler
from app.schemas.task import ChallengeTaskInput
from server import app


client = TestClient(app)

VALID_PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\n\x00\x00\x00\n\x08\x02\x00\x00\x00\x02PX\xea"
    b"\x00\x00\x00\x13IDATx\x9cc\xfc\xcf\x80\x0f0\xe1\x95e\x18\xa9\xd2\x00A,\x01\x13y\xed\xba&\x00\x00\x00\x00IEND\xaeB`\x82"
)


# -------------------------------------------------------------
# 1. Circuit Breaker & Timeout Guard Unit Tests
# -------------------------------------------------------------

def test_task_timeout_guard_normal():
    guard = TaskTimeoutGuard(case_id="D-01", timeout_seconds=5)
    with guard:
        time.sleep(0.05)
        assert guard.elapsed_time > 0.04
        assert guard.remaining_time() < 5.0
        assert not guard.is_timed_out()
    assert guard.duration > 0.04
    assert not guard.timed_out


def test_task_timeout_guard_timeout():
    # 测试 SIGALRM 超时触发
    with pytest.raises(TaskTimeoutException):
        with TaskTimeoutGuard(case_id="TIMEOUT-TEST", timeout_seconds=1):
            time.sleep(1.5)


def test_circuit_breaker_states():
    cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0.2)
    assert cb.state == CircuitBreaker.STATE_CLOSED
    assert cb.can_execute()

    # 第 1 次失败
    cb.record_failure()
    assert cb.state == CircuitBreaker.STATE_CLOSED
    assert cb.can_execute()

    # 第 2 次失败 -> 熔断开启 (OPEN)
    cb.record_failure()
    assert cb.state == CircuitBreaker.STATE_OPEN
    assert not cb.can_execute()

    # 尝试执行应被拒绝
    with pytest.raises(CircuitBreakerOpenException):
        cb.execute(lambda: "ok")

    # 等待 recovery_timeout 后转入 HALF_OPEN
    time.sleep(0.25)
    assert cb.can_execute()
    assert cb.state == CircuitBreaker.STATE_HALF_OPEN

    # 探针成功后恢复 CLOSED
    res = cb.execute(lambda: "recovered")
    assert res == "recovered"
    assert cb.state == CircuitBreaker.STATE_CLOSED


# -------------------------------------------------------------
# 2. ReproductionHandler D01 ~ D05 Local Offline Tests
# -------------------------------------------------------------

@pytest.fixture
def isolated_repro_env(tmp_path, monkeypatch):
    """设置隔离的临时输出目录和队伍名称"""
    team = "test_team"
    monkeypatch.setattr(settings, "RESEARCH_WORKSPACE_TEAM", team)
    output_dir = tmp_path / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "WORKSPACE_OUTPUT", str(output_dir))
    return output_dir, team


@pytest.mark.parametrize("case_id", ["D-01", "D-02", "D-03", "D-04", "D-05"])
def test_reproduction_d01_to_d05_offline(isolated_repro_env, case_id, monkeypatch):
    output_dir, team = isolated_repro_env
    handler = ReproductionHandler()

    # Mock 材料读取（对 D-03/D-04 补充 mock 材料，D-01/D-02/D-05 读取真实材料）
    orig_materials = handler._read_experiment_materials(case_id)
    if not orig_materials:
        monkeypatch.setattr(
            handler,
            "_read_experiment_materials",
            lambda cid: {
                "method": f"# Method for {cid}\nDescription.",
                "protocol": json.dumps({
                    "case_id": cid,
                    "metrics": [
                        {"name": "Macro-F1", "unit": "分数"},
                        {"name": "Accuracy", "unit": "%"},
                        {"name": "运行时间", "unit": "秒"}
                    ]
                }),
                "sample": json.dumps({"case_id": cid, "data": []})
            }
        )

    # Mock LLM 代码生成响应
    mock_llm_resp = {
        "id": "chatcmpl-mock",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "```python\ndef run_experiment(request):\n    return {'status': 'completed'}\n```"
                },
                "finish_reason": "stop"
            }
        ]
    }
    monkeypatch.setattr(handler, "_call_platform_llm", lambda prompt, work_dir, timeout=60: mock_llm_resp)

    # Mock 官方 runner 执行
    def mock_runner(cid, impl_path=None, timeout=90, **kwargs):
        fig_rel = f"data/figure/{team}/{cid}.png"
        fig_full = output_dir / fig_rel
        fig_full.parent.mkdir(parents=True, exist_ok=True)
        fig_full.write_bytes(VALID_PNG_BYTES)

        return {
            "case_id": cid,
            "status": "completed",
            "metrics": [
                {"name": "Macro-F1", "unit": "分数", "reference": None, "observed": 0.85, "relative_error": None},
                {"name": "Accuracy", "unit": "%", "reference": None, "observed": 91.2, "relative_error": None},
                {"name": "运行时间", "unit": "秒", "reference": None, "observed": 12.3, "relative_error": None}
            ],
            "figures": [
                {
                    "path": fig_rel,
                    "caption": f"实验真实曲线 {cid}",
                    "x_label": "Epoch",
                    "y_label": "Loss",
                    "legend": "Baseline"
                }
            ]
        }

    monkeypatch.setattr(handler, "_invoke_official_runner", mock_runner)

    task = ChallengeTaskInput(
        case_id=case_id,
        function="Reproduction",
        title=f"公开小实验 {case_id}",
        input=f"运行 {case_id} 离线实验流水线并导出指标与图表",
        materials=[],
        constraints=[],
        expected_output="生成 submission.json 与真实图表",
        output_schema_ref="Reproduction"
    )

    result = handler.handle(task, session_id="test-session")

    # 1. 结构与状态核验
    assert result["case_id"] == case_id
    assert result["status"] == "completed"

    # 2. 指标核验
    metrics = result["metrics"]
    assert isinstance(metrics, list) and len(metrics) == 3
    for m in metrics:
        assert "name" in m and "unit" in m
        assert m["observed"] is not None
        assert isinstance(m["observed"], (int, float))
        assert m["reference"] is None
        assert m["relative_error"] is None

    # 3. 图表核验
    figures = result["figures"]
    assert isinstance(figures, list) and len(figures) == 1
    fig = figures[0]
    for key in ("caption", "x_label", "y_label", "legend"):
        assert key in fig and len(fig[key].strip()) > 0

    # 4. 图表实体文件真实存在且为有效 PNG
    fig_path = output_dir / fig["path"]
    assert fig_path.is_file(), f"Figure not found at {fig_path}"
    assert fig_path.stat().st_size > 0
    with open(fig_path, "rb") as f:
        assert f.read(8) == b"\x89PNG\r\n\x1a\n"

    # 5. 落盘文件回读核验
    saved_json = output_dir / "data" / team / f"{case_id}.json"
    assert saved_json.is_file()
    with open(saved_json, "r", encoding="utf-8") as f:
        saved_data = json.load(f)
    assert saved_data["case_id"] == case_id
    assert saved_data["status"] == "completed"
    assert len(saved_data["metrics"]) == 3


def test_reproduction_materials_missing_fallback(isolated_repro_env):
    output_dir, team = isolated_repro_env
    handler = ReproductionHandler()

    task = ChallengeTaskInput(
        case_id="D-99",
        function="Reproduction",
        title="不存在的题目",
        input="运行未知实验",
        materials=[],
        constraints=[],
        expected_output="应当触发材料缺失降级",
        output_schema_ref="Reproduction"
    )

    result = handler.handle(task, session_id="test-session")
    assert result["case_id"] == "D-99"
    assert result["status"] == "materials_missing"
    assert len(result["metrics"]) == 3
    for m in result["metrics"]:
        assert m["observed"] is None
    assert result["figures"] == []

    # 确认回写落盘
    saved_json = output_dir / "data" / team / "D-99.json"
    assert saved_json.is_file()


def test_reproduction_llm_truncation_retry(isolated_repro_env, monkeypatch):
    """
    测试模型输出因长度限制被截断 (finish_reason=='length') 时的重试机制：
    首次调用返回 length 截断，二次调用返回 stop 正常代码。
    """
    output_dir, team = isolated_repro_env
    handler = ReproductionHandler()

    call_count = 0
    prompts_received = []

    def mock_post(client_self, url, json=None, headers=None, **kwargs):
        nonlocal call_count
        call_count += 1
        messages = json.get("messages", [])
        prompts_received.append(messages[-1]["content"])

        if call_count == 1:
            return type("MockResp", (), {
                "status_code": 200,
                "raise_for_status": lambda *a, **kw: None,
                "json": lambda *a, **kw: {
                    "id": "chatcmpl-trunc",
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": "```python\ndef run_experiment(request):\n    # truncated"
                            },
                            "finish_reason": "length"
                        }
                    ]
                }
            })()
        else:
            return type("MockResp", (), {
                "status_code": 200,
                "raise_for_status": lambda *a, **kw: None,
                "json": lambda *a, **kw: {
                    "id": "chatcmpl-complete",
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": "```python\ndef run_experiment(request):\n    return {'status': 'completed'}\n```"
                            },
                            "finish_reason": "stop"
                        }
                    ]
                }
            })()

    monkeypatch.setattr("httpx.Client.post", mock_post)

    work_dir = output_dir / "work_trunc_test"
    work_dir.mkdir(parents=True, exist_ok=True)

    resp = handler._call_platform_llm("Initial prompt", work_dir=work_dir, timeout=60)
    assert call_count == 2, "Expected 1 initial call + 1 retry call"
    assert resp["choices"][0]["finish_reason"] == "stop"
    assert "截断" in prompts_received[1] or "重试" in prompts_received[1]

    # 验证落盘的 generation-response.json
    gen_file = work_dir / "generation-response.json"
    assert gen_file.is_file()
    saved = json.loads(gen_file.read_text(encoding="utf-8"))
    assert saved["id"] == "chatcmpl-complete"

    # 验证保存 implementation.py 成功
    impl_path = handler._save_implementation(resp, work_dir=work_dir)
    assert impl_path.is_file()
    assert "run_experiment" in impl_path.read_text(encoding="utf-8")


def test_reproduction_runner_failure_fallback(isolated_repro_env, monkeypatch):
    """
    测试官方 runner 调度失败时的优雅降级（status='failed'，observed 为 None）。
    """
    output_dir, team = isolated_repro_env
    handler = ReproductionHandler()

    monkeypatch.setattr(handler, "_call_platform_llm", lambda prompt, work_dir, timeout=60: {
        "id": "chatcmpl-mock",
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": "```python\ndef run_experiment(request):\n    return {}\n```"},
            "finish_reason": "stop"
        }]
    })
    monkeypatch.setattr(handler, "_invoke_official_runner", lambda cid, impl_path=None, timeout=90, **kwargs: None)

    task = ChallengeTaskInput(
        case_id="D-01",
        function="Reproduction",
        title="Runner 失败测试",
        input="测试 runner 故障降级",
        materials=[],
        constraints=[],
        expected_output="应当降级为 failed",
        output_schema_ref="Reproduction"
    )

    result = handler.handle(task, session_id="test-session")
    assert result["case_id"] == "D-01"
    assert result["status"] == "failed"
    assert len(result["metrics"]) == 3
    for m in result["metrics"]:
        assert m["observed"] is None
        assert m["relative_error"] is None
    assert result["figures"] == []


def test_reproduction_corrupted_figure_fallback(isolated_repro_env, monkeypatch):
    output_dir, team = isolated_repro_env
    handler = ReproductionHandler()

    monkeypatch.setattr(handler, "_call_platform_llm", lambda prompt, work_dir, timeout=60: {
        "id": "chatcmpl-mock",
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": "```python\ndef run_experiment(request):\n    return {}\n```"},
            "finish_reason": "stop"
        }]
    })

    def mock_runner(cid, impl_path=None, timeout=90, **kwargs):
        fig_rel = f"data/figure/{team}/{cid}.png"
        fig_full = output_dir / fig_rel
        fig_full.parent.mkdir(parents=True, exist_ok=True)
        # 写入损坏的非 PNG 内容
        fig_full.write_bytes(b"CORRUPTED_NOT_PNG_DATA")

        return {
            "case_id": cid,
            "status": "completed",
            "metrics": [
                {"name": "Macro-F1", "unit": "分数", "reference": None, "observed": 0.85, "relative_error": None},
                {"name": "Accuracy", "unit": "%", "reference": None, "observed": 91.2, "relative_error": None},
                {"name": "运行时间", "unit": "秒", "reference": None, "observed": 12.3, "relative_error": None}
            ],
            "figures": [
                {
                    "path": fig_rel,
                    "caption": f"实验损坏图表 {cid}",
                    "x_label": "Epoch",
                    "y_label": "Loss",
                    "legend": "Baseline"
                }
            ]
        }

    monkeypatch.setattr(handler, "_invoke_official_runner", mock_runner)

    task = ChallengeTaskInput(
        case_id="D-01",
        function="Reproduction",
        title="图表损坏用例",
        input="测试图表校验失败降级",
        materials=[],
        constraints=[],
        expected_output="应当降级为 failed",
        output_schema_ref="Reproduction"
    )

    result = handler.handle(task, session_id="test-session")
    assert result["case_id"] == "D-01"
    assert result["status"] == "failed"
    for m in result["metrics"]:
        assert m["observed"] is None
    assert result["figures"] == []


# -------------------------------------------------------------
# 3. Server HTTP POST /solve Integration Test
# -------------------------------------------------------------

def test_server_reproduction_solve_endpoint(isolated_repro_env, monkeypatch):
    output_dir, team = isolated_repro_env

    mock_llm_resp = {
        "id": "chatcmpl-mock",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "```python\ndef run_experiment(request):\n    return {'status': 'completed'}\n```"
                },
                "finish_reason": "stop"
            }
        ]
    }
    monkeypatch.setattr(ReproductionHandler, "_call_platform_llm", lambda self, prompt, work_dir, timeout=60: mock_llm_resp)

    def mock_runner(self, cid, impl_path=None, timeout=90, **kwargs):
        fig_rel = f"data/figure/{team}/{cid}.png"
        fig_full = output_dir / fig_rel
        fig_full.parent.mkdir(parents=True, exist_ok=True)
        fig_full.write_bytes(VALID_PNG_BYTES)

        return {
            "case_id": cid,
            "status": "completed",
            "metrics": [
                {"name": "Macro-F1", "unit": "分数", "reference": None, "observed": 0.85, "relative_error": None},
                {"name": "Accuracy", "unit": "%", "reference": None, "observed": 91.2, "relative_error": None},
                {"name": "运行时间", "unit": "秒", "reference": None, "observed": 12.3, "relative_error": None}
            ],
            "figures": [
                {
                    "path": fig_rel,
                    "caption": f"实验真实曲线 {cid}",
                    "x_label": "Epoch",
                    "y_label": "Loss",
                    "legend": "Baseline"
                }
            ]
        }

    monkeypatch.setattr(ReproductionHandler, "_invoke_official_runner", mock_runner)

    payload = {
        "case_id": "D-01",
        "function": "Reproduction",
        "title": "D-01 文本分类小实验",
        "input": "请复现 D-01 文本分类实验，输出 Macro-F1、Accuracy 与运行时间",
        "materials": [],
        "constraints": [],
        "expected_output": "规范的 Reproduction 输出 JSON",
        "output_schema_ref": "Reproduction"
    }

    response = client.post("/solve", json=payload, headers={"X-Session-ID": "test-sess"})
    assert response.status_code == 200
    data = response.json()
    assert data["case_id"] == "D-01"
    assert data["status"] == "completed"
    assert len(data["metrics"]) == 3
    assert len(data["figures"]) == 1


# -------------------------------------------------------------
# 4. Concurrent Multi-task Execution Tests
# -------------------------------------------------------------

def test_reproduction_concurrent_multi_tasks(isolated_repro_env, monkeypatch):
    """
    测试 D-01 到 D-05 在多线程并发执行环境下的鲁棒性：
    防止多任务并发引起的文件读写交叉污染、竞争冒险或产物混淆。
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    output_dir, team = isolated_repro_env

    cases = ["D-01", "D-02", "D-03", "D-04", "D-05"]

    mock_llm_resp = {
        "id": "chatcmpl-mock",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "```python\ndef run_experiment(request):\n    return {'status': 'completed'}\n```"
                },
                "finish_reason": "stop"
            }
        ]
    }
    monkeypatch.setattr(ReproductionHandler, "_call_platform_llm", lambda self, prompt, work_dir, timeout=60: mock_llm_resp)

    def mock_runner(self, cid, impl_path=None, timeout=90, **kwargs):
        fig_rel = f"data/figure/{team}/{cid}.png"
        fig_full = output_dir / fig_rel
        fig_full.parent.mkdir(parents=True, exist_ok=True)
        fig_full.write_bytes(VALID_PNG_BYTES)

        return {
            "case_id": cid,
            "status": "completed",
            "metrics": [
                {"name": "Macro-F1", "unit": "分数", "reference": None, "observed": 0.85, "relative_error": None},
                {"name": "Accuracy", "unit": "%", "reference": None, "observed": 91.2, "relative_error": None},
                {"name": "运行时间", "unit": "秒", "reference": None, "observed": 12.3, "relative_error": None}
            ],
            "figures": [
                {
                    "path": fig_rel,
                    "caption": f"实验真实曲线 {cid}",
                    "x_label": "Epoch",
                    "y_label": "Loss",
                    "legend": "Baseline"
                }
            ]
        }

    monkeypatch.setattr(ReproductionHandler, "_invoke_official_runner", mock_runner)

    orig_read_mat = ReproductionHandler._read_experiment_materials

    def mock_read_mat(self, cid):
        real = orig_read_mat(self, cid)
        if real:
            return real
        return {
            "method": f"# Method for {cid}",
            "protocol": json.dumps({"case_id": cid, "metrics": []}),
            "sample": json.dumps({"case_id": cid})
        }

    monkeypatch.setattr(ReproductionHandler, "_read_experiment_materials", mock_read_mat)

    def run_case(cid):
        h = ReproductionHandler()
        t = ChallengeTaskInput(
            case_id=cid,
            function="Reproduction",
            title=f"并发小实验 {cid}",
            input=f"运行 {cid} 离线实验流水线",
            materials=[],
            constraints=[],
            expected_output="生成 submission.json 与真实图表",
            output_schema_ref="Reproduction"
        )
        return cid, h.handle(t, session_id=f"sess-{cid}")

    results = {}
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(run_case, cid): cid for cid in cases}
        for f in as_completed(futures):
            cid, res = f.result()
            results[cid] = res

    # 验证全部 5 道题并发执行结果
    for cid in cases:
        assert cid in results
        res = results[cid]
        assert res["case_id"] == cid
        assert res["status"] == "completed"

        # 验证指标与空值
        for m in res["metrics"]:
            assert m["observed"] is not None and isinstance(m["observed"], (int, float))
            assert m["reference"] is None
            assert m["relative_error"] is None

        # 验证图表与魔数签名
        fig = res["figures"][0]
        fig_path = output_dir / fig["path"]
        assert fig_path.is_file()
        with open(fig_path, "rb") as f_img:
            assert f_img.read(8) == b"\x89PNG\r\n\x1a\n"

        # 验证磁盘落盘隔离性
        disk_json = output_dir / "data" / team / f"{cid}.json"
        assert disk_json.is_file()
        with open(disk_json, "r", encoding="utf-8") as f_json:
            disk_data = json.load(f_json)
        assert disk_data["case_id"] == cid
        assert disk_data["status"] == "completed"


# -------------------------------------------------------------
# 5. Relative Error & Figures Validation Unit Tests
# -------------------------------------------------------------

def test_relative_error_computed_when_both_values_present(isolated_repro_env, monkeypatch):
    """验证当 reference 和 observed 同时存在时，准确计算 relative_error = |observed - reference| / |reference|"""
    output_dir, team = isolated_repro_env
    handler = ReproductionHandler()

    mock_submission = {
        "case_id": "D-01",
        "status": "completed",
        "metrics": [
            {"name": "Macro-F1", "unit": "分数", "reference": 1.0, "observed": 0.95, "relative_error": None},
            {"name": "Accuracy", "unit": "%", "reference": 100.0, "observed": 92.5, "relative_error": None},
            {"name": "运行时间", "unit": "秒", "reference": 10.0, "observed": 12.0, "relative_error": None},
        ],
        "figures": []
    }

    monkeypatch.setattr(handler, "_call_platform_llm", lambda prompt, work_dir, timeout=60: {
        "id": "chatcmpl-mock",
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": "```python\ndef run_experiment(request):\n    return {}\n```"},
            "finish_reason": "stop"
        }]
    })
    monkeypatch.setattr(handler, "_invoke_official_runner", lambda cid, impl_path=None, timeout=90, **kwargs: mock_submission)

    task = ChallengeTaskInput(
        case_id="D-01",
        function="Reproduction",
        title="D-01 相对误差测试",
        input="测试 relative_error 计算",
        materials=[],
        constraints=[],
        expected_output="relative_error 正确计算",
        output_schema_ref="Reproduction"
    )

    result = handler.handle(task, session_id="test-session-rel-err")
    assert result["status"] == "completed"
    metrics = result["metrics"]
    assert len(metrics) == 3

    # Macro-F1: |0.95 - 1.0| / 1.0 = 0.05
    assert metrics[0]["relative_error"] == pytest.approx(0.05, abs=1e-5)
    # Accuracy: |92.5 - 100.0| / 100.0 = 0.075
    assert metrics[1]["relative_error"] == pytest.approx(0.075, abs=1e-5)
    # 运行时间: |12.0 - 10.0| / 10.0 = 0.2
    assert metrics[2]["relative_error"] == pytest.approx(0.2, abs=1e-5)


def test_relative_error_none_when_reference_missing(isolated_repro_env, monkeypatch):
    """验证当 reference 缺失或为 0 时，relative_error 保持为 None"""
    output_dir, team = isolated_repro_env
    handler = ReproductionHandler()

    mock_submission = {
        "case_id": "D-02",
        "status": "completed",
        "metrics": [
            {"name": "Recall@5", "unit": "%", "reference": None, "observed": 95.0, "relative_error": None},
            {"name": "MRR@10", "unit": "分数", "reference": 0.0, "observed": 0.5, "relative_error": None},
            {"name": "查询吞吐", "unit": "queries/s", "reference": 100.0, "observed": None, "relative_error": None},
        ],
        "figures": []
    }

    monkeypatch.setattr(handler, "_call_platform_llm", lambda prompt, work_dir, timeout=60: {
        "id": "chatcmpl-mock",
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": "```python\ndef run_experiment(request):\n    return {}\n```"},
            "finish_reason": "stop"
        }]
    })
    monkeypatch.setattr(handler, "_invoke_official_runner", lambda cid, impl_path=None, timeout=90, **kwargs: mock_submission)

    task = ChallengeTaskInput(
        case_id="D-02",
        function="Reproduction",
        title="D-02 缺失 reference 测试",
        input="测试 reference 为 None 或 0 时的 relative_error",
        materials=[],
        constraints=[],
        expected_output="relative_error 为 None",
        output_schema_ref="Reproduction"
    )

    result = handler.handle(task, session_id="test-session-none-ref")
    assert result["status"] == "completed"
    metrics = result["metrics"]
    assert metrics[0]["relative_error"] is None
    assert metrics[1]["relative_error"] is None
    assert metrics[2]["relative_error"] is None


def test_fallback_returns_none_relative_error(isolated_repro_env):
    """验证 _fallback 降级输出中，无论是否配置预设参考值，relative_error 恒为 None"""
    output_dir, team = isolated_repro_env
    handler = ReproductionHandler()

    # 1. 默认无预设参考值的 case_id
    res_default = handler._fallback("D-99", status="materials_missing")
    assert res_default["status"] == "materials_missing"
    for m in res_default["metrics"]:
        assert m["observed"] is None
        assert m["reference"] is None
        assert m["relative_error"] is None

    # 2. 配置了预设参考值场景 (3-元组)
    handler.METRIC_SPECS["D-TEST-PRESET"] = [
        ("Macro-F1", "分数", 85.2),
        ("Accuracy", "%", 92.1),
        ("运行时间", "秒", 12.5),
    ]
    res_preset = handler._fallback("D-TEST-PRESET", status="failed")
    assert res_preset["status"] == "failed"
    assert res_preset["metrics"][0]["reference"] == 85.2
    assert res_preset["metrics"][0]["observed"] is None
    assert res_preset["metrics"][0]["relative_error"] is None
    assert res_preset["metrics"][1]["reference"] == 92.1
    assert res_preset["metrics"][1]["observed"] is None
    assert res_preset["metrics"][1]["relative_error"] is None
    assert res_preset["metrics"][2]["reference"] == 12.5
    assert res_preset["metrics"][2]["observed"] is None
    assert res_preset["metrics"][2]["relative_error"] is None

    # 3. 2-元组格式但包含数值预设 [(85.2, 分数), (92.1, %), (12.5, 秒)]
    handler.METRIC_SPECS["D-TEST-TUPLE2"] = [
        (85.2, "分数"),
        (92.1, "%"),
        (12.5, "秒"),
    ]
    res_tuple2 = handler._fallback("D-TEST-TUPLE2", status="failed")
    assert res_tuple2["status"] == "failed"
    assert res_tuple2["metrics"][0]["reference"] == 85.2
    assert res_tuple2["metrics"][0]["relative_error"] is None
    assert res_tuple2["metrics"][1]["reference"] == 92.1
    assert res_tuple2["metrics"][1]["relative_error"] is None
    assert res_tuple2["metrics"][2]["reference"] == 12.5
    assert res_tuple2["metrics"][2]["relative_error"] is None


def test_figures_empty_allowed_in_local_offline_mode():
    """验证在本地离线模式下 (is_online=False)，figures 为 [] 时允许通过"""
    handler = ReproductionHandler()
    assert handler._verify_and_sync_figures("D-01", {"figures": []}, Path("/tmp"), is_online=False) is True
    assert handler._verify_and_sync_figures("D-01", {"figures": []}, Path("/tmp"), is_online=True) is False
