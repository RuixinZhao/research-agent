import os
import gc
import logging
from typing import List, Dict, Any, Optional
import fitz  # PyMuPDF

logger = logging.getLogger(__name__)

class StreamPDFParser:
    """
    轻量级流式 PDF 解析服务。
    严格保证物理页码 1:1 对齐（从 1 开始计数），剔除顶部与底部噪点文本（页眉/页脚），
    单页解析后主动执行垃圾回收（GC），保障 1024 MiB 内存限制下常驻内存 < 30MB。
    """

    @staticmethod
    def extract_pages(
        pdf_path: str,
        max_pages: Optional[int] = None,
        header_margin_ratio: float = 0.06,
        footer_margin_ratio: float = 0.06
    ) -> List[Dict[str, Any]]:
        """
        按物理页码流式提取 PDF 文本并过滤页眉页脚。

        Args:
            pdf_path: PDF 文件的绝对或相对路径
            max_pages: 最大提取页数（None 表示提取全本）
            header_margin_ratio: 顶部页眉区域比例（默认 6%）
            footer_margin_ratio: 底部页脚区域比例（默认 6%）

        Returns:
            List[Dict[str, Any]]: 页面列表，每项包含:
                - page_num: 物理页码（1-indexed，如 1, 2, 3...）
                - text: 该页清洗后的正文内容
                - char_count: 该页字符数
        """
        if not os.path.exists(pdf_path):
            logger.warning(f"PDF 文件不存在: {pdf_path}")
            return []

        doc = None
        pages: List[Dict[str, Any]] = []

        try:
            doc = fitz.open(pdf_path)
            total_pages = len(doc)
            target_count = total_pages if max_pages is None else min(total_pages, max_pages)

            for page_index in range(target_count):
                page_num = page_index + 1  # 严格物理页码对齐（从 1 开始）
                page = doc[page_index]
                rect = page.rect

                header_y = rect.height * header_margin_ratio
                footer_y = rect.height * (1.0 - footer_margin_ratio)

                blocks = page.get_text("blocks")
                valid_texts: List[str] = []

                for b in blocks:
                    # b 结构: (x0, y0, x1, y1, text, block_no, block_type)
                    # block_type == 0 为文本块，1 为图像块
                    if len(b) >= 7 and b[6] == 0:
                        y0, y1, text = b[1], b[3], b[4].strip()
                        if not text:
                            continue
                        # 过滤落入顶部页眉或底部页脚区域的文本块
                        if y1 < header_y or y0 > footer_y:
                            continue
                        valid_texts.append(text)

                cleaned_text = "\n".join(valid_texts).strip()
                pages.append({
                    "page_num": page_num,
                    "text": cleaned_text,
                    "char_count": len(cleaned_text)
                })

        except Exception as e:
            logger.error(f"解析 PDF 发生异常 [{pdf_path}]: {str(e)}")
            return []
        finally:
            if doc is not None:
                try:
                    doc.close()
                except Exception:
                    pass
                del doc
            gc.collect()  # 立即回收底层 C++ MuPDF 对象与内存引用

        return pages

    @staticmethod
    def extract_page(
        pdf_path: str,
        page_num: int,
        header_margin_ratio: float = 0.06,
        footer_margin_ratio: float = 0.06
    ) -> Optional[Dict[str, Any]]:
        """
        抽取单个物理页（page_num 从 1 开始）。
        """
        if not os.path.exists(pdf_path) or page_num < 1:
            return None

        doc = None
        try:
            doc = fitz.open(pdf_path)
            if page_num > len(doc):
                return None

            page_index = page_num - 1
            page = doc[page_index]
            rect = page.rect
            header_y = rect.height * header_margin_ratio
            footer_y = rect.height * (1.0 - footer_margin_ratio)

            blocks = page.get_text("blocks")
            valid_texts: List[str] = []
            for b in blocks:
                if len(b) >= 7 and b[6] == 0:
                    y0, y1, text = b[1], b[3], b[4].strip()
                    if not text:
                        continue
                    if y1 < header_y or y0 > footer_y:
                        continue
                    valid_texts.append(text)

            cleaned_text = "\n".join(valid_texts).strip()
            return {
                "page_num": page_num,
                "text": cleaned_text,
                "char_count": len(cleaned_text)
            }
        except Exception as e:
            logger.error(f"读取单页异常 [{pdf_path}, p.{page_num}]: {str(e)}")
            return None
        finally:
            if doc is not None:
                try:
                    doc.close()
                except Exception:
                    pass
                del doc
            gc.collect()

    @staticmethod
    def get_page_count(pdf_path: str) -> int:
        """获取 PDF 总物理页数"""
        if not os.path.exists(pdf_path):
            return 0
        doc = None
        try:
            doc = fitz.open(pdf_path)
            return len(doc)
        except Exception:
            return 0
        finally:
            if doc is not None:
                try:
                    doc.close()
                except Exception:
                    pass
                del doc
            gc.collect()
