"""Unit tests for D-02 and D-05 reference implementations."""
import json
from pathlib import Path
import runpy
import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
D02_IMPL_PATH = ROOT_DIR / "d_implementations/D-02-implementation.py"
D05_IMPL_PATH = ROOT_DIR / "d_implementations/D-05-implementation.py"


@pytest.fixture(scope="module")
def d02_module():
    return runpy.run_path(str(D02_IMPL_PATH))


@pytest.fixture(scope="module")
def d05_module():
    return runpy.run_path(str(D05_IMPL_PATH))


def test_d02_run_phase(d02_module):
    req_path = ROOT_DIR / "research-experiments-v1/公开样例请求/D-02.json"
    req = json.loads(req_path.read_text(encoding="utf-8"))["payload"]
    run_exp = d02_module["run_experiment"]

    result = run_exp(req)
    assert "baseline" in result, "D-02 run phase missing baseline"
    assert "candidate" in result, "D-02 run phase missing candidate"
    assert "details" in result, "D-02 run phase missing details"

    details = result["details"]
    assert "selected" in details, "Missing details.selected"
    assert "search" in details, "Missing details.search"
    assert len(details["search"]) == 27, f"Expected 27 search grid rows, got {len(details['search'])}"

    selected = details["selected"]
    assert "k1" in selected and "b" in selected and "title_weight" in selected
    assert selected == {"b": 0.0, "k1": 0.4, "title_weight": 0.5}

    test_queries = req["data"]["test_queries"]
    test_q_ids = set(q["id"] for q in test_queries)
    assert set(result["baseline"].keys()) == test_q_ids
    assert set(result["candidate"].keys()) == test_q_ids

    all_doc_ids = set(d["id"] for d in req["data"]["documents"])
    for q_id in test_q_ids:
        b_ranking = result["baseline"][q_id]
        c_ranking = result["candidate"][q_id]
        assert set(r["id"] for r in b_ranking) == all_doc_ids
        assert set(r["id"] for r in c_ranking) == all_doc_ids

        # Check descending scores, ties ascending by id
        for i in range(len(c_ranking) - 1):
            assert (
                -c_ranking[i]["score"],
                c_ranking[i]["id"],
            ) <= (
                -c_ranking[i + 1]["score"],
                c_ranking[i + 1]["id"],
            ), "Ranking not strictly ordered by (-score, id)"


def test_d02_rank_phase(d02_module):
    req_path = ROOT_DIR / "research-experiments-v1/公开样例请求/D-02/rank-default.json"
    req = json.loads(req_path.read_text(encoding="utf-8"))["payload"]
    run_exp = d02_module["run_experiment"]

    result = run_exp(req)
    assert "candidate" in result, "D-02 rank phase missing candidate"
    assert "details" not in result or not result.get("details"), "Rank phase should not retune details"

    test_queries = req["data"]["test_queries"]
    test_q_ids = set(q["id"] for q in test_queries)
    assert set(result["candidate"].keys()) == test_q_ids

    all_doc_ids = set(d["id"] for d in req["data"]["documents"])
    for q_id in test_q_ids:
        c_ranking = result["candidate"][q_id]
        assert set(r["id"] for r in c_ranking) == all_doc_ids


def test_d05_task_conservation_and_metrics(d05_module):
    req_path = ROOT_DIR / "research-experiments-v1/公开样例请求/D-05.json"
    req = json.loads(req_path.read_text(encoding="utf-8"))["payload"]
    run_exp = d05_module["run_experiment"]
    compute_metrics = d05_module["compute_metrics"]

    result = run_exp(req)
    assert "baseline" in result and "candidate" in result

    data = req["data"]
    all_jobs = data["jobs"]
    all_ids = set(j["id"] for j in all_jobs)

    for mode in ["baseline", "candidate"]:
        run_data = result[mode]
        trace = run_data["trace"]
        dropped = run_data["dropped"]
        served_ms = run_data["served_ms"]

        trace_ids = set(t["id"] for t in trace)
        dropped_ids = set(d["id"] for d in dropped)

        # 任务守恒定律断言: trace 与 dropped 的并集必须严格等于全部任务，且无交集
        assert trace_ids | dropped_ids == all_ids, f"{mode}: Task conservation union mismatch"
        assert len(trace_ids & dropped_ids) == 0, f"{mode}: Task in both trace and dropped"
        assert len(trace) + len(dropped) == len(all_jobs), f"{mode}: Task count mismatch"

        # dropped 按 id 排序
        assert dropped == sorted(dropped, key=lambda x: str(x["id"]))

        # trace 按 dispatch_ms, server 排序
        for i in range(len(trace) - 1):
            assert (trace[i]["dispatch_ms"], trace[i]["server"]) <= (
                trace[i + 1]["dispatch_ms"],
                trace[i + 1]["server"],
            )

        # 指标计算核验
        metrics = compute_metrics(run_data, data["flow_weights"], data["servers"], data["horizon_ms"])
        assert 0.0 <= metrics["jain"] <= 1.0, f"{mode}: Invalid Jain index: {metrics['jain']}"
        assert 0.0 <= metrics["throughput"] <= 100.0, f"{mode}: Invalid throughput: {metrics['throughput']}"
        assert metrics["mean_wait"] >= 0.0, f"{mode}: Negative wait time: {metrics['mean_wait']}"
        assert metrics["throughput"] == 40.0
        assert metrics["jain"] == pytest.approx(1.0 / 3.0)
        assert metrics["mean_wait"] == 0.0


def test_d05_multi_server_and_boundary(d05_module):
    """Test concurrent 2 servers with setup cost, burst arrivals, deadline & horizon limits."""
    run_exp = d05_module["run_experiment"]
    test_req = {
        "case_id": "D-05",
        "phase": "run",
        "data": {
            "jobs": [
                {"id": "j1", "flow": "A", "arrival_ms": 0, "service_ms": 5, "deadline_ms": 20},
                {"id": "j2", "flow": "B", "arrival_ms": 0, "service_ms": 4, "deadline_ms": 20},
                {"id": "j3", "flow": "A", "arrival_ms": 1, "service_ms": 3, "deadline_ms": 5},  # will miss deadline on single busy server
                {"id": "j4", "flow": "C", "arrival_ms": 2, "service_ms": 10, "deadline_ms": 100}, # will exceed horizon 15
            ],
            "flow_weights": {"A": 1, "B": 2, "C": 1},
            "servers": 2,
            "setup_ms": 2,
            "horizon_ms": 15,
        },
    }
    result = run_exp(test_req)
    all_ids = {"j1", "j2", "j3", "j4"}

    for mode in ["baseline", "candidate"]:
        trace_ids = set(t["id"] for t in result[mode]["trace"])
        dropped_ids = set(d["id"] for d in result[mode]["dropped"])
        assert trace_ids | dropped_ids == all_ids
        assert len(trace_ids & dropped_ids) == 0
        assert len(result[mode]["trace"]) + len(result[mode]["dropped"]) == 4
