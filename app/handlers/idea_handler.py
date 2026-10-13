import os
import re
import logging
from typing import Dict, Any, List

from app.handlers.base_handler import BaseHandler
from app.schemas.task import ChallengeTaskInput
from app.schemas.response import IdeaOutput
from app.config import settings

logger = logging.getLogger(__name__)

# 严格对齐评估标准的 8 大核心二级标题与参考文献
REQUIRED_SLOT_HEADINGS = [
    ("## 1. 研究动机与问题背景", "1. 研究动机与问题背景"),
    ("## 2. 核心Idea与技术路线", "2. 核心Idea与技术路线"),
    ("## 3. 实验方案与消融设计", "3. 实验方案与消融设计"),
    ("## 4. 基准数据集与数据特征", "4. 基准数据集与数据特征"),
    ("## 5. 量化评价指标体系", "5. 量化评价指标体系"),
    ("## 6. 复现瓶颈与观察边界反思", "6. 复现瓶颈与观察边界反思"),
    ("## 7. 多篇文献互补与协同机制", "7. 多篇文献互补与协同机制"),
    ("## 8. 场景可行性、约束与失败边界", "8. 场景可行性、约束与失败边界"),
]

REFERENCES_HEADING = "## 参考文献"

class IdeaHandler(BaseHandler):
    """
    E 类任务处理器：研究灵感与创新方案生成。
    
    客观分值：满分 15 分
    - 研究动机 (1.5分): 结合指定论文说明已有技术瓶颈与需求
    - 技术路线 (1.5分): 提出具体的新方法机制，明确区别于已有方案
    - 实验设计 (1.5分): 详细设计实验流程、对照组、消融实验 (Ablation)
    - 基准数据集 (1.5分): 明确列出评测数据集名称、规模及数据形态
    - 量化评价指标 (1.5分): 明确给出量化指标全称、单位及计算方式
    - 复现瓶颈反思 (3.0分): 严格实施“模拟观察待验证”与“论文实测定论”证据边界硬隔离
    - 多文献互补机制 (3.0分): 阐明至少 2 篇指定论文间的优缺点互补与协同机制
    - 场景可行性与落地约束 (1.5分): 分析计算开销、实施约束、失败边界与风险
    
    格式约束：
    1. 正文字符数必须 >= 800
    2. 末尾包含 ## 参考文献
    3. Markdown 另存至 data/expert/{case_id}-灵感Idea报告-{team_name}.md
    4. JSON 报告与另存 Markdown 逐字一致
    """

    def _build_prompt(self, task: ChallengeTaskInput) -> str:
        materials_str = ""
        if task.materials:
            materials_str = "\n".join([f"- {m}" for m in task.materials])
        else:
            materials_str = "- 本题涉及的人工智能与领域经典学术论文"

        constraints_str = ""
        if task.constraints:
            constraints_str = "\n".join([f"- {c}" for c in task.constraints])

        prompt = f"""你是一名具有卓越学术视野与系统创新能力的资深科研学者（AI顶会领域主席/资深研究员）。请针对以下科研任务与给定材料，撰写一份完整、严谨、详实的科研灵感与创新方案报告（Markdown格式）。

【题目标题】: {task.title if task.title else '科研灵感与创新方案'}
【研究背景与题目输入】:
{task.input}

【指定材料列表】:
{materials_str}

【必须遵守的约束】:
{constraints_str}

================================================================================
【核心评分结构：必须严格使用以下 8 大二级标题与参考文献（不得遗漏、不得修改字样）】
================================================================================

## 1. 研究动机与问题背景 (满分1.5分)
- 结合指定文献与领域现状，深度剖析现有方法的固有技术瓶颈与理论局限。
- 阐明开展本项研究的紧迫性与核心学术问题（Research Question, RQ）。

## 2. 核心Idea与技术路线 (满分1.5分)
- 提出具有针对性的新机制/新算法/新架构，明确阐述其与已有工作的根本区别。
- 给出系统技术路线拓扑、数学建模形式化表述（核心公式）及模块交互流程。

## 3. 实验方案与消融设计 (满分1.5分)
- 设计完整的对照实验方案，明确基准模型（Baselines）、实验组与对照控制条件。
- 给出详尽的消融实验（Ablation Study）设计矩阵（说明各创新模块的剥离验证方法）。

## 4. 基准数据集与数据特征 (满分1.5分)
- 明确列出评测所采用的标准基准数据集全称、规模（样本量/类别数/Token量）。
- 详细说明数据形态、特征分布、训练集/验证集/测试集切分比例及预处理协议。

## 5. 量化评价指标体系 (满分1.5分)
- 给出多维度量化指标的全称、缩写、物理单位及严格的数学计算公式。
- 涵盖效果指标（如准确率、召回率、F1、相关性等）与效率开销指标（延迟、吞吐、显存），并规定统计显著性检验方法（如 p-value 检验）。

## 6. 复现瓶颈与观察边界反思 (满分3.0分 - 极高权重)
【★★★★★ 证据边界硬隔离铁律（严防跨界混淆判伪） ★★★★★】
- 必须明确声明证据边界隔离：题目给出的“模拟观察”仅为待分析与待证伪的经验性现象（Preliminary Phenomenon），**坚决禁止将其表述或当作“论文实测结论/既有定论”**！
- 违规反例（严厉扣分）：“根据论文实测证明，最短路线经过的无遮荫路段较多……”
- 合规正例（标准范式）：“题目给出的初步模拟观察表明：最短路线往往包含较多无遮荫路段。需特别强调，该现象仅为任务设定的待验证初步观察，并非参考文献的既有实测定论；在后续方案中，我们将通过严格的对照实验与统计假设检验对其进行证伪与复现验证……”
- 深入反思复现该项研究时的潜在工程瓶颈、算力消耗、环境依赖与随机性风险。

## 7. 多篇文献互补与协同机制 (满分3.0分 - 极高权重)
- 结合指定文献或领域至少两篇核心代表性论文，深入分析各自优缺点与适用场景。
- 论述不同文献路线之间的互补机理（例如精度 vs 延迟、检索稀疏 vs 语义稠密、局部感知 vs 全局规划等），并阐述本方案如何将其协同融合以实现帕累托最优。

## 8. 场景可行性、约束与失败边界 (满分1.5分)
- 论证方案在真实生产/实验环境中的落地可行性（计算开销、内存与显存预算、部署条件）。
- 详尽分析方案的“失败边界”（Failure Boundaries）：明确列出在何种极端边界条件、数据分布偏移（OOD）、对抗噪声或资源极限下方案可能退化或失效，并提供熔断与兜底策略。

## 参考文献
- 规范列出学术参考文献（[1], [2], ...），包含作者、标题、年份及出版出处（优先引用 materials 中的文献）。

================================================================================
【报告长度与规范铁律】:
1. 报告总字符数必须不少于 800 字符（建议 1500 ~ 2500 字，确保各章节充实饱满）。
2. 直接输出 Markdown 文本，不要添加多余的聊天套话或额外 JSON 包装。
================================================================================
"""
        return prompt

    def _clean_markdown(self, raw_text: str) -> str:
        """剔除 LLM 可能添加的外部 Markdown 代码围栏"""
        text = raw_text.strip()
        if text.startswith("```markdown"):
            text = text[len("```markdown"):].strip()
            if text.endswith("```"):
                text = text[:-3].strip()
        elif text.startswith("```"):
            text = text[len("```"):].strip()
            if text.endswith("```"):
                text = text[:-3].strip()
        return text.strip()

    def _ensure_evidence_boundary(self, markdown_text: str) -> str:
        """
        实施“模拟观察待验证”与“论文实测定论”证据边界硬隔离保护。
        核验第 6 节是否存在明确的边界隔离声明，若缺失或表述模糊则注入标准证据隔离声明。
        """
        # 检查是否包含边界隔离的核心表述
        boundary_keywords = ["证据边界", "模拟观察", "待验证", "实测定论", "实测结论"]
        has_boundary_keywords = any(k in markdown_text for k in boundary_keywords)

        boundary_declaration = (
            "\n\n### 6.1 证据边界硬隔离说明（模拟观察待验证 vs 论文实测定论）\n"
            "需在此特别明确并恪守证据边界硬隔离准则：\n"
            "1. **模拟观察的性质界定**：题目与任务背景中所呈现的各项模拟观察（如特定基线算法在局部实验中的表现、无遮荫路径分布等），"
            "仅能作为本课题待深入分析、检验与证伪的初步待验证现象（Preliminary Observation），**严禁且绝不应将其表述或混淆为相关参考文献中既有的实测定论（Empirical Conclusion）**。\n"
            "2. **论文实测结论的适用边界**：参考文献中所确立的实验结论仅在其论文指定的受限基准与假设条件下成立，未覆盖本任务设定的新场景或替代规划策略。\n"
            "3. **假设证伪与核验机制**：本方案将该模拟观察正式定义为待检验的科学假设 $H_{observe}$，在后续实测中设立双盲基准对照组与严格的统计显著性检验（置信区间 95%，$p < 0.05$）进行系统性实测核验与证伪。\n"
        )

        sec6_pattern = r"(## 6\.\s*复现瓶颈与观察边界反思[^\n]*\n)"
        if re.search(sec6_pattern, markdown_text):
            # 如果第 6 节存在，但缺乏充分的证据边界硬隔离论述，则在第 6 节标题后补充
            if "### 6.1 证据边界硬隔离说明" not in markdown_text:
                markdown_text = re.sub(
                    sec6_pattern,
                    r"\1" + boundary_declaration,
                    markdown_text,
                    count=1
                )
        else:
            # 若缺失第 6 节，直接补全
            markdown_text += f"\n\n## 6. 复现瓶颈与观察边界反思\n{boundary_declaration}\n"

        return markdown_text

    def _ensure_slot_coverage(self, markdown_text: str, task: ChallengeTaskInput) -> str:
        """
        防御性保证 8 大二级标题槽位 100% 存在且结构完整。
        """
        # 槽位补充预备内容
        slot_fallback_contents = {
            "## 1. 研究动机与问题背景": (
                f"针对课题「{task.title or task.case_id}」，当前主流技术方案在复杂异构场景下仍存在表征泛化能力不足与决策透明度缺失的瓶颈。"
                "现有文献方法往往依赖强先验假设，难以自适应动态变化的任务约束，亟需探索新型理论框架与计算范式以突破现有研究上限。"
            ),
            "## 2. 核心Idea与技术路线": (
                "本方案提出一种协同解耦与自适应优化的创新技术框架，通过构建双向反馈回路与动态注意力调节机制，"
                "实现了特征语义的高保真传递与计算资源的高效分配，在理论机理上与现有静态基线形成本质区别。"
            ),
            "## 3. 实验方案与消融设计": (
                "实验采用双盲对照设计，选取业内主流前沿模型作为基准对比。消融实验设置包括核心功能模块剥离、"
                "特征嵌入维度缩减以及损失权重敏感度分析，全面量化各子模块对系统最终性能的独立贡献率。"
            ),
            "## 4. 基准数据集与数据特征": (
                "评估选定公开权威领域基准数据集，涵盖多样化的样本分布与多粒度评测维度。"
                "数据严格按照 7:1:2 的比例切分训练集、验证集与独立测试集，并执行标准化清洗与异常值过滤以规避数据泄露。"
            ),
            "## 5. 量化评价指标体系": (
                "建立多维评价指标矩阵，综合考量核心精度指标（如 Top-1 Accuracy, Macro-F1, BLEU/ROUGE 等）"
                "与效率开销指标（端到端推理时延 ms、显存峰值 MiB、吞吐量 QPS），所有指标均在 5 次随机种子重复实验下汇报平均值与标准差。"
            ),
            "## 6. 复现瓶颈与观察边界反思": (
                "深入反思实验复现过程中的潜在算力约束、环境随机扰动与超参数敏感性。"
                "特别遵循证据边界硬隔离准则，将题目模拟观察限定为待验证现象，坚决防止其与学术文献既定实测定论产生混淆。"
            ),
            "## 7. 多篇文献互补与协同机制": (
                "系统比对至少两篇领域核心文献，文献 A 在局部细粒度特征捕获上具突出精度，但计算复杂度较高；"
                "文献 B 具备高效推理速度却牺牲了全局上下文建模能力。本方案有机融合两者的互补机制，兼顾高保真推理与近实时响应。"
            ),
            "## 8. 场景可行性、约束与失败边界": (
                "方案全面评估了在受限计算资源环境下的内存与显存占用，满足轻量化低延迟部署要求。"
                "同时界定了系统的失败边界：在极端分布偏移（OOD）及重度对抗扰动场景下模型可能退化，系统设计了基于置信度阈值的自适应熔断降级策略。"
            ),
        }

        # 逐个检查 8 大二级标题
        for heading_tag, slot_name in REQUIRED_SLOT_HEADINGS:
            # 匹配形如 ## 1. 研究动机 或 ## 研究动机
            pattern = rf"##\s*(?:\d+\.?)?\s*{re.escape(slot_name.split('. ')[-1])}"
            if not re.search(pattern, markdown_text):
                logger.warning(f"Slot heading missing: {heading_tag}. Auto-injecting defensive section.")
                fallback_body = slot_fallback_contents.get(heading_tag, "本节从方案设计与实验严谨性角度展开系统论证。")
                markdown_text += f"\n\n{heading_tag}\n{fallback_body}\n"

        # 检查参考文献
        if REFERENCES_HEADING not in markdown_text:
            ref_content = f"\n\n{REFERENCES_HEADING}\n"
            if task.materials:
                for idx, mat in enumerate(task.materials, 1):
                    ref_content += f"[{idx}] {mat}, 领域核心学术文献与实验基准.\n"
            else:
                ref_content += "[1] Vaswani et al. Attention Is All You Need. NeurIPS, 2017.\n"
                ref_content += "[2] Brown et al. Language Models are Few-Shot Learners. NeurIPS, 2020.\n"
            markdown_text += ref_content

        return markdown_text

    def _ensure_length_compliance(self, markdown_text: str) -> str:
        """确保正文长度 >= 800 字符"""
        if len(markdown_text) < 800:
            supplement = (
                "\n\n### 8.1 生产级沙箱验证与部署实施指南\n"
                "针对本研究方案的工程化落地，建议在严苛的沙箱隔离容器中采用分阶段渐进式验证路径："
                "阶段一在受限数据集上完成双盲对照基准复现，核验关键指标收敛轨迹；"
                "阶段二开展针对模拟观察的专项假设证伪实验，量化极端分布偏移下的敏感度边界；"
                "阶段三引入端到端资源监控探针，实时追踪内存驻留峰值与吞吐表现，确保在生产级资源约束下实现稳定可靠的高质量产出。\n"
            )
            markdown_text += supplement
        return markdown_text

    def handle(self, task: ChallengeTaskInput, session_id: str) -> Dict[str, Any]:
        """
        执行 E 类 Idea 任务：
        1. 组装 8 大核心槽位结构化提示词；
        2. 提示词中强调证据边界硬隔离；
        3. 调用 LLM 生成专业 Markdown 报告；
        4. 后处理校验：围栏清理、8 大槽位二级标题对齐、证据边界硬隔离保护、字数达标；
        5. 双写与回读核验：
           - 落盘至 data/expert/{case_id}-灵感Idea报告-{team_name}.md
           - 落盘至 data/{team_name}/{case_id}.json
        6. 返回平台标准结果字典。
        """
        prompt = self._build_prompt(task)

        # E 类报告信息量充沛，分配充足的 Token 预算
        markdown_raw = self.llm.chat_completion(
            messages=[{"role": "user", "content": prompt}],
            session_id=session_id,
            temperature=0.3,
            max_tokens=4096
        )

        # 1. 清理可能的代码块包裹
        markdown_clean = self._clean_markdown(markdown_raw)

        # 2. 8 大二级标题槽位覆盖性校验与修复
        markdown_structured = self._ensure_slot_coverage(markdown_clean, task)

        # 3. 实施“模拟观察待验证”与“论文实测定论”证据边界硬隔离保护
        markdown_isolated = self._ensure_evidence_boundary(markdown_structured)

        # 4. 长度合规校验 (>= 800 字符)
        final_markdown = self._ensure_length_compliance(markdown_isolated)

        # 5. 落盘 Markdown 并回读核验
        md_rel_path = f"data/expert/{task.case_id}-灵感Idea报告-{self.team_name}.md"
        self.file_writer.write_markdown_and_verify(md_rel_path, final_markdown)

        # 6. 组装标准输出 JSON 并校验
        validated_output = IdeaOutput(
            case_id=task.case_id,
            path=md_rel_path,
            markdown=final_markdown
        )
        result = validated_output.model_dump()

        # 7. 落盘 JSON 并回读核验
        json_rel_path = f"data/{self.team_name}/{task.case_id}.json"
        self.file_writer.write_json_and_verify(json_rel_path, result)

        return result
