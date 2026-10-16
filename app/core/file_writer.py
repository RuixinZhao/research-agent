import os
import json
from typing import Dict, Any
from app.config import settings

class SecureFileWriter:
    """
    工业级文件写入器与双写一致性回读核验器。
    严防路径越界（..）与写入文件不一致。
    """
    def __init__(self, workspace_root: str = None):
        root = workspace_root or settings.WORKSPACE_OUTPUT
        # 若环境为本地开发且不存在 /output，自动降级至当前目录
        if not os.path.exists(root) and root == "/output":
            root = os.getcwd()
        self.root = os.path.abspath(root)
        self.team_name = settings.RESEARCH_WORKSPACE_TEAM

    def _validate_safe_path(self, target_rel_path: str) -> str:
        target_clean = target_rel_path.lstrip("/")
        abs_path = os.path.abspath(os.path.join(self.root, target_clean))
        if not abs_path.startswith(self.root):
            raise PermissionError(f"Path Traversal Blocked: {target_rel_path}")
        return abs_path

    def write_json_and_verify(self, rel_path: str, data: Dict[str, Any]) -> str:
        abs_path = self._validate_safe_path(rel_path)
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)

        with open(abs_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        if not os.path.exists(abs_path) or os.path.getsize(abs_path) == 0:
            raise IOError(f"Write Verification Failed: {rel_path} is empty or missing")

        with open(abs_path, "r", encoding="utf-8") as f:
            read_back = json.load(f)
            if read_back.get("case_id") != data.get("case_id"):
                raise ValueError(f"Case ID mismatch during read-back verification: {rel_path}")

        return abs_path

    def write_markdown_and_verify(self, rel_path: str, markdown_content: str) -> str:
        abs_path = self._validate_safe_path(rel_path)
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)

        with open(abs_path, "w", encoding="utf-8") as f:
            f.write(markdown_content)

        if not os.path.exists(abs_path) or os.path.getsize(abs_path) == 0:
            raise IOError(f"Write Verification Failed: {rel_path} is empty or missing")

        with open(abs_path, "r", encoding="utf-8") as f:
            read_text = f.read()
            if read_text != markdown_content:
                raise ValueError(f"Markdown content mismatch during read-back verification: {rel_path}")

        return abs_path
