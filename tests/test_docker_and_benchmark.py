import os
import json
import pytest
from pathlib import Path
from scripts.validate_submission import SubmissionValidator
from scripts.run_mock_benchmark import MockLLMServer


def test_dockerfile_and_requirements():
    dockerfile_path = Path("Dockerfile")
    assert dockerfile_path.is_file(), "Dockerfile 必须存在于项目根目录"

    content = dockerfile_path.read_text(encoding="utf-8")
    assert "FROM agenthack/base:1.1.1" in content, "基础镜像必须指定 agenthack/base:1.1.1"
    assert "USER agent" in content, "必须切换回官方要求的受限非 root 账号 agent"
    assert "EXPOSE 8080" in content, "必须暴露平台 8080 端口"
    assert "chown -R agent:agent /app" in content, "必须保证 agent 用户拥有 /app 操作权限"
    assert "CMD [\"uvicorn\", \"server:app\"" in content, "必须配置生产级 Uvicorn 启动命令"

    dockerignore_path = Path(".dockerignore")
    assert dockerignore_path.is_file(), ".dockerignore 必须存在"
    ignore_content = dockerignore_path.read_text(encoding="utf-8")
    assert "*.tar" in ignore_content
    assert ".git" in ignore_content

    req_path = Path("requirements.txt")
    assert req_path.is_file(), "requirements.txt 必须存在"
    req_lines = req_path.read_text(encoding="utf-8").strip().splitlines()
    assert any("PyMuPDF" in line for line in req_lines), "requirements.txt 必须包含增补依赖 PyMuPDF"


def test_submission_validator_passing_cases(tmp_path):
    team_name = "team"
    data_dir = tmp_path / "data" / team_name
    expert_dir = tmp_path / "data" / "expert"
    fig_dir = tmp_path / "data" / "figure" / team_name
    data_dir.mkdir(parents=True)
    expert_dir.mkdir(parents=True)
    fig_dir.mkdir(parents=True)

    # 构造标准 25 题 dispatch
    case_ids = [f"{c}-{i:02d}" for c in ("A", "B", "C", "D", "E") for i in range(1, 6)]
    dispatch_data = {
        "team": team_name,
        "case_ids": case_ids,
        "cases": [
            {"case_id": cid, "function": "Chat", "question_file": f"data/{team_name}/assigned/{cid}.json"}
            for cid in case_ids
        ]
    }
    with open(data_dir / "dispatch.json", "w", encoding="utf-8") as f:
        json.dump(dispatch_data, f, ensure_ascii=False)

    # 构造各类合法产物
    for cid in case_ids:
        cat = cid[0]
        if cat == "A":
            content = {"case_id": cid, "answer": "学术深度解答机理", "clarifying_question": "范围限定追问？"}
        elif cat == "B":
            content = {"case_id": cid, "papers": [{"filename": "paper.pdf", "reason": "高保真匹配"}]}
        elif cat == "C":
            md_path = f"data/expert/{cid}-综述-{team_name}.md"
            md_text = "# 综述\n" + ("正文严谨分析，详述核心机理与实验对比。" * 30) + ("引用证据材料[1, p.1]。" * 15) + "\n\n## 参考文献\n[1] 文献"
            (tmp_path / md_path).write_text(md_text, encoding="utf-8")
            content = {"case_id": cid, "path": md_path, "markdown": md_text}
        elif cat == "D":
            fig_path = f"data/figure/{team_name}/{cid}.png"
            (tmp_path / fig_path).write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
            content = {
                "case_id": cid,
                "status": "completed",
                "metrics": [
                    {"name": "m1", "unit": "u", "observed": 1.0, "reference": 1.0, "relative_error": 0.0},
                    {"name": "m2", "unit": "u", "observed": 2.0, "reference": 2.0, "relative_error": 0.0},
                    {"name": "m3", "unit": "u", "observed": 3.0, "reference": 3.0, "relative_error": 0.0}
                ],
                "figures": [{"path": fig_path, "caption": "图", "x_label": "x", "y_label": "y", "legend": "l"}]
            }
        elif cat == "E":
            md_path = f"data/expert/{cid}-灵感Idea报告-{team_name}.md"
            md_text = "# Idea\n" + ("8大槽位创新方案设计，边界硬隔离学术研究。" * 60)
            (tmp_path / md_path).write_text(md_text, encoding="utf-8")
            content = {"case_id": cid, "path": md_path, "markdown": md_text}

        with open(data_dir / f"{cid}.json", "w", encoding="utf-8") as f:
            json.dump(content, f, ensure_ascii=False)

    validator = SubmissionValidator(team_name=team_name, root_dir=str(tmp_path))
    assert validator.run() is True, "25 题合规产物预检必须 100% PASS"
    assert len(validator.passed_cases) == 25
    assert len(validator.failed_cases) == 0


def test_submission_validator_error_detection(tmp_path):
    # 构造缺失与非法数据环境，验证预检工具拦截能力
    team_name = "test_err_team"
    data_dir = tmp_path / "data" / team_name
    data_dir.mkdir(parents=True)

    # 1. 构造非法 dispatch.json
    with open(data_dir / "dispatch.json", "w", encoding="utf-8") as f:
        json.dump({"team": team_name, "case_ids": ["A-01"]}, f)

    # 2. 构造不合规的 A-01 (缺少 clarifying_question)
    with open(data_dir / "A-01.json", "w", encoding="utf-8") as f:
        json.dump({"case_id": "A-01", "answer": "只有回答"}, f)

    validator = SubmissionValidator(team_name=team_name, root_dir=str(tmp_path))
    assert validator.run() is False, "非法提交数据必须被预检拦截并返回 False"
    assert any("clarifying_question" in err for err in validator.errors)


def test_mock_llm_server_lifecycle():
    server = MockLLMServer(host="127.0.0.1", port=8999)
    started = server.start()
    assert started is True
    server.stop()


def test_dotenv_and_live_llm_runner(tmp_path):
    from scripts.run_mock_benchmark import load_dotenv_config, MockBenchmarkRunner

    env_file = tmp_path / ".env"
    env_file.write_text("TEST_KEY=HELLO_WORLD\nCHALLENGE_LLM_MODEL=deepseek-chat\n", encoding="utf-8")
    cfg = load_dotenv_config(env_file)
    assert cfg.get("TEST_KEY") == "HELLO_WORLD"
    assert cfg.get("CHALLENGE_LLM_MODEL") == "deepseek-chat"

    runner = MockBenchmarkRunner(live_llm=True, auto_start=False)
    assert runner.live_llm is True
