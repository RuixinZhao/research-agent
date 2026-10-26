import os
import json
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient

from server import app
from app.core.file_writer import SecureFileWriter
from app.handlers.chat_handler import ChatHandler
from app.schemas.task import ChallengeTaskInput
from app.config import settings

client = TestClient(app)

def test_file_writer_team_id_env_resolution(monkeypatch, tmp_path):
    monkeypatch.setenv("TEAM_ID", "team_agent_hack_01")
    monkeypatch.delenv("RESEARCH_WORKSPACE_TEAM", raising=False)
    fw = SecureFileWriter(workspace_root=str(tmp_path))
    assert fw.team_name == "team_agent_hack_01"

def test_file_writer_multi_root_redundancy(monkeypatch, tmp_path):
    monkeypatch.setenv("TEAM_ID", "team_custom")
    root_dir = tmp_path / "output"
    root_dir.mkdir()
    fw = SecureFileWriter(workspace_root=str(root_dir))
    
    data = {"case_id": "A-99", "answer": "测试回答", "clarifying_question": "测试追问？"}
    rel_path = f"data/{fw.team_name}/A-99.json"
    fw.write_json_and_verify(rel_path, data)
    
    # 验证 primary_abs
    primary_file = root_dir / "data" / "team_custom" / "A-99.json"
    assert primary_file.is_file()

def test_chat_handler_clamp_length(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "WORKSPACE_OUTPUT", str(tmp_path))
    handler = ChatHandler()
    
    # 超长 350 字
    long_answer = "在系统动力学建模中，控制变量与状态空间维度的耦合关系对收敛性具有显著影响。" * 10
    task = ChallengeTaskInput(
        case_id="A-04",
        function="Chat",
        title="轨迹控制",
        input="测试输入",
        materials=[],
        constraints=[],
        expected_output="",
        output_schema_ref="Chat"
    )
    mock_resp = json.dumps({
        "answer": long_answer,
        "clarifying_question": "请问自变量调节范围如何限定"
    }, ensure_ascii=False)
    
    with patch("app.core.llm_gateway.LLMGatewayClient.chat_completion", return_value=mock_resp):
        res = handler.handle(task, session_id="test-sess")
        
    assert res["case_id"] == "A-04"
    assert len(res["answer"]) <= 300
    assert res["clarifying_question"].endswith("？")

def test_server_fallback_writes_to_disk_on_exception(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "WORKSPACE_OUTPUT", str(tmp_path))
    monkeypatch.setenv("TEAM_ID", "team_err_test")
    
    payload = {
        "case_id": "A-04",
        "function": "Chat",
        "title": "异常测试",
        "input": "异常输入",
        "materials": [],
        "constraints": [],
        "expected_output": "",
        "output_schema_ref": "Chat"
    }
    
    with patch("server.get_handler", side_effect=RuntimeError("Simulated LLM Gateway Crash")):
        response = client.post("/solve", json=payload, headers={"X-Session-ID": "err-sess"})
        
    assert response.status_code == 200
    data = response.json()
    assert data["case_id"] == "A-04"
    assert "answer" in data
    
    # 验证磁盘必然落盘，绝不漏写
    disk_file = tmp_path / "data" / "team_err_test" / "A-04.json"
    assert disk_file.is_file()
    with open(disk_file, "r", encoding="utf-8") as f:
        disk_data = json.load(f)
    assert disk_data["case_id"] == "A-04"
