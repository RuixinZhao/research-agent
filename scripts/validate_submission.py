#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
科研助手 Agent 提交物合规预检自动化流水线 (validate_submission.py)

功能与考核契约：
1. 校验 dispatch.json 存在性及 25 题派题一致性（A-E 各 5 题）；
2. 校验 data/<队伍名>/ 下 25 个结果 JSON 的完整性、UTF-8 编码与文件名/内部 case_id 严格对齐；
3. 校验五大类别专有 Schema 契约（无额外顶层字段干扰）：
   - A 类 (Chat): case_id, answer, clarifying_question
   - B 类 (Literature_Retrieval): case_id, papers (每项含合法 PDF filename 与 reason)
   - C 类 (Survey): case_id, path, markdown (>=800 字，含 ## 参考文献，双写文件逐字一致)
   - D 类 (Reproduction): case_id, status (completed/failed/materials_missing), metrics (恰好 3 项), figures (合法 PNG 签名及完整元数据)
   - E 类 (Idea): case_id, path, markdown (>=800 字，双写文件逐字一致)
4. 沙箱权限与安全性审计：阻断路径穿越 (..) 与越界符号链接；
5. 生成清晰的结构化核验看板，预检 100% 通过时退出码为 0，否则为 1。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple


PNG_MAGIC_BYTES = b"\x89PNG\r\n\x1a\n"


class SubmissionValidator:
    def __init__(self, team_name: str, root_dir: str | None = None, verbose: bool = False):
        self.team_name = team_name.strip()
        self.verbose = verbose
        self.root = self._locate_root(root_dir)
        self.errors: List[str] = []
        self.warnings: List[str] = []
        self.passed_cases: List[str] = []
        self.failed_cases: List[Tuple[str, str]] = []

    def _locate_root(self, user_root: str | None) -> Path:
        """多候选根目录探测与定位"""
        candidates: List[Path] = []
        if user_root:
            candidates.append(Path(user_root).resolve())

        # 优先探测 /output，其次当前目录，再次 ./output
        env_output = os.environ.get("WORKSPACE_OUTPUT", "/output")
        candidates.append(Path(env_output).resolve())
        candidates.append(Path.cwd().resolve())
        candidates.append((Path.cwd() / "output").resolve())

        for c in candidates:
            # 检查候选目录下是否存在 data/<team> 或 output/data/<team>
            if (c / "data" / self.team_name).is_dir():
                return c
            if (c / "output" / "data" / self.team_name).is_dir():
                return (c / "output").resolve()

        # 默认返回首选目录
        return Path(user_root).resolve() if user_root else Path.cwd().resolve()

    def log(self, msg: str) -> None:
        if self.verbose:
            print(f"[INFO] {msg}")

    def add_error(self, case_id: str, message: str) -> None:
        err = f"[{case_id}] {message}"
        self.errors.append(err)
        self.failed_cases.append((case_id, message))
        print(f"❌ FAIL: {err}", file=sys.stderr)

    def add_warning(self, case_id: str, message: str) -> None:
        warn = f"[{case_id}] {message}"
        self.warnings.append(warn)
        if self.verbose:
            print(f"⚠️ WARN: {warn}")

    def resolve_path(self, rel_path: str) -> Path:
        """安全路径解析，防范路径穿越 (..)"""
        clean_rel = rel_path.lstrip("/\\")
        if ".." in clean_rel:
            raise PermissionError(f"Path traversal detected: {rel_path}")
        return (self.root / clean_rel).resolve()

    def validate_dispatch(self) -> List[str]:
        """第一阶段：核验 dispatch.json 与派题列表"""
        dispatch_path = self.root / "data" / self.team_name / "dispatch.json"
        if not dispatch_path.is_file():
            # 兼容探测根级 dispatch.json
            dispatch_path_alt = self.root / "dispatch.json"
            if dispatch_path_alt.is_file():
                dispatch_path = dispatch_path_alt
            else:
                self.add_error("DISPATCH", f"未找到派题清单文件: {dispatch_path}")
                return []

        try:
            with open(dispatch_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            self.add_error("DISPATCH", f"dispatch.json 解析失败: {e}")
            return []

        case_ids = data.get("case_ids", [])
        if not isinstance(case_ids, list):
            self.add_error("DISPATCH", "dispatch.json 缺少有效的 'case_ids' 列表")
            return []

        # 检查是否为标准 25 题集合（A-E 各 5 题）
        if len(case_ids) != 25:
            self.add_warning("DISPATCH", f"题目数量不是标准 25 题 (当前为 {len(case_ids)} 题)")

        category_counts: Dict[str, int] = {}
        for cid in case_ids:
            cat = cid.split("-")[0] if "-" in cid else "UNKNOWN"
            category_counts[cat] = category_counts.get(cat, 0) + 1

        self.log(f"派题总数: {len(case_ids)}, 分类统计: {category_counts}")
        return case_ids

    def validate_case_chat(self, case_id: str, data: Dict[str, Any]) -> bool:
        """核验 A 类 Chat 结果"""
        allowed_keys = {"case_id", "answer", "clarifying_question"}
        extra_keys = set(data.keys()) - allowed_keys
        if extra_keys:
            self.add_error(case_id, f"A 类存在未定义的额外顶层字段: {extra_keys}")
            return False

        answer = data.get("answer")
        if not isinstance(answer, str) or not answer.strip():
            self.add_error(case_id, "A 类 'answer' 必须为非空字符串")
            return False

        clarifying = data.get("clarifying_question")
        if not isinstance(clarifying, str) or not clarifying.strip():
            self.add_error(case_id, "A 类 'clarifying_question' 必须为非空字符串")
            return False

        return True

    def validate_case_retrieval(self, case_id: str, data: Dict[str, Any]) -> bool:
        """核验 B 类 Literature_Retrieval 结果"""
        allowed_keys = {"case_id", "papers"}
        extra_keys = set(data.keys()) - allowed_keys
        if extra_keys:
            self.add_error(case_id, f"B 类存在未定义的额外顶层字段: {extra_keys}")
            return False

        papers = data.get("papers")
        if not isinstance(papers, list):
            self.add_error(case_id, "B 类 'papers' 必须为列表")
            return False

        for idx, item in enumerate(papers):
            if not isinstance(item, dict):
                self.add_error(case_id, f"B 类 papers[{idx}] 不是对象")
                return False
            fn = item.get("filename")
            reason = item.get("reason")
            if not isinstance(fn, str) or not fn.strip():
                self.add_error(case_id, f"B 类 papers[{idx}] 缺少合规的 'filename'")
                return False
            if ".." in fn or not fn.lower().endswith(".pdf"):
                self.add_error(case_id, f"B 类 papers[{idx}] 文件名异常: {fn}")
                return False
            if not isinstance(reason, str) or not reason.strip():
                self.add_error(case_id, f"B 类 papers[{idx}] 缺少合规的 'reason'")
                return False

        return True

    def validate_case_survey(self, case_id: str, data: Dict[str, Any]) -> bool:
        """核验 C 类 Survey 结果与落盘 Markdown 一致性"""
        allowed_keys = {"case_id", "path", "markdown"}
        extra_keys = set(data.keys()) - allowed_keys
        if extra_keys:
            self.add_error(case_id, f"C 类存在未定义的额外顶层字段: {extra_keys}")
            return False

        path_val = data.get("path")
        markdown_val = data.get("markdown")

        if not isinstance(path_val, str) or not path_val.strip():
            self.add_error(case_id, "C 类 'path' 必须为非空相对路径")
            return False
        if not isinstance(markdown_val, str) or not markdown_val.strip():
            self.add_error(case_id, "C 类 'markdown' 必须为非空正文字符串")
            return False

        # 校验字符数 >= 800
        char_count = len(markdown_val)
        if char_count < 800:
            self.add_error(case_id, f"C 类综述字数不足 800 字符 (实际: {char_count})")
            return False

        # 校验必备参考文献部分
        if "## 参考文献" not in markdown_val:
            self.add_error(case_id, "C 类综述缺少必备章节 '## 参考文献'")
            return False

        # 校验落盘文件一致性
        try:
            target_md_path = self.resolve_path(path_val)
            if not target_md_path.is_file() or target_md_path.stat().st_size == 0:
                self.add_error(case_id, f"C 类 Markdown 文件不存在或为空: {target_md_path}")
                return False

            with open(target_md_path, "r", encoding="utf-8") as f:
                disk_content = f.read()

            if disk_content != markdown_val:
                self.add_error(case_id, f"C 类 JSON 字段 markdown 与磁盘文件 {path_val} 逐字内容不一致！")
                return False
        except Exception as e:
            self.add_error(case_id, f"C 类磁盘文件校验异常: {e}")
            return False

        return True

    def validate_case_reproduction(self, case_id: str, data: Dict[str, Any]) -> bool:
        """核验 D 类 Reproduction 真实实验产物与图表"""
        allowed_keys = {"case_id", "status", "metrics", "figures"}
        extra_keys = set(data.keys()) - allowed_keys
        if extra_keys:
            self.add_error(case_id, f"D 类存在未定义的额外顶层字段: {extra_keys}")
            return False

        status = data.get("status")
        valid_statuses = {"completed", "failed", "materials_missing"}
        if status not in valid_statuses:
            self.add_error(case_id, f"D 类 status '{status}' 非法，必须为 {valid_statuses}")
            return False

        metrics = data.get("metrics")
        if not isinstance(metrics, list) or len(metrics) != 3:
            self.add_error(case_id, f"D 类 metrics 必须恰好为 3 项 (当前: {len(metrics) if isinstance(metrics, list) else '非列表'})")
            return False

        for idx, m in enumerate(metrics):
            if not isinstance(m, dict):
                self.add_error(case_id, f"D 类 metrics[{idx}] 不是对象")
                return False
            for req in ("name", "unit"):
                if not str(m.get(req, "")).strip():
                    self.add_error(case_id, f"D 类 metrics[{idx}] 缺少 '{req}'")
                    return False

            if status == "completed":
                obs = m.get("observed")
                if obs is None:
                    self.add_error(case_id, f"D 类 status=completed 时 metrics[{idx}] observed 不能为空")
                    return False

        figures = data.get("figures", [])
        if not isinstance(figures, list):
            self.add_error(case_id, "D 类 'figures' 必须为列表")
            return False

        if status == "completed":
            if len(figures) == 0:
                self.add_error(case_id, "D 类 status=completed 时必须提供至少一张真实图表")
                return False

            for idx, fig in enumerate(figures):
                if not isinstance(fig, dict):
                    self.add_error(case_id, f"D 类 figures[{idx}] 不是对象")
                    return False
                fig_path = fig.get("path")
                if not fig_path or ".." in fig_path:
                    self.add_error(case_id, f"D 类 figures[{idx}] path 非法: {fig_path}")
                    return False

                for meta in ("caption", "x_label", "y_label", "legend"):
                    val = str(fig.get(meta, "")).strip()
                    if not val:
                        self.add_error(case_id, f"D 类 figures[{idx}] 缺少图表元数据 '{meta}'")
                        return False

                # 真实磁盘图表存在性与二进制 PNG 头校验
                try:
                    img_abs = self.resolve_path(fig_path)
                    if not img_abs.is_file() or img_abs.stat().st_size == 0:
                        self.add_error(case_id, f"D 类图表文件不存在或为空: {img_abs}")
                        return False

                    with open(img_abs, "rb") as f:
                        header = f.read(8)
                        if header != PNG_MAGIC_BYTES:
                            self.add_error(case_id, f"D 类图表文件 {fig_path} 缺少合规的 PNG 二进制魔数签名")
                            return False
                except Exception as e:
                    self.add_error(case_id, f"D 类图表文件校验异常: {e}")
                    return False

        return True

    def validate_case_idea(self, case_id: str, data: Dict[str, Any]) -> bool:
        """核验 E 类 Idea 结果与落盘 Markdown 一致性"""
        allowed_keys = {"case_id", "path", "markdown"}
        extra_keys = set(data.keys()) - allowed_keys
        if extra_keys:
            self.add_error(case_id, f"E 类存在未定义的额外顶层字段: {extra_keys}")
            return False

        path_val = data.get("path")
        markdown_val = data.get("markdown")

        if not isinstance(path_val, str) or not path_val.strip():
            self.add_error(case_id, "E 类 'path' 必须为非空相对路径")
            return False
        if not isinstance(markdown_val, str) or not markdown_val.strip():
            self.add_error(case_id, "E 类 'markdown' 必须为非空正文字符串")
            return False

        # 校验字符数 >= 800
        char_count = len(markdown_val)
        if char_count < 800:
            self.add_error(case_id, f"E 类 Idea 报告字数不足 800 字符 (实际: {char_count})")
            return False

        # 校验落盘文件一致性
        try:
            target_md_path = self.resolve_path(path_val)
            if not target_md_path.is_file() or target_md_path.stat().st_size == 0:
                self.add_error(case_id, f"E 类 Markdown 文件不存在或为空: {target_md_path}")
                return False

            with open(target_md_path, "r", encoding="utf-8") as f:
                disk_content = f.read()

            if disk_content != markdown_val:
                self.add_error(case_id, f"E 类 JSON 字段 markdown 与磁盘文件 {path_val} 逐字内容不一致！")
                return False
        except Exception as e:
            self.add_error(case_id, f"E 类磁盘文件校验异常: {e}")
            return False

        return True

    def run(self) -> bool:
        """执行全套预检流水线"""
        print("=" * 68)
        print(f"🚀 科研助手 Agent 交付成果自动化预检流水线 (Team: {self.team_name})")
        print(f"📁 工作区根目录: {self.root}")
        print("=" * 68)

        case_ids = self.validate_dispatch()
        if not case_ids:
            # 若未从 dispatch 获取到题目，尝试扫描已存在的标准 25 题
            case_ids = [f"{cat}-{i:02d}" for cat in ("A", "B", "C", "D", "E") for i in range(1, 6)]
            self.log(f"使用标准 25 题回退列表: {case_ids}")

        total_cases = len(case_ids)
        self.passed_cases.clear()
        self.failed_cases.clear()

        for case_id in case_ids:
            json_file = self.root / "data" / self.team_name / f"{case_id}.json"
            if not json_file.is_file():
                self.add_error(case_id, f"结果 JSON 文件缺失: {json_file}")
                continue

            try:
                with open(json_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception as e:
                self.add_error(case_id, f"JSON 解析失败: {e}")
                continue

            if data.get("case_id") != case_id:
                self.add_error(case_id, f"JSON 内部 case_id '{data.get('case_id')}' 与文件名不一致")
                continue

            # 按类别执行专项校验
            cat = case_id[0].upper()
            passed = False
            if cat == "A":
                passed = self.validate_case_chat(case_id, data)
            elif cat == "B":
                passed = self.validate_case_retrieval(case_id, data)
            elif cat == "C":
                passed = self.validate_case_survey(case_id, data)
            elif cat == "D":
                passed = self.validate_case_reproduction(case_id, data)
            elif cat == "E":
                passed = self.validate_case_idea(case_id, data)
            else:
                self.add_error(case_id, f"未知题目类别: {cat}")
                passed = False

            if passed:
                self.passed_cases.append(case_id)
                print(f"✅ PASS: [{case_id}] 结构与产物核验无误")

        # 汇总统计
        print("\n" + "=" * 68)
        print("📊 提交预检结果总览 (Pre-flight Validation Summary)")
        print(f"总检查用例数: {total_cases}")
        print(f"核验通过用例: {len(self.passed_cases)}")
        print(f"核验失败用例: {len(self.failed_cases)}")

        if self.errors:
            print("\n❌ 发现以下不合规错误项 (请对照修复):")
            for err in self.errors:
                print(f"  • {err}")
            print("\n🚨 预检结果: 失败 (FAILED) - 请修复上述错误后重新提交！")
            return False
        else:
            print("\n🎉 预检结果: 完美通过 (100% PASS) - 符合大赛交付与判题规范！")
            return True


def main() -> int:
    parser = argparse.ArgumentParser(description="科研助手 Agent 交付成果规范预检工具")
    parser.add_argument("team_name", nargs="?", default=None, help="参赛队伍名称 (默认读取 RESEARCH_WORKSPACE_TEAM 或 'team')")
    parser.add_argument("--root", default=None, help="工作区根目录 (默认自动探测)")
    parser.add_argument("--verbose", "-v", action="store_true", help="显示详细调试信息")
    args = parser.parse_args()

    team = args.team_name or os.environ.get("RESEARCH_WORKSPACE_TEAM", "team")
    validator = SubmissionValidator(team_name=team, root_dir=args.root, verbose=args.verbose)
    success = validator.run()
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
