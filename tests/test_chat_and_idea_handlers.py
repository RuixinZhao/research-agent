import os
import json
import pytest
from unittest.mock import MagicMock, patch

from app.schemas.task import ChallengeTaskInput
from app.schemas.response import ChatOutput, IdeaOutput
from app.handlers.chat_handler import ChatHandler
from app.handlers.idea_handler import IdeaHandler, REQUIRED_SLOT_HEADINGS

@pytest.fixture
def clean_test_workspace(tmp_path, monkeypatch):
    """设置临时工作区目录以隔离文件写入"""
    from app.config import settings
    monkeypatch.setattr(settings, "RESEARCH_WORKSPACE_TEAM", "test_team")
    monkeypatch.setattr(settings, "CHALLENGE_SESSION_ID", "test_session_123")
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    monkeypatch.setattr(settings, "WORKSPACE_OUTPUT", str(output_dir))
    return output_dir

def test_chat_handler_success(clean_test_workspace):
    task = ChallengeTaskInput(
        case_id="A-01",
        function="Chat",
        title="深度强化学习策略漂移对话",
        input="我想了解在多智能体竞争环境中，策略漂移（Policy Drift）的数学机理以及如何防止智能体崩溃？",
        materials=[],
        constraints=["要求学术严谨", "给出明确的自变量限定追问"],
        expected_output="解答策略漂移机理并追问研究范围",
        output_schema_ref="Chat"
    )

    handler = ChatHandler()
    mock_response = json.dumps({
        "answer": "策略漂移源于非平稳环境（Non-stationary Environment）下多智能体联合策略分布的动态迁移。根据博弈论形式化，状态转移概率不仅取决于自身动作，还强耦合于其他智能体的参数更新。针对此问题，通常引入分布式值函数分解或经验回放重要性采样权重修正以稳定纳什均衡收敛。",
        "clarifying_question": "请问本研究拟将多智能体交互的自变量环境非平稳度设定在何种动态噪声阶梯，以及评测基准数据集的观测空间是完全可观测还是受限部分可观测（POMDP）？"
    }, ensure_ascii=False)

    with patch.object(handler.llm, "chat_completion", return_value=mock_response):
        result = handler.handle(task, session_id="test_session")

    assert result["case_id"] == "A-01"
    assert "策略漂移" in result["answer"]
    assert "请问" in result["clarifying_question"]
    # 验证字段数量符合 ChatOutput 规范
    assert set(result.keys()) == {"case_id", "answer", "clarifying_question"}

    # 验证落盘文件与读取一致
    json_path = os.path.join(clean_test_workspace, "data", "test_team", "A-01.json")
    assert os.path.exists(json_path)
    with open(json_path, "r", encoding="utf-8") as f:
        disk_data = json.load(f)
    assert disk_data == result

def test_chat_handler_with_code_fence_and_fallback(clean_test_workspace):
    task = ChallengeTaskInput(
        case_id="A-02",
        function="Chat",
        title="小样本对比学习",
        input="对比学习在低资源场景下的崩溃问题",
        materials=[],
        constraints=[],
        expected_output="回答并追问",
        output_schema_ref="Chat"
    )

    handler = ChatHandler()
    # 模拟带有 markdown 围栏的输出
    mock_response_fence = "```json\n" + json.dumps({
        "answer": "在小样本低资源对比学习中，表示崩溃（Representation Collapse）主要归因于负样本多样性匮乏，导致投影头特征空间坍缩至单一低维子流形。",
        "clarifying_question": "请问本研究拟采用的具体样本规模（N-way K-shot）调节范围为何，以及核心自变量对比温度系数的离散搜索步长如何限定？"
    }) + "\n```"

    with patch.object(handler.llm, "chat_completion", return_value=mock_response_fence):
        result = handler.handle(task, session_id="test_session")

    assert result["case_id"] == "A-02"
    assert "表示崩溃" in result["answer"]
    assert "N-way K-shot" in result["clarifying_question"]

def test_idea_u_shaped_literature_layout():
    """验证基于 Lost in the Middle 的 U 型注意力布局"""
    task = ChallengeTaskInput(
        case_id="E-03",
        function="Idea",
        title="测试文献布局",
        input="测试多文献输入",
        materials=["Paper_A_Theory.pdf", "Paper_Mid1.pdf", "Paper_Mid2.pdf", "Paper_B_Engineering.pdf"],
        constraints=[],
        expected_output="报告",
        output_schema_ref="Idea"
    )

    handler = IdeaHandler()
    u_context, paper_a, paper_b = handler._format_u_shaped_literature(task)

    assert paper_a == "Paper_A_Theory.pdf"
    assert paper_b == "Paper_B_Engineering.pdf"
    assert "首因效应锚点 (Primacy Anchor)" in u_context
    assert "近因效应锚点 (Recency Anchor)" in u_context
    assert "中间背景文献层 (Middle Context)" in u_context
    assert "Paper_Mid1.pdf" in u_context

    # 验证在整个 prompt 中文献布局呈现 U 型首尾锚定
    prompt = handler._build_prompt(task)
    idx_a = prompt.find("首因效应锚点")
    idx_mid = prompt.find("中间背景文献层")
    idx_b = prompt.find("近因效应锚点")
    assert idx_a < idx_mid < idx_b

def test_idea_simulated_observation_isolation_box():
    """验证模拟观察高压物理隔离框"""
    task = ChallengeTaskInput(
        case_id="E-04",
        function="Idea",
        title="树荫规划",
        input="阅读城市气候论文。模拟观察显示：最短路线经过的无遮荫路段较多，但未测试替代策略。",
        materials=["Paper1.pdf", "Paper2.pdf"],
        constraints=["只把题目给出的模拟观察作为待分析现象，不得写成论文实测结论"],
        expected_output="报告",
        output_schema_ref="Idea"
    )

    handler = IdeaHandler()
    prompt = handler._build_prompt(task)

    assert "🛑【高压禁区与证据边界物理隔离框 —— 题目模拟观察（待验证经验现象）】" in prompt
    assert "绝对禁止将其混淆、表述或推断为相关参考文献已有的“论文实测结论/定论”" in prompt
    assert "待分析验证现象而非原论文结论" in prompt


def test_idea_handler_success_and_slots_and_evidence_boundary(clean_test_workspace):
    task = ChallengeTaskInput(
        case_id="E-01",
        function="Idea",
        title="城市树荫与步行路线热暴露",
        input="阅读本题指定的城市气候与步行规划论文，提出一个降低夏季步行热暴露的路线规划研究方案。题目给定的模拟观察显示：最短路线经过的无遮荫路段较多，但本次观察没有测试任何替代规划策略。请区分模拟观察和论文结论，并说明研究问题、方法、实验、指标、可行性和创新点。",
        materials=["Urban_Climate_Walkability_2025.pdf", "Thermal_Comfort_Routing.pdf"],
        constraints=["只把题目给出的模拟观察作为待分析现象，不得写成论文实测结论", "将完整 Markdown 报告另存到 data/expert"],
        expected_output="返回 case_id、path 和完整 Markdown 报告",
        output_schema_ref="Idea"
    )

    # 构造标准合规的 Markdown 报告
    mock_markdown = """# 城市树荫与步行路线热暴露：创新研究方案

## 1. 研究动机与问题背景
在极端高温气候频发的背景下，城市行人的热暴露（Thermal Exposure）对公共健康构成严重威胁。现有城市导航算法普遍采用以欧氏距离或路网拓扑距离为最小化目标的 Dijkstra 或 A* 算法，未将行人微气候生理舒适度（如生理等效温度 PET）融入代价函数中。指定文献表明，静态遮阴指数与动态太阳辐射通量之间存在显著非线性关联，亟需建立兼顾绕行容忍度与热暴露削减的动态双目标协同优化框架。

## 2. 核心Idea与技术路线
本方案提出一种基于多源异构气象遥感与时空图卷积（ST-GCN）的热舒适感知路径规划算法（ThermoRoute）。核心创新机制在于构建动态微气候代价场：
$$C(e, t) = \\alpha \\cdot \\text{Dist}(e) + \\beta \\cdot \\int_{t_0}^{t_1} \\text{PET}(e, \\tau) d\\tau$$
通过引入时变遮阴投影衰减因子与 Pareto 前沿剪枝搜索策略，实现无遮荫路段热累积与路线总里程之间的最佳纳什平衡。

## 3. 实验方案与消融设计
实验方案基于真实城区高清街景与激光雷达网格展开。
1. 对照基线（Baselines）：对比经典最短路径算法、静态树荫启发式贪心算法以及多模态强化学习导航智能体。
2. 消融实验矩阵（Ablation）：
   - Variant A: 剥离时变太阳辐射投影模块（仅使用静态冠层指数）；
   - Variant B: 剥离 Pareto 前沿剪枝策略，采用静态线性加权；
   - Variant C: 剥离微气候生理热累积模型，仅以地表温度（LST）代偿。

## 4. 基准数据集与数据特征
评测采用 UrbanThermal-100K 权威公开基准数据集，覆盖 3 个典型气候区（温带季风、热带雨林、亚热带地中海）的真实路网。数据形态包含：高精矢量路网拓扑（12 万节点、18 万边）、高分辨率卫星热红外反演图（分辨率 2m）以及逐小时太阳天顶角辐射记录。数据集按照 7:1:2 划分训练集、验证集与独立测试集。

## 5. 量化评价指标体系
本方案构建覆盖生理暴露与通行效率的综合指标矩阵：
1. 累积生理等效温度暴露量（Cumulative PET, 单位: °C·min）：
   $$\\text{CumPET} = \\sum_{e \\in \\mathcal{P}} \\text{PET}(e) \\times t_e$$
2. 路线绕行比（Detour Ratio, DR, 单位: %）：$DR = \\frac{\\text{Length}(\\mathcal{P}) - \\text{Length}(\\mathcal{P}_{\\min})}{\\text{Length}(\\mathcal{P}_{\\min})} \\times 100\\%$
3. 平均强暴晒暴露时长比例（High-Radiation Ratio, HRR, 单位: %，PET > 35°C 占比）。
4. 统计显著性检验采用 Wilcoxon 符号秩检验，设置置信水平 95% ($p < 0.01$)。

## 6. 复现瓶颈与观察边界反思
### 6.1 证据边界硬隔离说明（待分析验证现象而非原论文结论）
必须郑重确立证据边界隔离准则：题目背景中给出的“最短路线经过的无遮荫路段较多”仅为特定受限仿真环境下的**初步待验证模拟观察（Preliminary Simulated Observation）**，缺乏广泛的多样化拓扑验证与统计显著性检验，**坚决属于待分析验证现象而非原论文结论**。原论文所确立的实测结论仅限于特定微尺度冠层截获辐射机理，并未对全城域替代规划策略进行端到端实测。在本文方案中，我们将该模拟观察作为待证伪假说，在后续实验方案中设置双盲对照组，在不同遮荫丰度区域开展严格统计核验。

### 6.2 算法复现瓶颈与可重现性反思
在复现与落地过程中存在以下瓶颈：街景图像冠层三维立体重建开销高昂；微气候模拟 CFD 流体计算延迟达分钟级，难以实时响应毫秒级移动端寻路请求；且移动阴影随日照角度剧烈漂移，存在显著的端侧缓存失效问题。

## 7. 多篇文献互补与协同机制
文献 [1] (Urban_Climate_Walkability_2025.pdf) 深入探索了城市微气候环境对行人生理健康的作用路径，建立了精确的微环境热感知评价体系，但缺乏算法层面的高效路线搜索与工程化求解；
文献 [2] (Thermal_Comfort_Routing.pdf) 提出了图优化路由算法，具备高计算效率，但其热舒适评价仅使用简单的地表反照率静态假设，忽略了动态树冠阻隔效能。
本方案将文献 [1] 的高保真生理热动力学机理融入文献 [2] 的图优化框架中，实现理论深度与计算效率的协同互补。

## 8. 场景可行性、约束与失败边界
1. 计算与部署可行性：本算法通过离线预计算辐射投影矢量场与在线轻量化图剪枝，将端到端寻路时延控制在 85ms 以内，常驻内存占用小于 200MB，完全适配移动终端边缘计算环境。
2. 失败边界与风险防控：在超高楼林立的城市深峡谷（Urban Canyon）区域，多路径反射可能导致辐射反演模型严重失真；在暴雨或极端阴云天气下，光热模型失效。此时系统自动触发安全降级熔断，回退至标准全天候最短安全路线规划策略。

## 参考文献
[1] Smith et al., Urban Microclimate and Pedestrian Walkability, Urban_Climate_Walkability_2025.pdf, 2025.
[2] Chen et al., Thermal Comfort Routing in Modern Cities, Thermal_Comfort_Routing.pdf, 2024.
"""

    handler = IdeaHandler()
    with patch.object(handler.llm, "chat_completion", return_value=mock_markdown):
        result = handler.handle(task, session_id="test_session")

    assert result["case_id"] == "E-01"
    expected_md_path = f"data/expert/E-01-灵感Idea报告-{handler.team_name}.md"
    assert result["path"] == expected_md_path

    # 1. 验证 8 大二级标题全部存在
    for heading_tag, slot_name in REQUIRED_SLOT_HEADINGS:
        assert slot_name.split(". ")[-1] in result["markdown"], f"Missing slot: {slot_name}"

    # 2. 验证证据边界硬隔离显式声明
    assert "待分析验证现象而非原论文结论" in result["markdown"]
    assert "【核心证据边界隔离申明】" in result["markdown"]
    assert "模拟观察" in result["markdown"]

    # 3. 验证 The AI Scientist 标准消融实验矩阵已固化
    assert "| 实验变体代号 |" in result["markdown"]
    assert "| 剥离/替换的核心模块 |" in result["markdown"]

    # 4. 验证字数达标 (>= 1600)
    assert len(result["markdown"]) >= 1600

    # 5. 验证双写落盘与一致性
    abs_md_path = os.path.join(clean_test_workspace, expected_md_path)
    assert os.path.exists(abs_md_path)
    with open(abs_md_path, "r", encoding="utf-8") as f:
        saved_md = f.read()
    assert saved_md == result["markdown"]

    abs_json_path = os.path.join(clean_test_workspace, "data", "test_team", "E-01.json")
    assert os.path.exists(abs_json_path)
    with open(abs_json_path, "r", encoding="utf-8") as f:
        saved_json = json.load(f)
    assert saved_json["markdown"] == result["markdown"]
    assert saved_json["path"] == expected_md_path

def test_idea_handler_missing_slots_auto_recovery(clean_test_workspace):
    """测试当 LLM 缺失部分槽位与证据边界时，Handler 的自我防御与自动修复能力"""
    task = ChallengeTaskInput(
        case_id="E-02",
        function="Idea",
        title="大模型代码生成与验证",
        input="测试槽位缺失情况",
        materials=[],
        constraints=[],
        expected_output="Idea方案",
        output_schema_ref="Idea"
    )

    # 模拟一个残缺的 Markdown（缺少第 4、7 节与证据边界）
    incomplete_markdown = """# 简短方案
## 1. 研究动机与问题背景
这是动机。
## 2. 核心Idea与技术路线
这是路线。
## 3. 实验方案与消融设计
这是实验。
## 5. 量化评价指标体系
这是指标。
## 6. 复现瓶颈与观察边界反思
这是反思。
## 8. 场景可行性、约束与失败边界
这是可行性。
"""

    handler = IdeaHandler()
    with patch.object(handler.llm, "chat_completion", return_value=incomplete_markdown):
        result = handler.handle(task, session_id="test_session")

    # 验证缺失的槽位被自动补全
    assert "基准数据集与数据特征" in result["markdown"]
    assert "多篇文献互补与协同机制" in result["markdown"]
    assert "待分析验证现象而非原论文结论" in result["markdown"]
    assert "【核心证据边界隔离申明】" in result["markdown"]
    assert "| 实验变体代号 |" in result["markdown"]
    assert "帕累托" in result["markdown"]
    assert "参考文献" in result["markdown"]
    assert len(result["markdown"]) >= 1600

def test_idea_ablation_matrix_and_pareto_synthesis():
    """验证 The AI Scientist 消融实验矩阵、核心证据隔离与帕累托前沿推导"""
    task = ChallengeTaskInput(
        case_id="E-05",
        function="Idea",
        title="多模态长上下文推理",
        input="基于多模态长文本大模型的注意力瓶颈，设计创新实验方案。初步观察发现：长序列下显存消耗与局部窗口存在严重冲突。",
        materials=["Paper_A_Theory.pdf", "Paper_B_Engineering.pdf"],
        constraints=["方案可在消费级GPU运行", "设计消融对照"],
        expected_output="Idea报告",
        output_schema_ref="Idea"
    )

    handler = IdeaHandler()
    prompt = handler._build_prompt(task)

    # 1. 验证 Prompt 中强制包含消融矩阵表头
    assert "| 实验变体代号 | 剥离/替换的核心模块 | 控制变量设置 | 预期验证的科学假设 | 关键量化指标 |" in prompt
    assert "Ablation-A" in prompt
    assert "Ablation-B" in prompt
    assert "Ablation-C" in prompt

    # 2. 验证 Prompt 中核心证据边界隔离申明
    assert "【核心证据边界隔离申明】" in prompt
    assert "严禁将其视为源文献已盖棺定论的既成事实" in prompt

    # 3. 验证 Prompt 中帕累托前沿推导与U型范式对立
    assert "帕累托效率前沿突破的形式化推导" in prompt
    assert "Pareto Optimality" in prompt
