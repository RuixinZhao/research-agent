import os
import gc
import json
import re
import logging
from typing import Dict, Any, List, Set

from app.handlers.base_handler import BaseHandler
from app.schemas.task import ChallengeTaskInput
from app.core.pdf_parser import StreamPDFParser
from app.core.search_engine import LocalFTS5SearchEngine
from app.config import settings

logger = logging.getLogger(__name__)

class RetrievalHandler(BaseHandler):
    """
    B 类 Literature_Retrieval 任务处理器（顶会级逻辑推理与否定排他防火墙）。
    目标：精准论文检索与否定条件排他拦截。
    计分规则：15 * H / N - 0.75 * U。严防误报无关论文造成 -0.75U 扣分（宁缺毋滥原则）。
    特性：
    1. 1024 MiB 内存保护：流式逐页解析前 4 页并主动 GC；
    2. DeepSeek 逻辑链【否定排他防火墙】：自动析出排除性红线，对候选文献实施多维度排他审查；
    3. 物理文件存在性与唯一性校验，死保 U=0。
    """

    def _resolve_papers_dir(self) -> str:
        """寻找真实可用的论文根目录，支持生产环境与本地开发降级"""
        candidate_dirs = [
            settings.PAPERS_DIR,
            "/data/papers",
            os.path.join(os.getcwd(), "downloaded_papers"),
            os.path.join(os.getcwd(), "agent_papers"),
        ]
        for d in candidate_dirs:
            if os.path.exists(d) and os.path.isdir(d):
                pdfs = [f for f in os.listdir(d) if f.endswith(".pdf")]
                if pdfs:
                    return d
        return settings.PAPERS_DIR

    def _extract_negation_keywords(self, text: str) -> Set[str]:
        """从用户查询文本中提取显式排他/否定关键词"""
        keywords = set()
        patterns = [
            r"(?:不包含|不要包含|排除|不涉及|不采用|除外|剔除|不要有|不要)\s*['\"“]?([A-Za-z0-9\u4e00-\u9fa5_-]+)['\"”]?",
            r"exclude\s+['\"“]?([A-Za-z0-9_-]+)['\"”]?",
            r"without\s+['\"“]?([A-Za-z0-9_-]+)['\"”]?",
        ]
        for pat in patterns:
            for match in re.findall(pat, text, re.IGNORECASE):
                cleaned = match.strip()
                cleaned = re.sub(r"(?:方法|算法|模型|方向|技术)?(?:的文献|的论文|相关|的)?$", "", cleaned)
                if len(cleaned) >= 2:
                    keywords.add(cleaned)
        return keywords

    def handle(self, task: ChallengeTaskInput, session_id: str) -> Dict[str, Any]:
        papers_dir = self._resolve_papers_dir()

        # 1. 扫描本地实际物理存在的 PDF 文件
        available_pdfs: List[str] = []
        if os.path.exists(papers_dir):
            for root, _, files in os.walk(papers_dir):
                for f in files:
                    if f.endswith(".pdf"):
                        available_pdfs.append(f)
        available_pdfs = sorted(list(set(available_pdfs)))

        if not available_pdfs:
            logger.warning(f"论文库为空或未找到 PDF 文件: {papers_dir}")
            result = {"case_id": task.case_id, "papers": []}
            self.file_writer.write_json_and_verify(f"data/{self.team_name}/{task.case_id}.json", result)
            return result

        # 若题目显式指定了 materials 范围，则以指定材料为优先候选库
        candidate_pool = available_pdfs
        if task.materials:
            specified_in_pool = [m for m in task.materials if m in available_pdfs]
            if specified_in_pool:
                candidate_pool = specified_in_pool

        # 2. 建立轻量级临时 FTS5 索引并逐篇流式解析前 4 页（控制内存常驻）
        engine = LocalFTS5SearchEngine()
        pdf_snippets_map: Dict[str, str] = {}
        try:
            for pdf_name in candidate_pool:
                full_path = os.path.join(papers_dir, pdf_name)
                if not os.path.exists(full_path):
                    for root, _, files in os.walk(papers_dir):
                        if pdf_name in files:
                            full_path = os.path.join(root, pdf_name)
                            break

                if not os.path.exists(full_path):
                    continue

                # 仅解析前 4 页（覆盖 Title, Abstract, Introduction, 核心方法概述）
                pages = StreamPDFParser.extract_pages(full_path, max_pages=4)
                if pages:
                    engine.index_paper_pages(pdf_name, pages)
                    first_page_text = pages[0]["text"] if len(pages) > 0 else ""
                    pdf_snippets_map[pdf_name] = first_page_text[:600]
                del pages
                gc.collect()

            # 3. 构造综合检索词召回候选 Top 论文
            search_query = f"{task.title} {task.input}".strip()
            candidates = engine.search(search_query, top_k=10)
            candidate_files = list(dict.fromkeys([c["filename"] for c in candidates]))

            # 若通过 query 未能召回足够候选，且材料库较小（<= 10），将材料库纳入候选
            if len(candidate_files) < 3 and len(candidate_pool) <= 10:
                for fn in candidate_pool:
                    if fn not in candidate_files:
                        candidate_files.append(fn)

            if not candidate_files:
                result = {"case_id": task.case_id, "papers": []}
                self.file_writer.write_json_and_verify(f"data/{self.team_name}/{task.case_id}.json", result)
                return result

            # 4. 组装候选论文摘要信息
            candidate_info_list = []
            for fn in candidate_files[:12]:
                snippet = pdf_snippets_map.get(fn, "")
                candidate_info_list.append({
                    "filename": fn,
                    "abstract_snippet": snippet
                })

            # 5. DeepSeek 逻辑链【否定排他防火墙】
            firewall_prompt = f"""你是一名极其严苛的学术文献检索与排他审核裁判。你的核心职责是根据用户的研究需求，构建【否定排他防火墙】，从候选论文中精确选出【完全符合主题且不触犯任何排他红线】的高置信度文献。

【检索任务需求与具体指令】:
{task.input}

【任务约束条件】:
{json.dumps(task.constraints, ensure_ascii=False) if task.constraints else "无额外显式约束"}

【候选论文列表及其摘要片段】:
{json.dumps(candidate_info_list, ensure_ascii=False, indent=2)}

【评分与惩罚刚性铁律（绝不可违犯）】:
1. 【高精度惩罚计分】: 计分公式为 15 * H / N - 0.75 * U。每误报一篇无关或边缘文献，直接扣减 0.75 分！因此必须坚决奉行【宁缺毋滥（High Precision）】原则。
2. 【否定排他防火墙机制】:
   - 深入分析检索需求中的否定词（如“排除...”、“不要...”、“不涉及...”、“非某方向”、“exclude...”等），明确析出所有【绝对排他红线】。
   - 凡是论文主题、方法、模态或应用场景触及排他红线的，无论相关度多高，必须判定为 REJECT！
3. 【核心契合度要求】:
   - 目标文献的核心创新点必须直接解决用户的正面需求；仅在 Related Work 中作为背景顺带提及的论文，坚决 REJECT！
4. 【精确文件名匹配】:
   - 选中的文件名必须与候选列表中提供的 filename 逐字完全匹配，严禁修改或造词。
5. 【疑罪从无/宁缺毋滥】:
   - 若候选文献匹配度存疑或无高置信度完全吻合者，宁可返回空数组 []，绝对不可冒险推荐！

【输出格式规范】:
必须返回纯 JSON 格式：
{{
  "negative_exclusions": [
    "解析出的显式或隐式排他红线1",
    "排他红线2"
  ],
  "evaluations": [
    {{
      "filename": "完整文件名.pdf",
      "negative_violation": true/false,
      "core_contribution_match": true/false,
      "confidence_score": 1到5的整数打分,
      "decision": "ACCEPT 或 REJECT",
      "reason": "具体判定逻辑说明"
    }}
  ],
  "selected": [
    {{
      "filename": "完整文件名.pdf",
      "reason": "具体陈述核心创新点为何完全吻合需求且未违反任何排他约束的论证依据。"
    }}
  ]
}}
"""
            llm_response = self.llm.chat_completion(
                messages=[
                    {"role": "system", "content": "你是一名精通学术论文检索、逻辑严谨、严格执行否定排他防火墙的 AI 专家。输出严格合规 JSON。"},
                    {"role": "user", "content": firewall_prompt}
                ],
                session_id=session_id,
                temperature=0.0,
                response_format={"type": "json_object"}
            )

            # 解析 LLM 输出与防火墙二次校验
            selected_papers_raw: List[Dict[str, str]] = []
            evaluations_map: Dict[str, Dict[str, Any]] = {}
            parsed: Dict[str, Any] = {}

            try:
                raw_json = json.loads(llm_response)
                if isinstance(raw_json, dict):
                    parsed = raw_json
                    # 记录细粒度评估
                    raw_evals = parsed.get("evaluations", [])
                    if isinstance(raw_evals, list):
                        for ev in raw_evals:
                            if isinstance(ev, dict) and "filename" in ev:
                                evaluations_map[ev["filename"].strip()] = ev

                    selected_papers_raw = parsed.get("selected", [])
                elif isinstance(raw_json, list):
                    selected_papers_raw = raw_json
            except Exception as pe:
                logger.warning(f"LLM 响应 JSON 解析失败，尝试正则提取: {pe}")
                match = re.search(r"\{.*\}", llm_response, re.DOTALL)
                if match:
                    try:
                        p_obj = json.loads(match.group(0))
                        if isinstance(p_obj, dict):
                            parsed = p_obj
                            selected_papers_raw = p_obj.get("selected", [])
                    except Exception:
                        pass

            # 6. 防火墙二次拦截与物理存在性核验

            valid_papers = []
            seen_filenames = set()

            # 提取显式否定排他关键词（规则层 + LLM 输出的 negative_exclusions）
            explicit_neg_kws = self._extract_negation_keywords(task.input)
            for ex in parsed.get("negative_exclusions", []):
                if isinstance(ex, str) and ex.strip():
                    cleaned_ex = re.sub(r"(?:方法|算法|模型|方向|技术)?(?:的文献|的论文|相关|的)?$", "", ex.strip())
                    if len(cleaned_ex) >= 2:
                        explicit_neg_kws.add(cleaned_ex)

            for p in selected_papers_raw:
                if not isinstance(p, dict):
                    continue
                fn = p.get("filename", "").strip()

                # 核验 1：必须在本地文件系统中物理存在
                if fn not in available_pdfs:
                    logger.warning(f"排除不存在的物理文件: {fn}")
                    continue

                # 核验 2：若 evaluations 判定其违反了排他红线或 decision 为 REJECT，坚决剔除
                ev = evaluations_map.get(fn)
                if ev:
                    if ev.get("negative_violation") is True:
                        logger.info(f"防火墙拦截触犯排他红线的文献: {fn}")
                        continue
                    if ev.get("decision") == "REJECT":
                        logger.info(f"防火墙拦截判定为 REJECT 的文献: {fn}")
                        continue
                    if ev.get("confidence_score", 5) < 3:
                        logger.info(f"防火墙拦截低置信度文献: {fn}")
                        continue

                # 核验 2.1：规则层双重排他校验（防 -0.75U 误报）
                # 检查文件名与正文摘要片段是否包含明确被排他的关键词
                snippet_text = pdf_snippets_map.get(fn, "").lower()
                fn_lower = fn.lower()
                is_neg_violated = False
                for neg_kw in explicit_neg_kws:
                    kw_lower = neg_kw.lower()
                    if kw_lower in fn_lower or kw_lower in snippet_text:
                        logger.info(f"防火墙双重校验拦截包含排他关键词 '{neg_kw}' 的文献: {fn}")
                        is_neg_violated = True
                        break
                if is_neg_violated:
                    continue

                # 核验 3：去重
                if fn not in seen_filenames:
                    seen_filenames.add(fn)
                    valid_papers.append({
                        "filename": fn,
                        "reason": p.get("reason", "经正文与核心方法验证，该文献完全满足检索需求且未触犯任何排他约束。").strip()
                    })

            result = {
                "case_id": task.case_id,
                "papers": valid_papers
            }

        finally:
            engine.close()
            del engine
            gc.collect()

        # 7. 写入本队产物目录并回读校验
        output_rel_path = f"data/{self.team_name}/{task.case_id}.json"
        self.file_writer.write_json_and_verify(output_rel_path, result)
        return result
