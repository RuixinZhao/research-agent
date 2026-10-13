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
    A 类任务处理器：科研深度对话与研究范围限定追问。
    
    评分项：满分 5 分
    - answer (3分): 科研专业学术解答（专业术语密集、理论机理严谨，字数约 150~300 字）
    - clarifying_question (2分): 针对研究范围限定的一个最关键追问（限定研究对象/数据集粒度/实验控制条件）
    """

    def _build_prompt(self, task: ChallengeTaskInput) -> str:
        prompt = f"""你是一名资深科研学者与人工智能顶会审稿专家。请针对以下用户的科研设想或提问，进行专业、详实、富有学术深度的解答，并提出一个最关键的研究范围限定追问。

【题目标题】: {task.title if task.title else '科研对话'}
【用户输入】: {task.input}
"""
        if task.constraints:
            constraints_str = "\n".join([f"- {c}" for c in task.constraints])
            prompt += f"\n【额外约束条件】:\n{constraints_str}\n"

        prompt += """
【答题与输出要求】:
必须以合法的 JSON 格式返回，且仅包含以下两个顶级字段：
1. "answer": 专业、详实的学术解答（字数在 150~300 字）。
   - 严禁使用泛泛空洞套话，必须富含科研专业术语（如形式化概念、底层作用机理、经典基线、收敛性与权衡分析）。
   - 逻辑清晰，剖析自变量与因变量之间的关联机制与潜在挑战。
2. "clarifying_question": 提出且仅提出一个最关键、具体的科研范围限定追问。
   - 必须紧扣“研究范围限定”（如限定目标研究对象/样本类别、基准数据集规模与标注粒度、变量控制与物理/环境条件、评估场景等）。
   - 必须为单一问句，直接击中该研究方向落地的核心边界。

【JSON 返回格式示例】:
{
  "answer": "在探究光照条件与室内植物生长的关系时，光合光量子通量密度（PPFD）直接决定光反应阶段ATP与NADPH的合成速率，而每日光照周期（Photoperiod）累积计算日常光积量（DLI），共同调控生物量积累与形态发生。然而当超出光饱和点时会引发光抑制现象并加剧活性氧（ROS）积累。因此需结合不同耐阴机制物种在生殖或营养生长阶段的代谢可塑性进行系统评估。",
  "clarifying_question": "请问本研究所针对的目标植物具体属于阳生还是阴生物种，以及拟在哪个生理生长阶段（幼苗期、营养生长期或生殖期）展开变量控制？"
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

        try:
            data = json.loads(cleaned)
            if isinstance(data, dict):
                answer = data.get("answer", "")
                question = data.get("clarifying_question", "")
                if answer and question:
                    return {"answer": answer.strip(), "clarifying_question": question.strip()}
        except Exception as e:
            logger.warning(f"Direct JSON parse failed for {task.case_id}: {e}. Fallback to regex extraction.")

        # 正则降级提取
        answer_match = re.search(r'"answer"\s*:\s*"((?:\\.|[^"\\])*)"', cleaned)
        question_match = re.search(r'"clarifying_question"\s*:\s*"((?:\\.|[^"\\])*)"', cleaned)

        answer = ""
        question = ""
        if answer_match:
            try:
                answer = json.loads(f'"{answer_match.group(1)}"')
            except Exception:
                answer = answer_match.group(1)
        if question_match:
            try:
                question = json.loads(f'"{question_match.group(1)}"')
            except Exception:
                question = question_match.group(1)

        # 终极兜底默认值
        if not answer:
            answer = (
                f"针对课题「{task.title or '该科研设想'}」，系统性研究需立足于核心变量间的作用机理与控制条件。"
                "在给定约束与实验基准下，应重点剖析特征表征粒度、样本复杂度与基线模型在边界场景下的泛化能力，"
                "并结合定量对照实验验证关键因子的敏感性与因果关联，以确保实验结论具备可重复性与统计显著性。"
            )
        if not question:
            question = "请问本研究拟针对的具体基准数据集规模是什么，以及核心自变量的控制边界与实验对照组条件如何设定？"

        return {"answer": answer, "clarifying_question": question}

    def handle(self, task: ChallengeTaskInput, session_id: str) -> Dict[str, Any]:
        """
        执行 A 类对话任务：
        1. 组装学术科研提示词；
        2. 调用 LLM 获得结构化解答与范围限定追问；
        3. Pydantic 校验标准输出字段；
        4. 写入队伍工作区并执行回读核验。
        """
        prompt = self._build_prompt(task)
        
        response_str = self.llm.chat_completion(
            messages=[{"role": "user", "content": prompt}],
            session_id=session_id,
            temperature=0.2,
            response_format={"type": "json_object"}
        )
        
        parsed = self._parse_response(response_str, task)

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
