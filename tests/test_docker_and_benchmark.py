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


def test_submission_validator_passing_cases():
    validator = SubmissionValidator(team_name="team")
    assert validator.run() is True, "已有 25 题产物预检必须 100% PASS"
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
