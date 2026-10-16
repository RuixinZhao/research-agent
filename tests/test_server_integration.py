import os
import json
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient

from server import app
from app.config import settings

client = TestClient(app)

@pytest.fixture
def isolated_server_env(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "RESEARCH_WORKSPACE_TEAM", "team_eval")
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    monkeypatch.setattr(settings, "WORKSPACE_OUTPUT", str(output_dir))
    return output_dir

def test_server_chat_endpoint(isolated_server_env):
    payload = {
        "case_id": "A-01",
        "function": "Chat",
        "title": "对话测试",
        "input": "请解释深度学习中的梯度消失问题，并提出一个限定性追问。",
        "materials": [],
        "constraints": [],
        "expected_output": "回答与追问",
        "output_schema_ref": "Chat"
    }

    mock_llm_resp = json.dumps({
        "answer": "梯度消失（Gradient Vanishing）主要源于反向传播链式法则中深层导数连乘小于1（如Sigmoid饱和区或小权重矩阵）。可通过残差连接（Residual Connections）或归一化层缓解。",
        "clarifying_question": "请问本研究所采用的网络深度（层数）以及使用的具体非线性激活函数是什么？"
    }, ensure_ascii=False)

    with patch("app.core.llm_gateway.LLMGatewayClient.chat_completion", return_value=mock_llm_resp):
        response = client.post("/solve", json=payload, headers={"X-Session-ID": "sess-test"})

    assert response.status_code == 200
    data = response.json()
    assert data["case_id"] == "A-01"
    assert "梯度消失" in data["answer"]
    assert "请问" in data["clarifying_question"]

def test_server_idea_endpoint(isolated_server_env):
    payload = {
        "case_id": "E-05",
        "function": "Idea",
        "title": "大模型幻觉抑制与细粒度归因",
        "input": "阅读检索增强生成论文，提出细粒度事实溯源方案。模拟观察表明单句引用准确率较低，但未测试段落级长上下文融合。",
        "materials": ["ALiiCE_NAACL2025.pdf", "RefChecker_2024.pdf"],
        "constraints": ["只把题目给出的模拟观察作为待分析现象，不得写成论文实测结论"],
        "expected_output": "返回 Idea 方案",
        "output_schema_ref": "Idea"
    }

    mock_md = """# 细粒度事实溯源与幻觉抑制创新方案

## 1. 研究动机与问题背景
现有大语言模型（LLM）在检索增强生成（RAG）场景中频繁出现细粒度实体层面的事实幻觉（Hallucination）。已有研究主要聚焦于粗粒度文档级召回，未能精确界定生成 token 与检索源文本物理跨度之间的对齐关系，导致不可靠的归因输出。

## 2. 核心Idea与技术路线
提出实体级双向跨度注意力重加权机制（SpanAttn-Align）。通过在解码阶段对实体命名词与原始召回页码物理坐标建立动态注意力约束流，实现显式引用绑定与细粒度幻觉抑制。

## 3. 实验方案与消融设计
设立三组对比实验：与标准 RAG 基线、词级重排序模型进行对比。消融实验设置：剥离实体对齐模块、剥离上下文衰减因子、替换不同长文本窗口大小。

## 4. 基准数据集与数据特征
采用 FActScore 与 ALiiCE 权威公开基准数据集。包含 50,000 个复杂事实性问答对，标注了 token 级的显式引用来源与物理页码对应关系。

## 5. 量化评价指标体系
采用以下指标体系：
1. 引用精度（Citation Precision, CP, %）
2. 实体幻觉率（Entity Hallucination Rate, EHR, %）
3. 归因延迟（Attribution Latency, ms）
显著性分析采用两独立样本 t 检验 ($p < 0.01$)。

## 6. 复现瓶颈与观察边界反思
### 6.1 证据边界硬隔离说明（模拟观察待验证 vs 论文实测定论）
特别声明：题目给定的“单句引用准确率较低”仅为特定受限提示词与特定采样条件下的**初步待验证模拟观察（Preliminary Observation）**，缺乏多模型多样化提示词的跨域统计支撑，**严禁将其归结为相关参考文献既有的实测定论（Empirical Conclusion）**。本方案将其作为待检验假说，通过大规模双盲评测验证其在多语言和长上下文场景下的鲁棒性。

### 6.2 算法复现瓶颈与工程挑战
在工程落地中，跨度级别注意力张量矩阵存储开销随着序列长度呈二次方膨胀，且跨页文档跨度分割存在边界歧义，需要构建轻量级缓存索引。

## 7. 多篇文献互补与协同机制
文献 [1] (ALiiCE) 侧重于位置细粒度引文生成，具备高召回特性但计算开销大；
文献 [2] (RefChecker) 专注于后验细粒度事实核验，准确率极高但缺乏生成引导。
本方案将两者互补结合，形成前向生成引导与后验核验的自洽闭环。

## 8. 场景可行性、约束与失败边界
系统在单张 A10 显卡上进行显存优化，常驻显存开销低于 3GB，寻优延迟小于 120ms。失败边界：对于高度抽象的无实体因果推断文本，实体对齐机制效用退化，系统自动熔断至宽松上下文校验机制。

## 参考文献
[1] ALiiCE Authors. ALiiCE: Positional Fine-grained Citation Generation. NAACL, 2025.
[2] RefChecker Authors. Fine-grained Hallucination Checker. 2024.
"""

    with patch("app.core.llm_gateway.LLMGatewayClient.chat_completion", return_value=mock_md):
        response = client.post("/solve", json=payload, headers={"X-Session-ID": "sess-test"})

    assert response.status_code == 200
    data = response.json()
    assert data["case_id"] == "E-05"
    assert "data/expert/E-05-灵感Idea报告-team_eval.md" in data["path"]
    assert "证据边界" in data["markdown"]
    assert "模拟观察" in data["markdown"]
    assert len(data["markdown"]) >= 800
