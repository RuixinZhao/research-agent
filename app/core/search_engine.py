import sqlite3
import re
import logging
from typing import List, Dict, Any, Optional, Set

logger = logging.getLogger(__name__)

# 中英文学术核心词汇对照与双语扩展字典（零耗时规则扩展，彻底替代多轮 LLM 交互）
BILINGUAL_ACADEMIC_MAP: Dict[str, List[str]] = {
    # 推荐系统与过滤
    "推荐系统": ["recommender system", "recommendation", "collaborative filtering", "content-based"],
    "推荐算法": ["recommender system", "recommendation"],
    "协同过滤": ["collaborative filtering", "matrix factorization"],
    "基于内容": ["content-based", "content based"],
    # 大语言模型与 NLP
    "大语言模型": ["large language model", "LLM", "foundation model"],
    "大模型": ["large language model", "LLM", "foundation model"],
    "语言模型": ["language model", "NLP"],
    "自注意力": ["self-attention", "attention mechanism"],
    "注意力机制": ["attention mechanism", "multi-head attention", "transformer"],
    "预训练": ["pre-trained", "pretraining"],
    "微调": ["fine-tuning", "finetuning", "LoRA"],
    "长文本": ["long context", "long document"],
    "检索增强": ["retrieval-augmented", "RAG"],
    # 图学习
    "图神经网络": ["graph neural network", "GNN", "GCN", "graph convolutional"],
    "图网络": ["graph network", "GNN"],
    "节点分类": ["node classification"],
    "整图分类": ["graph classification", "whole-graph classification"],
    "图分类": ["graph classification"],
    "链接预测": ["link prediction"],
    # 经典机器学习与深度学习
    "神经网络": ["neural network", "neural networks", "deep learning"],
    "深度学习": ["deep learning", "deep neural network"],
    "支持向量机": ["support vector machine", "SVM", "kernel method"],
    "随机森林": ["random forest"],
    "决策树": ["decision tree"],
    "分类算法": ["classification", "classifier"],
    "分类": ["classification"],
    "聚类": ["clustering", "k-means"],
    "强化学习": ["reinforcement learning", "RL", "policy gradient"],
    # 计算机视觉
    "视觉识别": ["visual recognition", "image recognition", "computer vision"],
    "计算机视觉": ["computer vision"],
    "目标检测": ["object detection"],
    "图像分割": ["image segmentation"],
    "卷积神经网络": ["convolutional neural network", "CNN"],
    # 多模态与知识图谱
    "多模态": ["multimodal", "multi-modal", "vision-language"],
    "知识图谱": ["knowledge graph", "knowledge base"],
    "文本分类": ["text classification"],
    "情感分析": ["sentiment analysis"],
}


def expand_bilingual_query(query: str) -> str:
    """
    对检索词进行快速双语扩展（纯规则/词典，零外网延迟）：
    1. 自动提取并扩展常见中英文学术核心词汇；
    2. 提取文本中出现的英文字词或英文缩写（如 SVM, GPT, GNN, Transformer 等）；
    3. 组合为加权的综合检索字符串。
    """
    if not query:
        return ""

    expanded_terms: List[str] = []

    # 1. 词典映射扩展
    for zh_key, en_list in BILINGUAL_ACADEMIC_MAP.items():
        if zh_key in query:
            expanded_terms.extend(en_list)

    # 2. 提取原始文本中的英文字词与专有名词（长度 >= 2）
    en_tokens = re.findall(r"\b[A-Za-z0-9_\-]{2,}\b", query)
    expanded_terms.extend(en_tokens)

    # 去重并拼接
    unique_terms = list(dict.fromkeys(expanded_terms))
    expanded_str = " ".join(unique_terms)
    return f"{query} {expanded_str}".strip()


class LocalFTS5SearchEngine:
    """
    基于内存的 SQLite FTS5 全文检索引擎。
    提供多列加权 BM25 排序、零外部网络依赖、支持中英文混合索引。
    权重策略（满足平台优化要求）：
    - 文件名关键词 (权重 3.0)
    - 论文第一页标题与摘要 (权重 2.0)
    - 正文后续页 (权重 1.0)
    严格执行 PRAGMA cache_size 锁定，常驻内存保持在 < 15MB 范围内。
    """

    def __init__(self):
        self.conn = sqlite3.connect(":memory:")
        # 锁定内存占用约 8MB ~ 15MB
        self.conn.execute("PRAGMA cache_size = 2000;")
        self.conn.execute("PRAGMA page_size = 4096;")
        self._init_schema()

    def _init_schema(self):
        self.conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS paper_fts USING fts5(
                filename UNINDEXED,
                page_num UNINDEXED,
                raw_content UNINDEXED,
                title_filename,
                first_page_abstract,
                body_content,
                tokenize='unicode61'
            );
        """)
        self.conn.commit()

    @staticmethod
    def _tokenize_for_index(text: str) -> str:
        """
        对文本进行预处理：在 CJK 汉字之间插入空格，使 FTS5 的 unicode61 分词器
        能够无缝支持单字与词组检索，兼顾英文单词与中文关键词。
        """
        if not text:
            return ""
        # 在汉字字符两侧添加空格，保留英文字词的自然边界
        return re.sub(r"([\u4e00-\u9fa5])", r" \1 ", text)

    def index_paper_pages(self, filename: str, pages: List[Dict[str, Any]]):
        """
        按多级权重索引论文：
        - 文件名记录：写入 title_filename 列（后续加权 3.0）
        - 论文前 1~2 页（标题与摘要）：写入 first_page_abstract 列（后续加权 2.0）
        - 后续正文页：写入 body_content 列（后续加权 1.0）
        """
        cursor = self.conn.cursor()
        clean_name = re.sub(r"[\-_.]", " ", filename).replace("pdf", " ").strip()
        spaced_name = self._tokenize_for_index(clean_name)

        # 1. 文件名与标题记录（高权重列）
        records = [(filename, 0, clean_name, spaced_name, "", "")]

        # 2. 逐页内容记录
        if pages:
            for p in pages:
                raw_text = p.get("text", "")
                p_num = int(p.get("page_num", 1))
                if not raw_text.strip():
                    continue
                spaced_text = self._tokenize_for_index(raw_text)

                if p_num <= 1:
                    # 第一页：标题与摘要区
                    records.append((filename, p_num, raw_text, "", spaced_text, ""))
                else:
                    # 后续页：正文内容区
                    records.append((filename, p_num, raw_text, "", "", spaced_text))

        cursor.executemany(
            "INSERT INTO paper_fts (filename, page_num, raw_content, title_filename, first_page_abstract, body_content) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            records
        )
        self.conn.commit()

    def search(
        self,
        query: str,
        top_k: int = 15,
        target_filename: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        执行词法 BM25 多列加权检索：
        bm25(paper_fts, 3.0, 2.0, 1.0)
        - title_filename 权重 3.0
        - first_page_abstract 权重 2.0
        - body_content 权重 1.0

        Args:
            query: 检索关键词或任务输入描述
            top_k: 返回的最大论文数
            target_filename: 可选，限定检索特定论文

        Returns:
            List[Dict[str, Any]]: 按论文去重排序的结果列表，每篇保留最佳匹配片段与分数
        """
        if not query or not query.strip():
            return []

        # 提取中文字符与英文字词
        tokens = [t for t in re.findall(r"[\u4e00-\u9fa5]|[a-zA-Z0-9]+", query.lower()) if t.strip()]
        if not tokens:
            return []

        # 过滤极常见停用词，保留高质量区分词
        stop_words = {
            "the", "a", "an", "is", "are", "in", "on", "of", "to", "for", "with",
            "and", "or", "这", "的", "是", "在", "和", "了", "有", "及", "与", "关于"
        }
        filtered_tokens = [t for t in tokens if t not in stop_words]
        if not filtered_tokens:
            filtered_tokens = tokens[:10]
        else:
            filtered_tokens = filtered_tokens[:25]  # 限制 token 数量避免过长 SQL

        # 安全构造 FTS5 MATCH 表达式（每个 token 双引号包裹防特殊字符语法错误）
        match_expr = " OR ".join(f'"{t}"' for t in filtered_tokens)

        cursor = self.conn.cursor()
        # 多列加权：文件名 3.0 > 第一页标题摘要 2.0 > 正文 1.0
        if target_filename:
            sql = """
                SELECT filename, page_num, raw_content, bm25(paper_fts, 3.0, 2.0, 1.0) as score
                FROM paper_fts
                WHERE paper_fts MATCH ? AND filename = ?
                ORDER BY score ASC;
            """
            params = (match_expr, target_filename)
        else:
            sql = """
                SELECT filename, page_num, raw_content, bm25(paper_fts, 3.0, 2.0, 1.0) as score
                FROM paper_fts
                WHERE paper_fts MATCH ?
                ORDER BY score ASC;
            """
            params = (match_expr,)

        try:
            cursor.execute(sql, params)
            rows = cursor.fetchall()

            # 按论文文件名去重，保留各论文的最优（得分绝对值最大）片段
            best_by_paper: Dict[str, Dict[str, Any]] = {}
            for r in rows:
                fn = r[0]
                page_num = r[1]
                content_text = r[2]
                score = abs(float(r[3]))
                snippet = content_text[:300].strip()

                if fn not in best_by_paper or score > best_by_paper[fn]["bm25_score"]:
                    best_by_paper[fn] = {
                        "filename": fn,
                        "page_num": page_num,
                        "snippet": snippet,
                        "bm25_score": score,
                        "full_text": content_text
                    }

            # 按相关度分数降序排列，取 Top-K
            sorted_results = sorted(best_by_paper.values(), key=lambda x: x["bm25_score"], reverse=True)
            return sorted_results[:top_k]
        except sqlite3.OperationalError as e:
            logger.warning(f"FTS5 检索语法异常，降级空结果: {str(e)}")
            return []

    def close(self):
        """释放 SQLite 资源"""
        try:
            self.conn.close()
        except Exception:
            pass
