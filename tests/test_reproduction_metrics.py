import pytest
from app.handlers.reproduction_handler import ReproductionHandler
from app.schemas.task import ChallengeTaskInput
from app.config import settings


@pytest.fixture
def repro_test_env(tmp_path, monkeypatch):
    team = "test_metrics_team"
    monkeypatch.setattr(settings, "RESEARCH_WORKSPACE_TEAM", team)
    output_dir = tmp_path / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "WORKSPACE_OUTPUT", str(output_dir))
    return output_dir, team


def test_relative_error_computed_when_both_values_present(repro_test_env, monkeypatch):
    """
    构造一个 submission_data，其中某 metric 的 reference=100.0, observed=95.0，
    验证经 handler 内部处理后 relative_error == 0.05（即 |95-100|/100）。
    """
    output_dir, team = repro_test_env
    handler = ReproductionHandler()

    mock_submission = {
        "case_id": "D-01",
        "status": "completed",
        "metrics": [
            {
                "name": "Accuracy",
                "unit": "%",
                "reference": 100.0,
                "observed": 95.0,
                "relative_error": None
            },
            {
                "name": "Macro-F1",
                "unit": "分数",
                "reference": 1.0,
                "observed": 0.90,
                "relative_error": None
            },
            {
                "name": "运行时间",
                "unit": "秒",
                "reference": 10.0,
                "observed": 12.0,
                "relative_error": None
            }
        ],
        "figures": []
    }

    monkeypatch.setattr(handler, "_locate_and_parse_submission", lambda case_id, work_dir, stdout: mock_submission)
    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: type("Proc", (), {"returncode": 0, "stdout": "", "stderr": ""})())

    task = ChallengeTaskInput(
        case_id="D-01",
        function="Reproduction",
        title="D-01 指标相对误差测试",
        input="测试 reference=100.0, observed=95.0 的相对误差",
        materials=[],
        constraints=[],
        expected_output="relative_error == 0.05",
        output_schema_ref="Reproduction"
    )

    result = handler.handle(task, session_id="session-test-rel-err")
    assert result["status"] == "completed"
    metrics = result["metrics"]
    assert len(metrics) == 3

    # Accuracy: |95.0 - 100.0| / 100.0 == 0.05
    acc_metric = metrics[0]
    assert acc_metric["name"] == "Accuracy"
    assert acc_metric["reference"] == 100.0
    assert acc_metric["observed"] == 95.0
    assert acc_metric["relative_error"] == pytest.approx(0.05, abs=1e-5)

    # Macro-F1: |0.90 - 1.0| / 1.0 == 0.10
    assert metrics[1]["relative_error"] == pytest.approx(0.10, abs=1e-5)

    # 运行时间: |12.0 - 10.0| / 10.0 == 0.20
    assert metrics[2]["relative_error"] == pytest.approx(0.20, abs=1e-5)


def test_relative_error_none_when_reference_missing(repro_test_env, monkeypatch):
    """
    构造 reference=None, observed=85.0 的 metric，
    验证 relative_error 保持为 None。
    """
    output_dir, team = repro_test_env
    handler = ReproductionHandler()

    mock_submission = {
        "case_id": "D-02",
        "status": "completed",
        "metrics": [
            {
                "name": "Recall@5",
                "unit": "%",
                "reference": None,
                "observed": 85.0,
                "relative_error": None
            },
            {
                "name": "MRR@10",
                "unit": "分数",
                "reference": 0.0,
                "observed": 0.8,
                "relative_error": None
            },
            {
                "name": "查询吞吐",
                "unit": "queries/s",
                "reference": 1000.0,
                "observed": None,
                "relative_error": None
            }
        ],
        "figures": []
    }

    monkeypatch.setattr(handler, "_locate_and_parse_submission", lambda case_id, work_dir, stdout: mock_submission)
    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: type("Proc", (), {"returncode": 0, "stdout": "", "stderr": ""})())

    task = ChallengeTaskInput(
        case_id="D-02",
        function="Reproduction",
        title="D-02 缺失 reference 相对误差测试",
        input="测试 reference=None 时的 relative_error",
        materials=[],
        constraints=[],
        expected_output="relative_error is None",
        output_schema_ref="Reproduction"
    )

    result = handler.handle(task, session_id="session-test-none-ref")
    assert result["status"] == "completed"
    metrics = result["metrics"]
    assert len(metrics) == 3

    # reference=None -> relative_error is None
    assert metrics[0]["reference"] is None
    assert metrics[0]["observed"] == 85.0
    assert metrics[0]["relative_error"] is None

    # reference=0.0 -> relative_error is None
    assert metrics[1]["reference"] == 0.0
    assert metrics[1]["observed"] == 0.8
    assert metrics[1]["relative_error"] is None

    # observed=None -> relative_error is None
    assert metrics[2]["reference"] == 1000.0
    assert metrics[2]["observed"] is None
    assert metrics[2]["relative_error"] is None


def test_fallback_returns_none_relative_error(repro_test_env):
    """
    直接调用 handler._fallback("D-01", "failed")，
    验证返回的所有 metric 的 relative_error 均为 None（降级时不能伪造误差）。
    """
    output_dir, team = repro_test_env
    handler = ReproductionHandler()

    res = handler._fallback("D-01", "failed")
    assert res["case_id"] == "D-01"
    assert res["status"] == "failed"
    assert len(res["metrics"]) == 3
    for m in res["metrics"]:
        assert m["observed"] is None
        assert m["relative_error"] is None
