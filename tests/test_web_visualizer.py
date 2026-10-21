# -*- coding: utf-8 -*-
"""测试前端具象化控制台与 Web API 接口"""

import pytest
from fastapi.testclient import TestClient
from server import app

client = TestClient(app)

def test_web_index_html():
    """测试根路径返回 index.html"""
    response = client.get("/")
    assert response.status_code == 200
    assert "AGY-RESEARCH STUDIO" in response.text
    assert "科研助手多智能体具象化控制台" in response.text

def test_api_system_info():
    """测试系统信息接口"""
    response = client.get("/api/system")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "online"
    assert "runtime" in data
    assert "agents" in data
    assert len(data["agents"]) == 5

def test_api_overview():
    """测试基准总览接口"""
    response = client.get("/api/overview")
    assert response.status_code == 200
    data = response.json()
    assert "total_cases" in data
    assert "total_score" in data
    assert "categories" in data

def test_api_tasks():
    """测试任务列表接口"""
    response = client.get("/api/tasks")
    assert response.status_code == 200
    tasks = response.json()
    assert isinstance(tasks, list)
    assert len(tasks) > 0

def test_api_task_detail_survey():
    """测试 C-01 任务详情与引文解析"""
    response = client.get("/api/tasks/C-01")
    assert response.status_code == 200
    data = response.json()
    assert data["case_id"] == "C-01"
    assert "markdown_info" in data
    if data["markdown_info"]:
        assert data["markdown_info"]["char_count"] >= 800

def test_api_task_detail_idea():
    """测试 E-01 任务详情与 8 槽位解析"""
    response = client.get("/api/tasks/E-01")
    assert response.status_code == 200
    data = response.json()
    assert data["case_id"] == "E-01"
    if data.get("slot_analysis"):
        assert data["slot_analysis"]["total_expected"] == 8

def test_api_papers():
    """测试论文库接口"""
    response = client.get("/api/papers")
    assert response.status_code == 200
    papers = response.json()
    assert isinstance(papers, list)

def test_api_citation_snippet():
    """测试真实物理页引文提取接口"""
    response = client.get("/api/citations/snippet?case_id=C-01&doc_num=1&page_num=1")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] in ("success", "file_missing", "not_found")
    if data["status"] == "success":
        assert "filename" in data
        assert "snippet" in data
        assert len(data["snippet"]) > 0

def test_api_benchmark_validate():
    """测试预检接口返回真实控制台输出"""
    response = client.post("/api/benchmark/validate")
    assert response.status_code == 200
    data = response.json()
    assert "raw_output" in data
    assert "PASS" in data["raw_output"]
    assert data["status"] == "passed"

