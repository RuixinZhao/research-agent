import os
import json
import pytest
import fitz
from unittest.mock import patch

from app.schemas.task import ChallengeTaskInput
from app.handlers.retrieval_handler import RetrievalHandler
from app.config import settings

@pytest.fixture
def mock_retrieval_papers_env(tmp_path, monkeypatch):
    """
    搭建受控的 B 类检索测试环境：
    创建 10 篇特征鲜明的模拟 PDF 论文，用于测试 Negation Firewall 对抗排他能力。
    """
    papers_dir = tmp_path / "papers"
    output_dir = tmp_path / "output"
    papers_dir.mkdir()
    output_dir.mkdir()

    monkeypatch.setattr(settings, "RESEARCH_WORKSPACE_TEAM", "test_team")
    monkeypatch.setattr(settings, "WORKSPACE_OUTPUT", str(output_dir))
    monkeypatch.setattr(settings, "PAPERS_DIR", str(papers_dir))

    mock_papers_meta = [
        (
            "Classical_SVM_Classification.pdf",
            "Support Vector Machines without Neural Networks",
            "This paper presents classical support vector machines and kernel methods for classification without using any neural networks or deep learning architectures."
        ),
        (
            "Deep_Neural_Network_Vision.pdf",
            "Deep Neural Networks for Visual Recognition",
            "This paper investigates multi-layer deep neural networks and convolutional neural network architectures for visual recognition."
        ),
        (
            "Content_Based_RecSys.pdf",
            "Content-Based Recommendation Systems",
            "This paper designs item-feature content-based recommendation systems, deliberately excluding collaborative filtering methods."
        ),
        (
            "Collaborative_Filtering_RecSys.pdf",
            "Collaborative Filtering for Recommenders",
            "This paper explores matrix factorization and user-item collaborative filtering methods for large-scale recommendation systems."
        ),
        (
            "LLaMA_Open_Foundation_Model.pdf",
            "LLaMA: Open Foundation Language Models",
            "This paper introduces LLaMA, an open foundational large language model, developed independently of OpenAI GPT series."
        ),
        (
            "GPT_Generative_Pretrained_Transformer.pdf",
            "GPT: Generative Pretrained Transformers",
            "This paper proposes GPT generative pretrained transformer architecture for natural language generation."
        ),
        (
            "GNN_Graph_Classification.pdf",
            "Whole-Graph Classification with Graph Neural Networks",
            "This paper focuses on whole-graph classification for chemical molecular graphs using GNNs, without performing any node classification."
        ),
        (
            "GNN_Node_Classification.pdf",
            "Semi-Supervised Node Classification with GCNs",
            "This paper proposes graph convolutional networks specifically evaluated on semi-supervised node classification benchmarks."
        ),
        (
            "Transformer_Attention_Model.pdf",
            "Attention Is All You Need",
            "This paper introduces the Transformer model based entirely on multi-head self-attention mechanisms without recurrence."
        ),
        (
            "Random_Forest_Tabular.pdf",
            "Random Forest on Structured Data",
            "This paper benchmarks decision trees and random forests on structured tabular data without neural attention mechanisms."
        ),
    ]

    for fname, title, text in mock_papers_meta:
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((50, 50), f"{title}\n\nAbstract: {text}")
        doc.save(str(papers_dir / fname))
        doc.close()

    return papers_dir, output_dir


def _mock_firewall_llm_response(messages, **kwargs):
    """
    根据 Negation Firewall Prompt 智能模拟审校裁判的评估输出
    """
    user_prompt = ""
    for m in messages:
        if m["role"] == "user":
            user_prompt = m["content"]
            break

    # 解析 prompt 中的任务需求与排他意图
    if "神经网络" in user_prompt and ("不包含" in user_prompt or "排除" in user_prompt):
        return json.dumps({
            "negative_exclusions": ["神经网络"],
            "evaluations": [
                {
                    "filename": "Classical_SVM_Classification.pdf",
                    "negative_violation": False,
                    "core_contribution_match": True,
                    "confidence_score": 5,
                    "decision": "ACCEPT",
                    "reason": "该文献研究经典支持向量机方法，未采用任何神经网络，完全符合排他要求。"
                },
                {
                    "filename": "Deep_Neural_Network_Vision.pdf",
                    "negative_violation": True,
                    "core_contribution_match": False,
                    "confidence_score": 1,
                    "decision": "REJECT",
                    "reason": "该文献核心方法为深度神经网络，直接触碰不包含神经网络的排他红线。"
                }
            ],
            "selected": [
                {
                    "filename": "Classical_SVM_Classification.pdf",
                    "reason": "研究经典支持向量机分类，未触碰神经网络排他红线。"
                }
            ]
        }, ensure_ascii=False)

    elif "协同过滤" in user_prompt and "排除" in user_prompt:
        return json.dumps({
            "negative_exclusions": ["协同过滤"],
            "evaluations": [
                {
                    "filename": "Content_Based_RecSys.pdf",
                    "negative_violation": False,
                    "core_contribution_match": True,
                    "confidence_score": 5,
                    "decision": "ACCEPT",
                    "reason": "该文献聚焦基于内容的推荐系统，未采用协同过滤，符合排他要求。"
                },
                {
                    "filename": "Collaborative_Filtering_RecSys.pdf",
                    "negative_violation": True,
                    "core_contribution_match": False,
                    "confidence_score": 1,
                    "decision": "REJECT",
                    "reason": "该文献核心方法正是协同过滤，触碰绝对排他红线。"
                }
            ],
            "selected": [
                {
                    "filename": "Content_Based_RecSys.pdf",
                    "reason": "研究基于内容的推荐系统，排除了协同过滤方法。"
                }
            ]
        }, ensure_ascii=False)

    elif "GPT" in user_prompt and ("不要" in user_prompt or "不包含" in user_prompt):
        return json.dumps({
            "negative_exclusions": ["GPT"],
            "evaluations": [
                {
                    "filename": "LLaMA_Open_Foundation_Model.pdf",
                    "negative_violation": False,
                    "core_contribution_match": True,
                    "confidence_score": 5,
                    "decision": "ACCEPT",
                    "reason": "该文献为开源大语言模型 LLaMA，非 GPT 系列，完全合规。"
                },
                {
                    "filename": "GPT_Generative_Pretrained_Transformer.pdf",
                    "negative_violation": True,
                    "core_contribution_match": False,
                    "confidence_score": 1,
                    "decision": "REJECT",
                    "reason": "该文献为 GPT 论文，触犯排他约束。"
                }
            ],
            "selected": [
                {
                    "filename": "LLaMA_Open_Foundation_Model.pdf",
                    "reason": "介绍大语言模型且不包含 GPT 系列文献。"
                }
            ]
        }, ensure_ascii=False)

    elif "节点分类" in user_prompt and ("不涉及" in user_prompt or "排除" in user_prompt):
        return json.dumps({
            "negative_exclusions": ["节点分类"],
            "evaluations": [
                {
                    "filename": "GNN_Graph_Classification.pdf",
                    "negative_violation": False,
                    "core_contribution_match": True,
                    "confidence_score": 5,
                    "decision": "ACCEPT",
                    "reason": "该文献专注整图分类任务，不涉及节点分类，符合要求。"
                },
                {
                    "filename": "GNN_Node_Classification.pdf",
                    "negative_violation": True,
                    "core_contribution_match": False,
                    "confidence_score": 1,
                    "decision": "REJECT",
                    "reason": "该文献专门研究节点分类，触犯排他红线。"
                }
            ],
            "selected": [
                {
                    "filename": "GNN_Graph_Classification.pdf",
                    "reason": "图神经网络文献，专注于图级别分类且不涉及节点分类。"
                }
            ]
        }, ensure_ascii=False)

    elif "Transformer" in user_prompt or "注意力机制" in user_prompt:
        return json.dumps({
            "negative_exclusions": [],
            "evaluations": [
                {
                    "filename": "Transformer_Attention_Model.pdf",
                    "negative_violation": False,
                    "core_contribution_match": True,
                    "confidence_score": 5,
                    "decision": "ACCEPT",
                    "reason": "该文献提出 Transformer 自注意力模型，完全切合正面主题。"
                },
                {
                    "filename": "Random_Forest_Tabular.pdf",
                    "negative_violation": False,
                    "core_contribution_match": False,
                    "confidence_score": 1,
                    "decision": "REJECT",
                    "reason": "随机森林文献与 Transformer 注意力机制无关。"
                }
            ],
            "selected": [
                {
                    "filename": "Transformer_Attention_Model.pdf",
                    "reason": "该论文提出 Transformer 架构及其多头注意力机制。"
                }
            ]
        }, ensure_ascii=False)

    # 兜底返回空，恪守宁缺毋滥原则
    return json.dumps({"negative_exclusions": [], "evaluations": [], "selected": []})


def test_negation_firewall_query_1_exclude_neural_network(mock_retrieval_papers_env):
    """
    查询 1：「找出不包含'神经网络'的论文」
    期望：返回的 found_papers 列表中不含"神经网络"相关论文，严防误报扣分。
    """
    handler = RetrievalHandler()
    task = ChallengeTaskInput(
        case_id="B-NEG-01",
        function="Literature_Retrieval",
        title="非神经网络分类算法检索",
        input="找出不包含'神经网络'的论文",
        materials=[],
        constraints=["排除任何采用神经网络或深度学习的论文"],
        expected_output="不含神经网络的分类文献",
        output_schema_ref="Literature_Retrieval"
    )

    with patch.object(handler.llm, "chat_completion", side_effect=_mock_firewall_llm_response):
        result = handler.handle(task, "test_negation_session_01")

    found_papers = [p["filename"] for p in result["papers"]]
    print(f"Query 1 Found papers: {found_papers}")

    # 断言：绝对不能包含 Deep_Neural_Network_Vision.pdf，也不能包含任何带有 Neural_Network 的论文
    for p in found_papers:
        assert "Neural_Network" not in p, f"违规包含神经网络文献: {p}"
        assert "神经网络" not in p, f"违规包含神经网络文献: {p}"

    # 断言：高精度命中古典 SVM 论文
    assert "Classical_SVM_Classification.pdf" in found_papers


def test_negation_firewall_query_2_exclude_collaborative_filtering(mock_retrieval_papers_env):
    """
    查询 2：「查找研究方向为推荐系统但排除协同过滤方法的文献」
    期望：高精度返回基于内容的推荐文献，坚决排除协同过滤文献。
    """
    handler = RetrievalHandler()
    task = ChallengeTaskInput(
        case_id="B-NEG-02",
        function="Literature_Retrieval",
        title="推荐系统文献检索",
        input="查找研究方向为推荐系统但排除协同过滤方法的文献",
        materials=[],
        constraints=["排除任何采用协同过滤的文献"],
        expected_output="非协同过滤推荐系统文献",
        output_schema_ref="Literature_Retrieval"
    )

    with patch.object(handler.llm, "chat_completion", side_effect=_mock_firewall_llm_response):
        result = handler.handle(task, "test_negation_session_02")

    found_papers = [p["filename"] for p in result["papers"]]
    print(f"Query 2 Found papers: {found_papers}")

    # 断言：排除协同过滤
    for p in found_papers:
        assert "Collaborative_Filtering" not in p, f"违规包含协同过滤文献: {p}"
        assert "协同过滤" not in p, f"违规包含协同过滤文献: {p}"

    assert "Content_Based_RecSys.pdf" in found_papers


def test_negation_firewall_query_3_exclude_gpt(mock_retrieval_papers_env):
    """
    查询 3：「搜索大语言模型相关论文，但不要包含 GPT」
    期望：如有 GPT 相关论文在库中，不应被返回；正确返回开源 LLaMA 论文。
    """
    handler = RetrievalHandler()
    task = ChallengeTaskInput(
        case_id="B-NEG-03",
        function="Literature_Retrieval",
        title="大语言模型检索",
        input="搜索大语言模型相关论文，但不要包含 GPT",
        materials=[],
        constraints=["严禁返回 GPT 系列文献"],
        expected_output="非 GPT 大模型文献",
        output_schema_ref="Literature_Retrieval"
    )

    with patch.object(handler.llm, "chat_completion", side_effect=_mock_firewall_llm_response):
        result = handler.handle(task, "test_negation_session_03")

    found_papers = [p["filename"] for p in result["papers"]]
    print(f"Query 3 Found papers: {found_papers}")

    for p in found_papers:
        assert "GPT" not in p, f"违规包含 GPT 文献: {p}"

    assert "LLaMA_Open_Foundation_Model.pdf" in found_papers


def test_negation_firewall_query_4_exclude_node_classification(mock_retrieval_papers_env):
    """
    查询 4：「所有关于图神经网络的论文中不涉及节点分类的」
    期望：节点分类相关论文被正确排除，命中整图分类论文。
    """
    handler = RetrievalHandler()
    task = ChallengeTaskInput(
        case_id="B-NEG-04",
        function="Literature_Retrieval",
        title="图神经网络非节点分类任务",
        input="所有关于图神经网络的论文中不涉及节点分类的",
        materials=[],
        constraints=["排除节点分类相关任务"],
        expected_output="非节点分类 GNN 论文",
        output_schema_ref="Literature_Retrieval"
    )

    with patch.object(handler.llm, "chat_completion", side_effect=_mock_firewall_llm_response):
        result = handler.handle(task, "test_negation_session_04")

    found_papers = [p["filename"] for p in result["papers"]]
    print(f"Query 4 Found papers: {found_papers}")

    for p in found_papers:
        assert "Node_Classification" not in p, f"违规包含节点分类文献: {p}"
        assert "节点分类" not in p, f"违规包含节点分类文献: {p}"

    assert "GNN_Graph_Classification.pdf" in found_papers


def test_negation_firewall_query_5_positive_control(mock_retrieval_papers_env):
    """
    查询 5：（正常查询，对照组）「Transformer 注意力机制相关论文」
    期望：正常检索，不受 negation 逻辑误伤，准确返回 Transformer 论文。
    """
    handler = RetrievalHandler()
    task = ChallengeTaskInput(
        case_id="B-POS-05",
        function="Literature_Retrieval",
        title="Transformer 注意力机制文献检索",
        input="Transformer 注意力机制相关论文",
        materials=[],
        constraints=[],
        expected_output="Transformer 相关文献",
        output_schema_ref="Literature_Retrieval"
    )

    with patch.object(handler.llm, "chat_completion", side_effect=_mock_firewall_llm_response):
        result = handler.handle(task, "test_negation_session_05")

    found_papers = [p["filename"] for p in result["papers"]]
    print(f"Query 5 Found papers: {found_papers}")

    assert "Transformer_Attention_Model.pdf" in found_papers
    assert "Random_Forest_Tabular.pdf" not in found_papers
