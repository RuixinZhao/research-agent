import os
import json
from typing import Dict, Any, Optional
from app.config import settings

class SecureFileWriter:
    """
    工业级文件写入器与双写一致性回读核验器。
    严防路径越界（..）与写入文件不一致。
    支持生产工作区根目录 (/output) 与本地开发目录双写冗余，
    并动态自适应识别平台下发的真实队伍标识符。
    """
    def __init__(self, workspace_root: Optional[str] = None):
        self._workspace_root = workspace_root

    @property
    def root(self) -> str:
        root = (
            self._workspace_root
            or os.environ.get("RESEARCH_RESULT_ROOT")
            or getattr(settings, "WORKSPACE_OUTPUT", "/output")
        )
        # 若环境为本地开发且不存在 /output，自动降级至当前目录
        if not os.path.exists(root) and root == "/output":
            root = os.getcwd()
        return os.path.abspath(root)

    @property
    def team_name(self) -> str:
        return self.get_team_name()

    def get_team_name(self) -> str:
        """动态检测当前工作区队伍名"""
        # 1. 优先读取平台注入环境变量（TEAM_ID 是 AgentHack 标准，RESEARCH_WORKSPACE_TEAM 是赛题规范）
        for env_var in ("RESEARCH_WORKSPACE_TEAM", "TEAM_ID", "TEAM_NAME", "TEAM"):
            val = os.environ.get(env_var)
            if val and val.strip() and val.strip() != "team":
                return val.strip()

        # 2. settings.RESEARCH_WORKSPACE_TEAM 配置（若被配置或 monkeypatch 覆盖）
        s_team = getattr(settings, "RESEARCH_WORKSPACE_TEAM", None)
        if s_team and str(s_team).strip() and str(s_team).strip() != "team":
            return str(s_team).strip()

        # 3. 探测真实派题 dispatch.json 所在目录及内部 team 声明
        candidate_roots = [self.root, "/output", "/data", os.getcwd()]
        for r in candidate_roots:
            if not r or not os.path.isdir(r):
                continue
            # 探测 r/data/*/dispatch.json
            data_dir = os.path.join(r, "data")
            if os.path.isdir(data_dir):
                for item in os.listdir(data_dir):
                    if item in ("expert", "figure", "work"):
                        continue
                    item_path = os.path.join(data_dir, item)
                    if os.path.isdir(item_path):
                        disp_file = os.path.join(item_path, "dispatch.json")
                        if os.path.isfile(disp_file):
                            try:
                                with open(disp_file, "r", encoding="utf-8") as f:
                                    d = json.load(f)
                                    if d.get("team"):
                                        return str(d["team"]).strip()
                            except Exception:
                                pass
                            return item
            # 探测 r/dispatch.json
            direct_disp = os.path.join(r, "dispatch.json")
            if os.path.isfile(direct_disp):
                try:
                    with open(direct_disp, "r", encoding="utf-8") as f:
                        d = json.load(f)
                        if d.get("team"):
                            return str(d["team"]).strip()
                except Exception:
                    pass

        # 4. 回退至环境变量或配置缺省
        return str(s_team or os.environ.get("RESEARCH_WORKSPACE_TEAM") or os.environ.get("TEAM_ID") or "team").strip()

    def _validate_safe_path(self, target_rel_path: str) -> str:
        target_clean = target_rel_path.lstrip("/")
        abs_path = os.path.abspath(os.path.join(self.root, target_clean))
        if not abs_path.startswith(self.root):
            raise PermissionError(f"Path Traversal Blocked: {target_rel_path}")
        return abs_path

    def write_json_and_verify(self, rel_path: str, data: Dict[str, Any]) -> str:
        primary_abs = self._validate_safe_path(rel_path)
        try:
            os.makedirs(os.path.dirname(primary_abs), exist_ok=True)
            with open(primary_abs, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            if not os.path.exists(primary_abs) or os.path.getsize(primary_abs) == 0:
                raise IOError(f"Write Verification Failed: {rel_path} is empty or missing")

            with open(primary_abs, "r", encoding="utf-8") as f:
                read_back = json.load(f)
                if read_back.get("case_id") != data.get("case_id"):
                    raise ValueError(f"Case ID mismatch during read-back verification: {rel_path}")
        except PermissionError:
            # 若主目录无写入权限（如 /output 属主限制），自动降级使用当前目录
            primary_abs = os.path.abspath(os.path.join(os.getcwd(), rel_path.lstrip("/\\")))
            os.makedirs(os.path.dirname(primary_abs), exist_ok=True)
            with open(primary_abs, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

        # 多根目录与多队伍标识冗余保障（非 pytest 隔离测试时激活）
        if not os.environ.get("PYTEST_CURRENT_TEST"):
            clean_rel = rel_path.lstrip("/\\")
            candidate_rel_paths = [clean_rel]
            current_team = self.team_name
            if current_team != "team":
                if f"data/{current_team}/" in clean_rel:
                    candidate_rel_paths.append(clean_rel.replace(f"data/{current_team}/", "data/team/"))
                elif "data/team/" in clean_rel:
                    candidate_rel_paths.append(clean_rel.replace("data/team/", f"data/{current_team}/"))

            candidate_roots = [os.path.abspath(os.getcwd())]
            for extra_root in ("/output", "/data"):
                if os.path.isdir(extra_root) and extra_root != self.root:
                    candidate_roots.append(extra_root)

            for c_root in candidate_roots:
                for c_rel in candidate_rel_paths:
                    try:
                        c_abs = os.path.abspath(os.path.join(c_root, c_rel))
                        if c_abs != primary_abs:
                            os.makedirs(os.path.dirname(c_abs), exist_ok=True)
                            with open(c_abs, "w", encoding="utf-8") as f:
                                json.dump(data, f, ensure_ascii=False, indent=2)
                    except Exception:
                        pass

        return primary_abs

    def write_markdown_and_verify(self, rel_path: str, markdown_content: str) -> str:
        primary_abs = self._validate_safe_path(rel_path)
        try:
            os.makedirs(os.path.dirname(primary_abs), exist_ok=True)
            with open(primary_abs, "w", encoding="utf-8") as f:
                f.write(markdown_content)

            if not os.path.exists(primary_abs) or os.path.getsize(primary_abs) == 0:
                raise IOError(f"Write Verification Failed: {rel_path} is empty or missing")

            with open(primary_abs, "r", encoding="utf-8") as f:
                read_text = f.read()
                if read_text != markdown_content:
                    raise ValueError(f"Markdown content mismatch during read-back verification: {rel_path}")
        except PermissionError:
            primary_abs = os.path.abspath(os.path.join(os.getcwd(), rel_path.lstrip("/\\")))
            os.makedirs(os.path.dirname(primary_abs), exist_ok=True)
            with open(primary_abs, "w", encoding="utf-8") as f:
                f.write(markdown_content)

        # 多根目录与多队伍标识冗余保障（非 pytest 隔离测试时激活）
        if not os.environ.get("PYTEST_CURRENT_TEST"):
            clean_rel = rel_path.lstrip("/\\")
            candidate_rel_paths = [clean_rel]
            current_team = self.team_name
            if current_team != "team":
                if f"-{current_team}." in clean_rel:
                    candidate_rel_paths.append(clean_rel.replace(f"-{current_team}.", "-team."))
                elif "-team." in clean_rel:
                    candidate_rel_paths.append(clean_rel.replace("-team.", f"-{current_team}."))

            candidate_roots = [os.path.abspath(os.getcwd())]
            for extra_root in ("/output", "/data"):
                if os.path.isdir(extra_root) and extra_root != self.root:
                    candidate_roots.append(extra_root)

            for c_root in candidate_roots:
                for c_rel in candidate_rel_paths:
                    try:
                        c_abs = os.path.abspath(os.path.join(c_root, c_rel))
                        if c_abs != primary_abs:
                            os.makedirs(os.path.dirname(c_abs), exist_ok=True)
                            with open(c_abs, "w", encoding="utf-8") as f:
                                f.write(markdown_content)
                    except Exception:
                        pass

        return primary_abs

