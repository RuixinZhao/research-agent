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
def test_reproduction_d01_to_d05_offline(isolated_repro_env, case_id):
    output_dir, team = isolated_repro_env
    handler = ReproductionHandler()

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


def test_reproduction_corrupted_figure_fallback(isolated_repro_env, monkeypatch):
    output_dir, team = isolated_repro_env
    handler = ReproductionHandler()

    # 模拟核验图表时损坏的情况
    def mock_corrupt_verify(*args, **kwargs):
        return False

    monkeypatch.setattr(handler, "_verify_and_sync_figures", mock_corrupt_verify)

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

def test_server_reproduction_solve_endpoint(isolated_repro_env):
    output_dir, team = isolated_repro_env

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
