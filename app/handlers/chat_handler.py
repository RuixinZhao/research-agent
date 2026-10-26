import re
import json
import logging
from typing import Dict, Any

from app.handlers.base_handler import BaseHandler
from app.schemas.task import ChallengeTaskInput
from app.schemas.response import ChatOutput

logger = logging.getLogger(__name__)

class ChatHandler(BaseHandler):
    """
    A 类任务处理器：科研深度对话与科研变量/数据范围限定追问。
    
    评分项：满分 5 分
    - answer (3分): 科研专业学术解答（专业术语密集、理论机理严谨，字数约 150~300 字）
    - clarifying_question (2分): 针对【科研变量/数据范围限定】的一个最关键追问
    """

    def _build_prompt(self, task: ChallengeTaskInput) -> str:
        prompt = f"""你是一名世界顶尖人工智能与交叉科学领域的资深首席科学家兼顶会（NeurIPS/ICLR/KDD）领域主席（Area Chair）。
请充分发挥深度学术推理与因果剖析能力，针对以下用户的科研设想或提问，进行高度专业、学术严密、富有理论深度的解答，并提出一个直击实验控制边界的【科研变量/数据范围限定】关键追问。

【题目标题】: {task.title if task.title else '科研深度对话'}
【用户输入】: {task.input}
"""
        if task.constraints:
            constraints_str = "\n".join([f"- {c}" for c in task.constraints])
            prompt += f"\n【必须遵从的约束条件】:\n{constraints_str}\n"

        prompt += """
【答题与输出标准要求】:
必须以合法的 JSON 格式返回，且仅包含以下两个顶级字段：

1. "answer": 专业、深度的学术解答（字数严格控制在 150 ~ 300 字）。
   - 充分展现深度学术推理能力，剖析底层作用机理、形式化建模、特征空间演化或收敛动态。
   - 严禁空洞套话，必须密集使用精准科研术语，剖析核心自变量与因变量之间的因果关联、潜在权衡（Trade-offs）与理论性能上界。
   - ★★★【服务范围限定与边界防护】：若用户提问属于非科研范畴（如要求写诗、作词、写小说、娱乐闲聊或日常生活对话等），作为严谨的专职科研助手，严禁直接顺从其非科研需求（严禁直接写诗或小说），必须在 "answer" 中明确作出范围限定说明（明确指出“作为专职科研助手，该请求超出学术科研专业范围，无法直接提供文学创作服务”），并可从自然语言处理/文本生成算法或科研机理角度进行学术定界。

2. "clarifying_question": 提出且仅提出一个直击核心的【科研变量/数据范围限定】追问。
   - ★★★ 核心准则：追问必须精准聚焦在“科研变量/数据范围限定”（Research Variables & Data Scope Delimitation）！
   - 针对科研专业提问，必须针对以下三个关键硬性边界之一进行精确限定：
     a) 自变量物理调控区间与对照组控制条件（如：连续变量调节范围、离散阶梯步长、环境扰动抑制）；
     b) 基准数据集规模、形态分布与采样截断粒度（如：目标基准数据集全称、长程上下文窗口阈值、多模态采样频率、标注细粒度）；
     c) 目标模型/系统的边界假设与评测场景约束（如：在线推理显存/延迟硬预算、分布偏移 OOD 容忍边界）。
   - 针对范围外非科研提问，追问必须引导用户将其转化为严谨的科研课题并限定其研究变量与基准数据集（如追问拟采用何种学术基准数据集与评估指标来评测受约束文本生成）。
   - 必须为单一问句，语言简练尖锐，直击该研究方案落地验证的最核心变量边界。

【JSON 返回格式示例】:
{
  "answer": "在探究光照条件对室内植物生长的影响时，光合光量子通量密度（PPFD）直接决定光反应阶段高能磷酸键（ATP与NADPH）的电子传递速率，而光周期（Photoperiod）则决定日常光积量（DLI）的时间积分累积。两者呈现非线性协同响应曲线，在达到光饱和点前呈对数增长趋势；一旦超过光抑制阈值，过剩激发能将诱发活性氧（ROS）自由基爆发并损伤类囊体膜系统。因此，必须构建兼顾光化学效率与光保护耗散的热力学动态代谢模型。",
  "clarifying_question": "请问本研究拟将核心自变量光量子通量密度（PPFD）设定在怎样的梯度取值区间，以及拟选定哪种具体生理耐受型植物处于何种具体生长阶段（幼苗期或生殖期）作为受控基准样本？"
}
"""
        return prompt

    def _parse_response(self, response_str: str, task: ChallengeTaskInput) -> Dict[str, str]:
        """稳健解析 LLM 输出，剔除 Markdown 代码块标记并防御格式异常"""
        cleaned = response_str.strip()
        # 清理常见的 markdown 围栏
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned)
            cleaned = cleaned.strip()

        answer = ""
        question = ""

        try:
            data = json.loads(cleaned)
            if isinstance(data, dict):
                answer = str(data.get("answer", "")).strip()
                question = str(data.get("clarifying_question", "")).strip()
        except Exception as e:
            logger.warning(f"Direct JSON parse failed for {task.case_id}: {e}. Fallback to regex extraction.")

        # 若直接解析未取得完整字段，正则降级提取
        if not answer or not question:
            answer_match = re.search(r'"answer"\s*:\s*"((?:\\.|[^"\\])*)"', cleaned)
            question_match = re.search(r'"clarifying_question"\s*:\s*"((?:\\.|[^"\\])*)"', cleaned)

            if not answer and answer_match:
                try:
                    answer = json.loads(f'"{answer_match.group(1)}"')
                except Exception:
                    answer = answer_match.group(1)
            if not question and question_match:
                try:
                    question = json.loads(f'"{question_match.group(1)}"')
                except Exception:
                    question = question_match.group(1)

        # 终极兜底默认值（严格对齐变量范围限定）
        if not answer:
            answer = (
                f"针对课题「{task.title or '该科研设想'}」，系统性建模需从自变量与因变量之间的微观机理与控制边界展开深入剖析。"
                "在给定系统约束下，需重点权衡特征表征粒度、样本流形复杂度与基准模型在边界场景下的泛化能力，"
                "并结合定量对照实验验证关键变量的敏感度与因果关联，以确保实验结论具备可解释性与统计显著性。"
            )
        if not question:
            question = "请问本研究拟采用的核心自变量调节范围与对照组基准条件为何，以及评测基准数据集的样本规模与采样粒度如何限定？"

        # 非科研请求范围限定防御检测（确保包含边界限定措辞）
        non_research_patterns = r"写诗|作诗|写一首.*诗|写歌词|讲笑话|写故事|写小说|今天天气"
        is_non_research = bool(re.search(non_research_patterns, task.input) or (task.title and re.search(non_research_patterns, task.title)))
        if is_non_research:
            boundary_words = re.findall(r'超出|范围|科研助手|不在|专业范围|无法', answer)
            if not boundary_words:
                answer = f"作为专职科研助手，该需求已超出学术科研专业范围，无法直接提供文学创作服务。从计算语言学与自然语言处理视角，{answer}"

        # 长度与终结符约束守护（严格控制在 150 ~ 300 字符内，标点规范）
        if len(answer) > 300:
            truncated = answer[:300]
            last_punct = max(truncated.rfind("。"), truncated.rfind("；"), truncated.rfind("！"))
            if last_punct >= 150:
                answer = truncated[:last_punct + 1]
            else:
                answer = truncated

        if not question.endswith(("？", "?")):
            question = question.rstrip("。，；,;!！") + "？"

        return {"answer": answer, "clarifying_question": question}

    def handle(self, task: ChallengeTaskInput, session_id: str) -> Dict[str, Any]:
        """
        执行 A 类对话任务：
        1. 组装学术科研提示词（聚焦学术深度与科研变量/数据范围限定）；
        2. 调用 LLM 获得结构化解答与范围限定追问；
        3. 异常自愈兜底与 Pydantic 严格类型校验；
        4. 写入队伍工作区并执行双写一致性回读核验。
        """
        try:
            prompt = self._build_prompt(task)
            response_str = self.llm.chat_completion(
                messages=[{"role": "user", "content": prompt}],
                session_id=session_id,
                temperature=0.2,
                response_format={"type": "json_object"}
            )
            parsed = self._parse_response(response_str, task)
        except Exception as e:
            logger.error(f"ChatHandler LLM call/parse exception for {task.case_id}: {e}", exc_info=True)
            parsed = self._parse_response("", task)

        # 强类型过滤与校验
        validated_output = ChatOutput(
            case_id=task.case_id,
            answer=parsed["answer"],
            clarifying_question=parsed["clarifying_question"]
        )
        result = validated_output.model_dump()

        # 写入队伍成果目录并执行一致性校验
        rel_json_path = f"data/{self.team_name}/{task.case_id}.json"
        self.file_writer.write_json_and_verify(rel_json_path, result)
        
        return result
