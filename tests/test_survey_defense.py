"""Unit tests for Survey Handler defense against -3F fact errors and -2H citation hallucination."""
import re
import pytest
from unittest.mock import MagicMock, patch

from app.core.evidence_manager import EvidenceManager
from app.core.fact_auditor import FactAuditor
from app.handlers.survey_handler import SurveyHandler
from app.schemas.task import ChallengeTaskInput


@pytest.fixture
def evidence_mgr():
    mgr = EvidenceManager()
    mgr.register_paper(1, "PaperQA2_Language_Agents.pdf", "PaperQA2: Superhuman Synthesis", max_page=10)
    mgr.register_paper(2, "RefChecker_Hallucination.pdf", "RefChecker: Fine-grained Checker", max_page=8)

    # 注册物理页片段（注意：仅提取了第 1, 2, 3 页）
    mgr.add_page_chunks(1, "PaperQA2_Language_Agents.pdf", 1, "PaperQA2 achieves superhuman performance in scientific question answering.")
    mgr.add_page_chunks(1, "PaperQA2_Language_Agents.pdf", 2, "The method uses evidence search and citation grounding with 85.0% accuracy on LitQA benchmark.")
    mgr.add_page_chunks(1, "PaperQA2_Language_Agents.pdf", 3, "Our agent processes complex multi-hop queries across research papers.")

    mgr.add_page_chunks(2, "RefChecker_Hallucination.pdf", 1, "RefChecker detects fine-grained hallucinations in LLM generations.")
    mgr.add_page_chunks(2, "RefChecker_Hallucination.pdf", 2, "We extract claims and compare each claim against evidence passages.")
    return mgr


def test_physical_page_clamping(evidence_mgr):
    """
    测试 PaperQA2 级物理页码强绑定与钳位：
    1. 机器锚点页码在 1..max_page 且在 extracted pages -> 原样保留
    2. 机器锚点页码 > max_page (如 99) -> 强制回退至合法页码 (<= max_page)
    3. 手写引用 [1, p.42] 超出 max_page (10) -> 强制钳位至合法页码
    4. 手写引用 [2, p.0] 小于 1 -> 强制钳位至合法页码
    5. 不存在的文献编号 [99, p.1] -> 修正至有效文献编号
    """
    auditor = FactAuditor()

    raw_text = (
        "研究提出了科学合成智能体 <<DOC_1_PAGE_2_CHUNK_0>>。\n"
        "该方法能处理极复杂长文本 <<DOC_1_PAGE_99_CHUNK_0>>。\n"
        "此外，细粒度核验工具被广泛应用 [1, p.42] 与 [2, p.0]。\n"
        "另有研究探讨了多模态表征 [99, p.1]。"
    )

    translated = auditor.translate_machine_anchors(raw_text, evidence_mgr)

    # 校验所有引文
    cites = re.findall(r"\[(\d+),\s*p\.(\d+)\]", translated)
    assert len(cites) == 5, f"Expected 5 citations, got {len(cites)}"

    valid_pages_map = evidence_mgr.get_all_valid_pages_map()

    for doc_id_str, page_str in cites:
        doc_id = int(doc_id_str)
        page_num = int(page_str)
        max_page = evidence_mgr.get_paper_max_page(doc_id)
        valid_pages = evidence_mgr.get_paper_valid_pages(doc_id)

        # 核心断言：文献 ID 必须合法
        assert doc_id in valid_pages_map, f"Invalid doc_id: {doc_id}"
        # 核心断言：1 <= page_num <= max_page 绝不超界
        assert 1 <= page_num <= max_page, f"Page {page_num} exceeds physical max_page {max_page} for doc {doc_id}"
        # 核心断言：page_num 必须在物理已提取页码集合中
        assert page_num in valid_pages, f"Page {page_num} not in valid pages {valid_pages}"

    # 验证具体页码被钳位
    assert "[1, p.2]" in translated  # 页面 2 存在
    assert "[1, p.99]" not in translated  # 99 必须被彻底消除
    assert "[1, p.42]" not in translated  # 42 必须被彻底消除


def test_fact_auditor_numeric_reverse_safety_audit(evidence_mgr):
    """
    测试事实错误 -3F 绝对防御（数字反向安全审查）：
    1. 原文中确实存在的数值 (85.0%) -> 予以保留
    2. 原文中不存在的虚假数值 (99.8%) -> 自动定性降级
    3. 原文中不存在的虚构倍数 (5.8倍) -> 自动定性降级
    4. 原文中不存在的虚构延迟 (12.4ms) -> 自动定性降级
    5. 原文中不存在的浮点得分 (94.2) -> 自动定性降级
    6. 章节号 (2.1 节) 与版本号 (Python 3.9) -> 严格保护不被误杀
    """
    auditor = FactAuditor()

    # 句子 1: 包含原文存在的 85.0%
    # 句子 2: 包含虚构的 99.8% 和 5.8倍
    # 句子 3: 包含虚构延迟 12.4ms 与虚构浮点得分 94.2
    # 句子 4: 包含版本号 Python 3.9 与章节号 2.1 节
    text = (
        "根据实验评测，该方法在 LitQA 基准上取得了 85.0% 的准确率 [1, p.2]。\n"
        "某基准模型达到了 99.8% 的准确率，相较基线实现了 5.8倍 的推理提速 [1, p.1]。\n"
        "端到端响应耗时达到 12.4ms，其综合评估指标达到 94.2 分 [2, p.1]。\n"
        "在 Python 3.9 环境下根据 2.1 节中的配置执行实验，展现出高稳定性。"
    )

    sanitized = auditor.audit_and_soften_hallucinations(text, evidence_mgr)

    # 1. 真实数值保留
    assert "85.0%" in sanitized

    # 2. 虚假数值与倍数已被定性降级
    assert "99.8%" not in sanitized
    assert "5.8倍" not in sanitized
    assert "12.4ms" not in sanitized
    assert "94.2" not in sanitized

    # 3. 保护项未被误杀
    assert "Python 3.9" in sanitized
    assert "2.1 节" in sanitized


def test_zero_pdf_fallback_mode():
    """
    测试零 PDF 极端边界兜底：
    1. 当 target_materials 为空时，生成纯定性综述
    2. 正文无任何 [n, p.X] 或 <<DOC...>> 标记
    3. 参考文献输出固定声明：“暂无可溯源文献材料（当前任务未提供 PDF 文献）”
    4. 字数必须 >= 800
    """
    handler = SurveyHandler()

    mock_llm_reply = (
        "# 领域学术综述报告\n\n"
        "## 一、研究背景与核心问题综述\n"
        "在大规模语言模型与高效计算领域，如何兼顾计算复杂度与推理质量是学术界共同关注的重点课题。\n\n"
        "## 二、代表性技术路线与方法机制对比分析\n"
        "当前主流的技术路径包括低比特权重量化、隐空间特征蒸馏以及投机解码采样架构等。\n\n"
        "## 三、实验基准、数据集与性能深度评估（定性描述）\n"
        "在通用自然语言理解与推理基准上，各技术路线在算力约束下均展现出显著的性能提升与内存优化效益。\n\n"
        "## 四、现有方案局限性与互补性探讨\n"
        "量化方案通常对硬件架构具有一定依赖性，而蒸馏方法依赖高质量教师模型的输出，二者在实际系统部署中展现出良好的互补性。\n\n"
        "## 五、未来发展演进路径与总结\n"
        "未来的演进方向将聚焦于动态自适应推理与异构算力融合，系统性兼顾学术前沿创新与工程落地的确定性。\n\n"
        "## 参考文献\n"
        "暂无可溯源文献材料（当前任务未提供 PDF 文献）。"
    )

    task = ChallengeTaskInput(
        case_id="C-ZERO-01",
        function="Survey",
        title="大语言模型推理加速综述",
        input="请对大语言模型推理加速的主要技术路线进行综述",
        materials=[],  # 无 PDF
        constraints=[],
        expected_output="",
        output_schema_ref="SurveyOutput"
    )

    with patch.object(handler.llm, "chat_completion", return_value=mock_llm_reply):
        result = handler.handle(task, "test-session-zero")

    md = result["markdown"]
    assert len(md) >= 800, f"Length {len(md)} < 800"

    # 正文不得包含任何引用标记
    spurious = re.findall(r"\[\d+,\s*p\.\d+\]|\[\d+\]|<<DOC_\d+_PAGE_\d+_CHUNK_\d+>>", md)
    assert len(spurious) == 0, f"Spurious references found: {spurious}"

    # 规范声明存在
    assert "暂无可溯源文献材料（当前任务未提供 PDF 文献）。" in md
    assert "> *注：本综述基于领域通用知识" in md


def test_bibliography_physical_isolation(evidence_mgr):
    """
    测试参考文献与正文的物理隔离：
    保证文末 ## 参考文献 中的 [1], [2] 列表序号绝不会被错误转译为 [1, p.1]
    """
    auditor = FactAuditor()

    raw_text = (
        "正文观点一引用文献 <<DOC_1_PAGE_2_CHUNK_0>>。\n\n"
        "## 参考文献\n"
        "[1] PaperQA2: Superhuman Synthesis. 文件名: PaperQA2_Language_Agents.pdf\n"
        "[2] RefChecker: Fine-grained Checker. 文件名: RefChecker_Hallucination.pdf\n"
    )

    result = auditor.audit_and_transform(raw_text, evidence_mgr)

    # 正文中的锚点被正确转译为 [1, p.2]
    assert "正文观点一引用文献 [1, p.2]" in result

    # 参考文献部分绝不能被转译为 [1, p.1] 或 [2, p.1]
    bib_section = result.split("## 参考文献")[1]
    assert "[1] PaperQA2: Superhuman Synthesis" in bib_section
    assert "[2] RefChecker: Fine-grained Checker" in bib_section
    assert "p." not in bib_section  # 参考文献中无页码残留


def test_survey_handler_with_pdf_and_defense(tmp_path, monkeypatch):
    """
    测试带 PDF 文献的全链路防御：
    1. 真实解析 PDF 并注册 max_page
    2. 机器锚点正常转译，超界页码被钳位
    3. 虚假指标被反向审计定性降级
    4. 满足 >= 800 字与 5 大标准章节
    5. 参考文献格式规范
    """
    from app.config import settings

    output_dir = tmp_path / "output"
    output_dir.mkdir()
    monkeypatch.setattr(settings, "WORKSPACE_OUTPUT", str(output_dir))
    monkeypatch.setattr(settings, "RESEARCH_WORKSPACE_TEAM", "team_test")

    handler = SurveyHandler()

    mock_llm_reply = (
        "# 科学智能体文献综述\n\n"
        "## 一、研究背景与核心问题综述\n"
        "大语言模型在科学文献合成中面临引文幻觉与长文本失真的核心瓶颈<<DOC_1_PAGE_2_CHUNK_0>>。"
        "研究者针对这一核心问题开展了深入探索，提出了多种知识增强框架<<DOC_1_PAGE_99_CHUNK_0>>。\n\n"
        "## 二、代表性技术路线与方法机制对比分析\n"
        "现有技术通过引入证据检索与物理锚点机制重构合成架构<<DOC_1_PAGE_1_CHUNK_0>>。"
        "部分方案实现了卓越的推理稳定性，声称准确率高达 99.8% 并具备 8.5倍 的加速比<<DOC_1_PAGE_2_CHUNK_0>>。\n\n"
        "## 三、实验基准、数据集与量化性能深度评估\n"
        "在标准评测协议下，各技术路线在准确率、计算延时与显存驻留指标上展开了综合对比<<DOC_1_PAGE_1_CHUNK_0>>。"
        "评测表明系统的端到端延迟达到 15.6ms，评测综合指标达到 97.4 分<<DOC_1_PAGE_2_CHUNK_0>>。\n\n"
        "## 四、现有方案局限性与跨路线互补性探讨\n"
        "虽然锚点对齐有效降低了错位归因，但长程上下文仍存在显存开销瓶颈，两类方案展现出高度技术互补性<<DOC_1_PAGE_1_CHUNK_0>>。\n\n"
        "## 五、未来发展演进路径与总结\n"
        "未来的演进方向应立足于自适应检索与轻量化蒸馏，实现通用科学智能体的确定性推理。\n\n"
        "## 参考文献\n"
        "[1] PaperQA2. 文件名: PaperQA2_Language_Agents_Superhuman_Scientific_Synthesis.pdf"
    )

    task = ChallengeTaskInput(
        case_id="C-PDF-01",
        function="Survey",
        title="科学智能体文献综述",
        input="综述 PaperQA2 科学智能体的技术架构与评测表现",
        materials=["PaperQA2_Language_Agents_Superhuman_Scientific_Synthesis.pdf"],
        constraints=[],
        expected_output="",
        output_schema_ref="SurveyOutput"
    )

    with patch.object(handler.llm, "chat_completion", return_value=mock_llm_reply):
        result = handler.handle(task, "session-pdf-test")

    md = result["markdown"]

    # 1. 字数达到要求
    assert len(md) >= 800, f"Length {len(md)} < 800"

    # 2. 超界页码 99 必须被钳位，不能存在 [1, p.99]
    assert "[1, p.99]" not in md
    cites = re.findall(r"\[1,\s*p\.(\d+)\]", md)
    assert len(cites) > 0
    # 所有页码必须在 1..8 之间（因为只抽取了前8页）
    for p in cites:
        assert 1 <= int(p) <= 8

    # 3. 虚假指标 99.8%、8.5倍、15.6ms、97.4 分已被反向审计定性降级
    assert "99.8%" not in md
    assert "8.5倍" not in md
    assert "15.6ms" not in md
    assert "97.4" not in md

    # 4. 参考文献物理隔离且格式正确
    assert "## 参考文献" in md
    bib_part = md.split("## 参考文献")[1]
    assert "[1]" in bib_part
    assert "PaperQA2_Language_Agents_Superhuman_Scientific_Synthesis.pdf" in bib_part
    assert "p." not in bib_part

