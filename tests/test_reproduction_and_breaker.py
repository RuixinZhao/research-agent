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


# -------------------------------------------------------------
# 4. Zero LLM Dependency & Concurrent Multi-task Execution Tests
# -------------------------------------------------------------

def test_reproduction_strictly_no_llm_dependency(isolated_repro_env, monkeypatch):
    """
    确保 D 类在任何情况下都不依赖外网大模型：
    即使 LLM 网关配置完全错误，D 类仍然能够 100% 确定性离线完成。
    """
    monkeypatch.setattr(settings, "CHALLENGE_LLM_BASE_URL", "http://non-existent-gateway.invalid:9999/v1")
    monkeypatch.setattr(settings, "CHALLENGE_LLM_API_KEY", "INVALID_KEY")
    
    handler = ReproductionHandler()
    assert handler.llm is None, "ReproductionHandler must explicitly have self.llm = None"

    task = ChallengeTaskInput(
        case_id="D-01",
        function="Reproduction",
        title="D-01 纯离线执行",
        input="测试无网络条件下的 D 类执行",
        materials=[],
        constraints=[],
        expected_output="生成 submission.json 与图表",
        output_schema_ref="Reproduction"
    )

    result = handler.handle(task, session_id="test-session")
    assert result["status"] == "completed"
    assert result["metrics"][0]["observed"] is not None
    assert result["metrics"][0]["reference"] is None
    assert result["metrics"][0]["relative_error"] is None


def test_reproduction_concurrent_multi_tasks(isolated_repro_env):
    """
    测试 D-01 到 D-05 在多线程并发执行环境下的鲁棒性：
    防止多任务并发引起的文件读写交叉污染、竞争冒险或产物混淆。
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    output_dir, team = isolated_repro_env

    cases = ["D-01", "D-02", "D-03", "D-04", "D-05"]

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

    monkeypatch.setattr(handler, "_locate_and_parse_submission", lambda case_id, work_dir, stdout: mock_submission)
    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: type("Proc", (), {"returncode": 0, "stdout": "", "stderr": ""})())

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

    monkeypatch.setattr(handler, "_locate_and_parse_submission", lambda case_id, work_dir, stdout: mock_submission)
    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: type("Proc", (), {"returncode": 0, "stdout": "", "stderr": ""})())

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
    assert handler._verify_and_sync_figures("D-01", {"figures": []}, "/tmp", is_online=False) is True
    assert handler._verify_and_sync_figures("D-01", {"figures": []}, "/tmp", is_online=True) is False


