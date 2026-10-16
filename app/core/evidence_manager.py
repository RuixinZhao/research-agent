import re
import logging
from dataclasses import dataclass, field
from typing import List, Dict, Set, Optional, Tuple, Any

logger = logging.getLogger(__name__)

@dataclass
class EvidenceCard:
    """
    科学证据卡片（PaperQA2 风格带物理页预锚定标签）。
    """
    tag: str             # 唯一机器锚点标签，例如 <<DOC_1_PAGE_3_CHUNK_0>>
    paper_id: int        # 文献序号 [1], [2]...
    page_num: int        # 物理页码（从 1 开始，1:1 对齐原 PDF）
    chunk_id: int        # 该页内的片段序号
    filename: str        # 完整文件名
    text: str            # 原文纯净文本
    char_count: int      # 字符数

class EvidenceManager:
    """
    物理页预锚定标签证据管理器（PaperQA2 架构）。
    在解析 PDF 物理页时为每个文本片段生成唯一机器锚点标签。
    模型在撰写综述时必须且只能使用机器锚点进行引用，彻底杜绝手写页码造成的幻觉。
    """
    def __init__(self):
        self.cards: List[EvidenceCard] = []
        self.tag_to_card: Dict[str, EvidenceCard] = {}
        self.paper_to_valid_pages: Dict[int, Set[int]] = {}
        self.paper_meta: Dict[int, Dict[str, Any]] = {}

    def register_paper(self, paper_id: int, filename: str, title: str = ""):
        """注册文献基础信息"""
        self.paper_meta[paper_id] = {
            "filename": filename,
            "title": title or filename.replace("_", " ").replace("-", " "),
        }
        if paper_id not in self.paper_to_valid_pages:
            self.paper_to_valid_pages[paper_id] = set()

    def add_page_chunks(
        self,
        paper_id: int,
        filename: str,
        page_num: int,
        page_text: str,
        max_chunk_len: int = 500
    ) -> List[EvidenceCard]:
        """
        按物理页切分生成带唯一机器锚点的证据卡片。
        """
        if paper_id not in self.paper_meta:
            self.register_paper(paper_id, filename)

        self.paper_to_valid_pages[paper_id].add(page_num)

        cleaned_text = page_text.strip()
        if not cleaned_text:
            return []

        # 切分逻辑：优先按自然段落分块，若单个段落过长则截断
        paragraphs = [p.strip() for p in cleaned_text.split("\n\n") if p.strip()]
        chunks_text: List[str] = []
        current_chunk = ""

        for p in paragraphs:
            if len(current_chunk) + len(p) <= max_chunk_len:
                current_chunk = f"{current_chunk}\n\n{p}".strip() if current_chunk else p
            else:
                if current_chunk:
                    chunks_text.append(current_chunk)
                current_chunk = p[:max_chunk_len]
        if current_chunk:
            chunks_text.append(current_chunk)

        # 若无段落分隔，直接切分
        if not chunks_text:
            chunks_text = [cleaned_text[:max_chunk_len]]

        # 最多保留前 3 个核心 chunk 以控制 prompt 长度
        chunks_text = chunks_text[:3]

        new_cards = []
        for c_idx, chunk_content in enumerate(chunks_text):
            tag = f"<<DOC_{paper_id}_PAGE_{page_num}_CHUNK_{c_idx}>>"
            card = EvidenceCard(
                tag=tag,
                paper_id=paper_id,
                page_num=page_num,
                chunk_id=c_idx,
                filename=filename,
                text=chunk_content,
                char_count=len(chunk_content)
            )
            self.cards.append(card)
            self.tag_to_card[tag] = card
            new_cards.append(card)

        return new_cards

    def format_evidence_context_for_prompt(self, max_total_chunks: int = 15) -> str:
        """
        输出提供给 LLM 的格式化证据上下文，强调机器锚点标签。
        """
        selected_cards = self.cards[:max_total_chunks]
        lines = []
        for c in selected_cards:
            lines.append(
                f"【机器证据锚点: {c.tag}】(文献[{c.paper_id}]: {c.filename}, 物理页码: p.{c.page_num}):\n"
                f"{c.text}\n"
            )
        return "\n".join(lines)

    def get_card(self, tag: str) -> Optional[EvidenceCard]:
        return self.tag_to_card.get(tag)

    def get_paper_valid_pages(self, paper_id: int) -> Set[int]:
        return self.paper_to_valid_pages.get(paper_id, set())

    def get_all_valid_pages_map(self) -> Dict[int, Set[int]]:
        return self.paper_to_valid_pages

    def get_all_tags(self) -> Set[str]:
        return set(self.tag_to_card.keys())

    def get_bibliography_text(self) -> str:
        """生成合规的标准参考文献列表"""
        lines = []
        for p_id in sorted(self.paper_meta.keys()):
            meta = self.paper_meta[p_id]
            lines.append(f"[{p_id}] {meta['title']}. 文件名: {meta['filename']}")
        return "\n".join(lines)

    def clear(self):
        self.cards.clear()
        self.tag_to_card.clear()
        self.paper_to_valid_pages.clear()
        self.paper_meta.clear()
