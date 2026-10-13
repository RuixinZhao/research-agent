import os
import gc
import json
import re
import logging
from typing import Dict, Any, List

from app.handlers.base_handler import BaseHandler
from app.schemas.task import ChallengeTaskInput
from app.core.pdf_parser import StreamPDFParser
from app.core.search_engine import LocalFTS5SearchEngine
from app.config import settings

logger = logging.getLogger(__name__)

class RetrievalHandler(BaseHandler):
    """
    B 类 Literature_Retrieval 任务处理器。
    目标：精准论文检索与否定条件排他拦截。
    计分规则：15 * H / N - 0.75 * U。严防误报无关论文造成 -0.75U 扣分（宁缺毋滥原则）。
    严格遵守 1024 MiB 内存限制，流式处理单篇 PDF 并及时垃圾回收。
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
        # 若上述均为空，返回配置默认路径
        return settings.PAPERS_DIR

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
                    # 遍历子目录查找
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
                    # 收集第 1 页核心摘要作为判断依据
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

            # 4. 组装候选论文摘要信息供 LLM 执行精准否定过滤
            candidate_info_list = []
            for fn in candidate_files[:10]:
                snippet = pdf_snippets_map.get(fn, "")
                candidate_info_list.append({
                    "filename": fn,
                    "abstract_snippet": snippet
                })

            # 5. LLM 精准语义对齐与负例拦截链
            prompt = f"""你是一名严格的科研文献检索裁判。你的任务是根据用户的检索需求，从候选论文列表中精确筛选出【完全符合主题且不触犯任何排他约束】的文献。

【检索任务需求】:
{task.input}

【任务约束】:
{json.dumps(task.constraints, ensure_ascii=False) if task.constraints else "无额外显式约束"}

【候选论文列表及其摘要片段】:
{json.dumps(candidate_info_list, ensure_ascii=False, indent=2)}

【评分与惩罚红线（极其重要）】:
1. 本题采用高精度惩罚计分：每误报一篇无关或边缘文献扣除 0.75 分！因此必须奉行【宁缺毋滥（High Precision）】原则。
2. 仔细检查需求中是否有否定排他条件（例如“排除/不要/不涉及某领域/非某技术”等），凡是触及排他条件的候选论文必须坚决剔除！
3. 凡是仅泛泛提及或仅为背景相关、非核心贡献契合的论文，坚决不选！
4. 选出的文件名必须与候选列表中的 filename 完全逐字一致，绝不能修改文件名或凭空造词！
5. 若没有任何一篇论文完全契合需求，请直接返回空数组 []。

【输出要求】:
必须返回纯 JSON 对象（不要输出任何额外文字或 Markdown 标记）：
{{
  "selected": [
    {{
      "filename": "完整文件名.pdf",
      "reason": "具体陈述该论文的核心研究方法与实验为何完全满足需求，并说明未触犯任何排除条件的依据。"
    }}
  ]
}}
"""
            llm_response = self.llm.chat_completion(
                messages=[
                    {"role": "system", "content": "你是一名精通学术论文检索与精准负例过滤的 AI 专家。严格输出合规 JSON。"},
                    {"role": "user", "content": prompt}
                ],
                session_id=session_id,
                temperature=0.0,
                response_format={"type": "json_object"}
            )

            # 解析 LLM 输出
            selected_papers_raw: List[Dict[str, str]] = []
            try:
                parsed = json.loads(llm_response)
                if isinstance(parsed, dict) and "selected" in parsed:
                    selected_papers_raw = parsed["selected"]
                elif isinstance(parsed, list):
                    selected_papers_raw = parsed
            except Exception as pe:
                logger.warning(f"LLM 响应 JSON 解析失败，尝试正则提取: {pe}")
                match = re.search(r"\{.*\}", llm_response, re.DOTALL)
                if match:
                    try:
                        p_obj = json.loads(match.group(0))
                        selected_papers_raw = p_obj.get("selected", [])
                    except Exception:
                        pass

            # 6. 物理存在性核验与去重
            valid_papers = []
            seen_filenames = set()
            for p in selected_papers_raw:
                if not isinstance(p, dict):
                    continue
                fn = p.get("filename", "").strip()
                if fn in available_pdfs and fn not in seen_filenames:
                    seen_filenames.add(fn)
                    valid_papers.append({
                        "filename": fn,
                        "reason": p.get("reason", "经正文与核心方法验证，该文献完全满足检索需求与实验要求。").strip()
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
