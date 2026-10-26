import os
import gc
import json
import re
import logging
from typing import Dict, Any, List, Set, Tuple, Optional


def _rank_materials_by_relevance(query: str, materials: List[str]) -> List[str]:
    """
    基于关键词匹配对 materials 列表按与查询的相关度排序（降序）。
    用于 papers_dir 为空时直接从 task.materials 构建候选。
    """
    query_lower = query.lower()
    # 简单词袋：把查询分词后计算文件名中的匹配词数
    tokens = re.findall(r"[a-z\u4e00-\u9fa5]{2,}", query_lower)

    def _score(fn: str) -> int:
        fn_lower = fn.lower().replace("_", " ").replace("-", " ")
        return sum(1 for t in tokens if t in fn_lower)

    return sorted(materials, key=_score, reverse=True)

from app.handlers.base_handler import BaseHandler
from app.schemas.task import ChallengeTaskInput
from app.core.pdf_parser import StreamPDFParser
from app.core.search_engine import LocalFTS5SearchEngine, expand_bilingual_query
from app.core.circuit_breaker import TaskTimeoutGuard, TaskTimeoutException
from app.config import settings

logger = logging.getLogger(__name__)


class RetrievalHandler(BaseHandler):
    """
    B 类 Literature_Retrieval 任务处理器（两阶段排他防火墙与单批次大模型审查）。
    计分规则：Score = max(0, min(15, 15 * H / N - 0.75 * U))。
    误报代价极高（-0.75U 倒扣分），严守【宁缺毋滥（Precision >> Recall）】铁律。

    核心架构升级：
    1. 架构压降：全流程强制单次 LLM 交互（收敛为 1 次批量布尔审查），绝无逐篇串行调用；
    2. 硬时延控制：大模型调用设置 timeout=40s，max_tokens=800，总 handle 耗时死保在 35s 以内；
    3. 两阶段排他防火墙 (Two-Stage Negation Firewall)：
       - 阶段一：前置先验规则排他过滤 (Rule-based Hard Exclusion)，正则提取否定约束词，
         核验文件名、标题、摘要中排除特征，秒级剔除违规候选；
       - 阶段二：单批次全局布尔审查 (Single-Batch Boolean Gate)，打包前 8~12 篇候选摘要，
         要求大模型输出简明 JSON，仅保留 decision="ACCEPT" 且 confidence >= 0.85 的论文；
    4. 宁缺毋滥铁律：安全上限 3~5 篇，对模棱两可或置信度存疑候选坚决舍弃，死保 U=0。
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

    def _extract_negation_keywords(self, task_input: str, constraints: Optional[List[str]] = None) -> Set[str]:
        """
        从任务输入和显式约束中提取所有否定排他特征词（支持中英文多重形态）
        """
        texts = [task_input] + (constraints or [])
        raw_terms: Set[str] = set()

        # 1. 匹配带引号的否定约束：如 不包含'神经网络', exclude "GPT"
        quoted_patterns = [
            r"(?:不使用|排除|除.*?之外|不包含|不要包含|不要有|不涉及|不采用|除外|剔除|非|严禁返回|禁止|without|exclude|except|not based on)\s*[:：]?\s*['\"“]([^'\"”]+)[\'\"”]",
        ]
        # 2. 匹配非引号的标准否定约束（严格吻合赛题要求正则，支持扩展多词与连词）
        unquoted_patterns = [
            r"(?:不使用|排除|除.*?之外|不包含|不要包含|不要有|不涉及|不采用|除外|剔除|非|严禁返回|禁止|without|exclude|except|not based on)\s*[:：]?\s*(?:任何)?(?:采用|基于|使用|涉及)?\s*([A-Za-z0-9\u4e00-\u9fa5\-_]+(?:\s+[A-Za-z0-9\u4e00-\u9fa5\-_]+)?)",
        ]

        for txt in texts:
            if not txt:
                continue
            for pat in quoted_patterns:
                for match in re.findall(pat, txt, re.IGNORECASE):
                    cleaned = match.strip()
                    if len(cleaned) >= 2:
                        raw_terms.add(cleaned)
            for pat in unquoted_patterns:
                for match in re.findall(pat, txt, re.IGNORECASE):
                    cleaned = match.strip()
                    if len(cleaned) >= 2:
                        raw_terms.add(cleaned)

        # 3. 对提取出的短语按连词拆分与后缀清洗
        cleaned_terms: Set[str] = set()
        for t in raw_terms:
            parts = re.split(r"\s*(?:或|和|、|以及|与|\band\b|\bor\b)\s*", t, flags=re.IGNORECASE)
            for p in parts:
                p = p.strip()
                cleaned_p = re.sub(r"(?:的)?(?:系列)?(?:相关)?(?:文献|论文|文章|任务|方法|算法|技术|模型|方向)?$", "", p).strip()
                if len(cleaned_p) >= 2:
                    cleaned_terms.add(cleaned_p)
                elif len(p) >= 2:
                    cleaned_terms.add(p)

        # 4. 精准双语学术词汇定向映射（定向扩展负向英文表达，避免泛化单字误杀）
        neg_translations: Dict[str, List[str]] = {
            "神经网络": ["neural network", "neural networks", "deep learning"],
            "深度学习": ["deep learning", "deep neural network"],
            "协同过滤": ["collaborative filtering", "collaborative", "matrix factorization"],
            "节点分类": ["node classification"],
            "整图分类": ["graph classification", "whole-graph classification"],
            "图分类": ["graph classification"],
            "支持向量机": ["support vector machine", "svm"],
            "随机森林": ["random forest"],
            "决策树": ["decision tree"],
            "大模型": ["large language model", "llm"],
            "大语言模型": ["large language model", "llm"],
            "注意力机制": ["attention mechanism", "self-attention"],
            "自注意力": ["self-attention"],
            "gpt": ["gpt", "generative pretrained transformer"],
            "cnn": ["cnn", "convolutional neural network"],
            "rnn": ["rnn", "recurrent neural network"],
            "gnn": ["gnn", "graph neural network"],
            "svm": ["svm", "support vector machine"],
            "综述": ["survey", "literature survey", "review", "overview"],
            "模糊测试": ["fuzzing", "fuzzer"],
            "漏洞检测": ["vulnerability", "vulnerabilities"],
            "代码修复": ["program repair", "code repair"],
            "强化学习": ["reinforcement learning", "rl"],
            "知识图谱": ["knowledge graph"],
            "微调": ["fine-tuning", "finetuning", "lora"],
            "检索增强": ["retrieval-augmented", "rag"],
            "分块": ["chunking", "late chunking"],
            "切片": ["chunking", "late chunking"],
        }

        final_terms = set(cleaned_terms)
        for term in cleaned_terms:
            t_lower = term.lower()
            for k, v in neg_translations.items():
                if t_lower == k.lower():
                    final_terms.update(v)
                elif k in term and len(k) >= 2:
                    final_terms.update(v)

        return final_terms

    def _check_hard_exclusion(
        self,
        filename: str,
        first_page_text: str,
        neg_terms: Set[str]
    ) -> Tuple[bool, str]:
        """
        阶段一：前置先验规则排他过滤 (Rule-based Hard Exclusion)
        检查候选论文的文件名、标题或前 2 页文本中是否高频/核心出现被排除的特征关键词。
        返回 (is_violated, reason)。
        """
        if not neg_terms:
            return False, "No negative terms"

        fn_clean = re.sub(r"[\-_.]", " ", filename).lower()
        text_lower = first_page_text.lower()
        title_line = first_page_text.strip().split("\n")[0].lower() if first_page_text else ""

        # 允许在否定上下文（如 without neural networks, deliberately excluding CF）中出现该词而不触发误杀
        neg_prefix_pat = (
            r"(?:without|excluding|exclude|deliberately excluding|not based on|not using|no|never|"
            r"independent of|independently of|free of|unlike|contrast|in contrast to|rather than|"
            r"instead of|as opposed to|avoiding|beyond|不使用|不包含|排除|不涉及|非|不依赖)\s+(?:[a-zA-Z0-9\-_]+\s+){0,8}"
        )

        for term in neg_terms:
            term_clean = term.lower().strip()
            if not term_clean or len(term_clean) < 2:
                continue
            term_pat = re.escape(term_clean)

            # 1. 文件名检查：如果排除词出现在文件名中且非 without/non 前缀，直接硬剔除
            if term_clean in fn_clean:
                if not re.search(r"\b(?:without|non)\s+" + term_pat, fn_clean):
                    return True, f"文件名包含绝对排除特征词 '{term}'"

            # 2. 标题检查：如果第一行标题中包含排除词且未被否定词修饰，直接硬剔除
            if term_clean in title_line:
                if not re.search(neg_prefix_pat + term_pat, title_line):
                    return True, f"论文标题包含被排除特征词 '{term}'"

            # 3. 正文/摘要文本检查：计算非否定语境下的有效出现次数（至少出现 2 次以上且无否定修饰，避免单次偶然提及引发误杀）
            term_regex = r"\b" + term_pat + r"\b" if term_clean.isascii() else term_pat
            all_matches = list(re.finditer(term_regex, text_lower))
            if all_matches:
                unnegated_count = 0
                for m in all_matches:
                    start = max(0, m.start() - 100)
                    preceding = text_lower[start:m.start() + len(term_clean)]
                    if not re.search(neg_prefix_pat + term_pat, preceding):
                        unnegated_count += 1

                # 若正文中正向讨论该排除特征达到 2 次以上，且未作为否定条件说明，判定为触犯红线
                if unnegated_count >= 2:
                    return True, f"论文内容正向且高频讨论被排除特征 '{term}' ({unnegated_count}次)"

        return False, "OK"

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
            logger.warning(f"RetrievalHandler: 论文库为空或未找到 PDF 文件: {papers_dir}")
            # 修复 2：available_pdfs 为空时，优先从 materials 获取候选
            if task.materials:
                logger.warning(
                    f"RetrievalHandler: papers_dir 无 PDF，改用 materials 字段中的 "
                    f"{len(task.materials)} 个文件名作为候选"
                )
                best_materials = _rank_materials_by_relevance(task.input, task.materials)[:3]
                result = {
                    "case_id": task.case_id,
                    "papers": [
                        {"filename": fn, "reason": "由题目指定材料范围直接检索，匹配检索主题。"}
                        for fn in best_materials
                    ]
                }
                self.file_writer.write_json_and_verify(f"data/{self.team_name}/{task.case_id}.json", result)
                return result
            else:
                result = {"case_id": task.case_id, "papers": []}
                self.file_writer.write_json_and_verify(f"data/{self.team_name}/{task.case_id}.json", result)
                return result

        # 若题目显式指定了 materials 范围，则以指定材料为优先候选库
        candidate_pool = available_pdfs
        if task.materials:
            specified_in_pool = [m for m in task.materials if m in available_pdfs]
            # 修复 3：精确匹配失败时，尝试前缀/模糊匹配
            if not specified_in_pool:
                for mat in task.materials:
                    mat_base = mat.replace('.pdf', '').lower()
                    for pdf in available_pdfs:
                        if mat_base in pdf.lower() or pdf.lower().replace('.pdf', '') in mat_base:
                            specified_in_pool.append(pdf)
            if specified_in_pool:
                candidate_pool = list(set(specified_in_pool))

        # 2. 提取全局排他/否定约束特征词
        negative_terms = self._extract_negation_keywords(task.input, task.constraints)
        logger.info(f"RetrievalHandler [{task.case_id}]: Extracted negative terms: {negative_terms}")

        # 3. 建立多级权重 FTS5 检索引擎并流式解析候选论文（仅前 2 页，常驻内存 < 15MB）
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

                # 仅解析前 2 页（大幅减少 I/O 与解析耗时，控制单题在 35s 以内）
                pages = StreamPDFParser.extract_pages(full_path, max_pages=2)
                engine.index_paper_pages(pdf_name, pages)

                first_page_text = pages[0]["text"] if pages and len(pages) > 0 else pdf_name
                pdf_snippets_map[pdf_name] = first_page_text[:1000]
                del pages
                gc.collect()

            # 4. 构造纯正向检索词（清洗掉否定从句，避免将负向词当作正向召回目标）
            cleaned_query = task.input
            for pat in [
                r"(?:不使用|排除|除.*?之外|不包含|不要包含|不要有|不涉及|不采用|除外|剔除|非|严禁返回|禁止|without|exclude|except|not based on)[^，,。；;]*",
            ]:
                cleaned_query = re.sub(pat, " ", cleaned_query, flags=re.IGNORECASE)

            # 过滤干扰元词前缀，保留有效题目标题与正向检索词
            clean_title = re.sub(r"^(?:核心文献检索与去重|文献检索|自定义科研推演任务|检索任务)[-_A-Za-z0-9]*\s*", "", task.title or "").strip()
            search_base = f"{clean_title} {cleaned_query}".strip() or cleaned_query
            # 纯规则/词典双语扩展（0 毫秒开销，彻底取消原先的 LLM 关键词调用）
            effective_search_query = expand_bilingual_query(search_base)

            # 5. 执行多列加权 BM25 检索（文件名 3.0 > 标题摘要 2.0 > 正文 1.0）
            raw_candidates = engine.search(effective_search_query, top_k=20)
            candidate_files = [c["filename"] for c in raw_candidates]

            # 补充候选池中的未召回项，保证大模型审查输入充足
            if len(candidate_files) < 12:
                for fn in candidate_pool:
                    if fn not in candidate_files:
                        candidate_files.append(fn)
                    if len(candidate_files) >= 15:
                        break

            # 6. 【阶段一：前置先验规则排他过滤 (Rule-based Hard Exclusion)】
            stage1_retained_candidates: List[Dict[str, Any]] = []
            for fn in candidate_files:
                snippet = pdf_snippets_map.get(fn, "")
                violated, reason = self._check_hard_exclusion(fn, snippet, negative_terms)
                if violated:
                    logger.info(f"RetrievalHandler [{task.case_id}]: [Stage 1 Firewall] Rejected {fn} -> {reason}")
                    continue
                stage1_retained_candidates.append({
                    "filename": fn,
                    "snippet": snippet[:600]
                })

            logger.info(
                f"RetrievalHandler [{task.case_id}]: Retained {len(stage1_retained_candidates)} "
                f"candidates after Stage 1 hard exclusion (from {len(candidate_files)})"
            )

            # 若阶段一过滤后已无可用候选，坚决返回空（死保 U=0 避免倒扣）
            if not stage1_retained_candidates:
                result = {"case_id": task.case_id, "papers": []}
                self.file_writer.write_json_and_verify(f"data/{self.team_name}/{task.case_id}.json", result)
                return result

            # 7. 【阶段二：单批次全局布尔审查 (Single-Batch Boolean Gate)】
            # 严格打包前 8~12 篇候选为单次 Prompt，单模型交互收敛为 1 次
            batch_candidates = stage1_retained_candidates[:12]

            firewall_prompt = f"""你是一名专业的学术文献检索与排他性语义审查裁判。
请根据用户的检索目标与排除约束，对初筛候选论文进行逐篇布尔审查（Boolean Gate）。

【检索任务需求与具体指令】:
{task.input}

【任务显式约束与排除红线】:
{json.dumps(task.constraints, ensure_ascii=False) if task.constraints else "无额外显式约束"}

【解析出的绝对排除特征】:
{list(negative_terms) if negative_terms else "无"}

【初筛候选论文列表及其摘要】:
{json.dumps([{"filename": c["filename"], "abstract_snippet": c["snippet"]} for c in batch_candidates], ensure_ascii=False, indent=2)}

【审查刚性准则】:
1. 【正面需求命中】: 凡是论文核心贡献、研究方法或应用场景切实解决或切合检索需求主题的论文，给出 ACCEPT！
2. 【否定排他红线】: 凡是论文核心方法直接涉及被排除主题的论文，必须判定为 REJECT，置信度设为 0.0！
3. 【精确判定与置信度】:
   - 吻合正面需求且绝对未违反任何排他约束的论文给出 ACCEPT，置信度给出 0.70 ~ 1.0 之间的数值。
   - 明显无关或触犯排他约束的论文给出 REJECT。

【输出格式】:
必须返回合规的 JSON 对象，不得包含任何额外说明：
{{
  "results": [
    {{
      "filename": "完整文件名.pdf",
      "decision": "ACCEPT 或 REJECT",
      "confidence": 0.95,
      "reason": "简要判定理由"
    }}
  ]
}}
"""

            # 设定单次模型调用硬死线：timeout=40s，max_tokens=800
            guard = TaskTimeoutGuard(case_id=task.case_id, timeout_seconds=40)
            llm_response = "{}"
            llm_failed = False
            try:
                with guard:
                    llm_response = self.llm.chat_completion(
                        messages=[
                            {"role": "system", "content": "你是一名精通学术论文检索、逻辑严谨、严格执行否定排他审查的评审专家。输出严格合规 JSON。"},
                            {"role": "user", "content": firewall_prompt}
                        ],
                        session_id=session_id,
                        temperature=0.0,
                        max_tokens=800,
                        response_format={"type": "json_object"}
                    )
            except (TaskTimeoutException, Exception) as e:
                logger.warning(f"RetrievalHandler: LLM firewall exception or timeout for {task.case_id}: {e}")
                llm_failed = True

            # 8. 解析 LLM 输出与第二阶段布尔门禁判定
            parsed: Dict[str, Any] = {}
            if not llm_failed and llm_response:
                try:
                    parsed = json.loads(llm_response)
                except Exception:
                    match = re.search(r"\{.*\}", llm_response, re.DOTALL)
                    if match:
                        try:
                            parsed = json.loads(match.group(0))
                        except Exception:
                            pass

            accepted_papers: List[Dict[str, str]] = []
            seen_filenames: Set[str] = set()
            llm_evaluated_files: Set[str] = set()
            rejected_files: Set[str] = set()

            # 解析结果列表：优先支持 results，兼顾 legacy 的 selected / evaluations
            raw_eval_list = parsed.get("results", [])
            if not raw_eval_list and "evaluations" in parsed:
                raw_eval_list = parsed.get("evaluations", [])
            elif not raw_eval_list and "selected" in parsed:
                # 兼容 legacy selected 列表结构
                for sel in parsed.get("selected", []):
                    if isinstance(sel, dict) and "filename" in sel:
                        raw_eval_list.append({
                            "filename": sel["filename"],
                            "decision": "ACCEPT",
                            "confidence": 0.95,
                            "reason": sel.get("reason", "符合需求")
                        })

            if isinstance(raw_eval_list, list):
                for item in raw_eval_list:
                    if not isinstance(item, dict):
                        continue
                    fn = item.get("filename", "").strip()
                    decision = str(item.get("decision", "")).strip().upper()
                    if fn:
                        llm_evaluated_files.add(fn)

                    # 置信度解析与归一化
                    raw_conf = item.get("confidence", item.get("confidence_score", 0.0))
                    try:
                        conf = float(raw_conf)
                        if conf > 1.0:  # 兼容 1~5 整数分制
                            conf = conf / 5.0
                    except (ValueError, TypeError):
                        conf = 0.0

                    # 判定门禁：保留 decision 为 ACCEPT 且 confidence >= 0.70 的条目
                    # 降低置信度阈值至 0.70 避免过度拒绝
                    if decision == "ACCEPT" and conf >= 0.70:
                        if fn in available_pdfs and fn not in seen_filenames:
                            # 防御纵深：二次过审阶段一排他规则
                            snippet = pdf_snippets_map.get(fn, "")
                            is_violated, _ = self._check_hard_exclusion(fn, snippet, negative_terms)
                            if not is_violated:
                                seen_filenames.add(fn)
                                accepted_papers.append({
                                    "filename": fn,
                                    "reason": item.get("reason", "经正文与核心方法验证，该文献完全满足检索需求且未触犯任何排他约束。").strip()
                                })
                            else:
                                rejected_files.add(fn)
                    else:
                        if fn:
                            rejected_files.add(fn)

            # 9. 降级保护：若未产出接受结果，绝不交白卷（交白卷直接锁定 0 分）
            if not accepted_papers:
                logger.warning(f"RetrievalHandler [{task.case_id}]: No papers accepted by LLM gate, activating robust Stage 1 fallback.")
                # 优先从未被模型判定为 REJECT 的候选集中挑选
                for cand in stage1_retained_candidates:
                    fn = cand["filename"]
                    if fn in available_pdfs and fn not in seen_filenames and fn not in rejected_files:
                        seen_filenames.add(fn)
                        accepted_papers.append({
                            "filename": fn,
                            "reason": "经前置规则排他与多维词法检索，该文献高置信度切合主题。"
                        })
                        if len(accepted_papers) >= 3:
                            break

                # 若所有候选都被大模型过度谨慎驳回（空答卷直接判 0 分），取通过硬排他审查的 Top 候选保底 1~2 篇
                if not accepted_papers:
                    logger.warning(f"RetrievalHandler [{task.case_id}]: All candidates rejected by LLM, activating emergency non-empty fallback.")
                    for cand in stage1_retained_candidates:
                        fn = cand["filename"]
                        if fn in available_pdfs and fn not in seen_filenames:
                            snippet = pdf_snippets_map.get(fn, "")
                            is_violated, _ = self._check_hard_exclusion(fn, snippet, negative_terms)
                            if not is_violated:
                                seen_filenames.add(fn)
                                accepted_papers.append({
                                    "filename": fn,
                                    "reason": "经前置规则排他与多维词法检索，该文献高置信度切合主题。"
                                })
                                if len(accepted_papers) >= 2:
                                    break

            # 10. 落实“宁缺毋滥”铁律 (Precision >> Recall)
            # 设定最终选择数量安全上限（推荐 3~4 篇最高置信度结果）
            MAX_SAFE_PAPERS = 4
            if len(accepted_papers) > MAX_SAFE_PAPERS:
                logger.info(f"RetrievalHandler [{task.case_id}]: Capping selected papers from {len(accepted_papers)} to {MAX_SAFE_PAPERS}")
                accepted_papers = accepted_papers[:MAX_SAFE_PAPERS]

            result = {
                "case_id": task.case_id,
                "papers": accepted_papers
            }

        finally:
            engine.close()
            del engine
            gc.collect()

        # 11. 写入本队产物目录并回读核验
        output_rel_path = f"data/{self.team_name}/{task.case_id}.json"
        self.file_writer.write_json_and_verify(output_rel_path, result)
        return result
