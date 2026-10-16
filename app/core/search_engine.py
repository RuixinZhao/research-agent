import sqlite3
import re
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

class LocalFTS5SearchEngine:
    """
    基于内存的 SQLite FTS5 全文检索引擎。
    提供 BM25 排序、零外部网络依赖、支持中英文混合索引。
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
                content,
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
        按页批量插入论文索引。
        """
        if not pages:
            return
        cursor = self.conn.cursor()
        records = []
        for p in pages:
            raw_text = p.get("text", "")
            if not raw_text.strip():
                continue
            spaced_text = self._tokenize_for_index(raw_text)
            records.append((filename, int(p.get("page_num", 1)), raw_text, spaced_text))

        cursor.executemany(
            "INSERT INTO paper_fts (filename, page_num, raw_content, content) VALUES (?, ?, ?, ?)",
            records
        )
        self.conn.commit()

    def search(
        self,
        query: str,
        top_k: int = 10,
        target_filename: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        执行词法 BM25 检索。

        Args:
            query: 用户检索关键词或任务输入描述
            top_k: 返回的最大片段数
            target_filename: 可选，限定检索特定论文

        Returns:
            List[Dict[str, Any]]: 检索结果，包含 filename, page_num, snippet, bm25_score 等
        """
        if not query or not query.strip():
            return []

        # 提取中文字符与英文字词
        tokens = [t for t in re.findall(r"[\u4e00-\u9fa5]|[a-zA-Z0-9]+", query.lower()) if t.strip()]
        if not tokens:
            return []

        # 过滤极常见停用词，保留高质量区分词
        stop_words = {"the", "a", "an", "is", "are", "in", "on", "of", "to", "for", "with", "and", "or", "这", "的", "是", "在", "和"}
        filtered_tokens = [t for t in tokens if t not in stop_words]
        if not filtered_tokens:
            filtered_tokens = tokens[:10]
        else:
            filtered_tokens = filtered_tokens[:20]  # 限制 token 数量避免过长 SQL

        # 安全构造 FTS5 MATCH 表达式（每个 token 双引号包裹防注入与特殊字符语法错误）
        match_expr = " OR ".join(f'"{t}"' for t in filtered_tokens)

        cursor = self.conn.cursor()
        if target_filename:
            sql = """
                SELECT filename, page_num, raw_content, bm25(paper_fts) as score
                FROM paper_fts
                WHERE paper_fts MATCH ? AND filename = ?
                ORDER BY score ASC
                LIMIT ?;
            """
            params = (match_expr, target_filename, top_k)
        else:
            sql = """
                SELECT filename, page_num, raw_content, bm25(paper_fts) as score
                FROM paper_fts
                WHERE paper_fts MATCH ?
                ORDER BY score ASC
                LIMIT ?;
            """
            params = (match_expr, top_k)

        try:
            cursor.execute(sql, params)
            rows = cursor.fetchall()
            results = []
            for r in rows:
                content_text = r[2]
                snippet = content_text[:300].strip()
                results.append({
                    "filename": r[0],
                    "page_num": r[1],
                    "snippet": snippet,
                    "bm25_score": abs(float(r[3])),
                    "full_text": content_text
                })
            return results
        except sqlite3.OperationalError as e:
            logger.warning(f"FTS5 检索语法异常，降级空结果: {str(e)}")
            return []

    def close(self):
        """释放 SQLite 资源"""
        try:
            self.conn.close()
        except Exception:
            pass
