import os
import sys
import json
import shutil
import logging
import subprocess
from pathlib import Path, PurePosixPath
from typing import Dict, Any, List, Optional

from app.config import settings
from app.handlers.base_handler import BaseHandler
from app.schemas.task import ChallengeTaskInput
from app.schemas.response import ReproductionOutput

logger = logging.getLogger(__name__)

class ReproductionHandler(BaseHandler):
    """
    D 类复现任务处理器（分值 40 分，P0 核心优先级）。
    
    核心职责：
    1. 双模环境探测：线上独享 Unix 通道 runner (/data/experiments/run_experiment.py) vs 本地离线执行脚本
    2. 子进程受控调度：硬限 140s 超时防卡死，实时捕获阶段事件
    3. 解析 submission.json，确保指标字段规范与 case_id 严格一致
    4. PNG 图表真实性深度核验：存在性、8 字节魔数签名、PIL 图像完整性、元数据(caption/x_label/y_label/legend)齐全性
    5. 故障/超时/材料缺失合规优雅降级：禁止伪造 observed 指标与图表，准确输出 failed/materials_missing
    6. 双写落盘与一致性回读核验
    """

    TASK_IDS = {
        "D-01": "TASK_D_01_SINGLE_MACHINE",
        "D-02": "TASK_D_02_SINGLE_MACHINE",
        "D-03": "TASK_D_03_SINGLE_MACHINE",
        "D-04": "TASK_D_04_SINGLE_MACHINE",
        "D-05": "TASK_D_05_SINGLE_MACHINE",
    }

    METRIC_SPECS = {
        "D-01": [("Macro-F1", "分数"), ("Accuracy", "%"), ("运行时间", "秒")],
        "D-02": [("Recall@5", "%"), ("MRR@10", "分数"), ("查询吞吐", "queries/s")],
        "D-03": [("推理吞吐", "samples/s"), ("P95 延迟", "ms"), ("缓存命中率", "%")],
        "D-04": [("验证集准确率", "%"), ("约束通过率", "%"), ("搜索耗时", "分钟")],
        "D-05": [("公平性 Jain 指数", "分数"), ("归一化吞吐", "%"), ("平均等待时间", "ms")],
    }

    PNG_MAGIC_BYTES = b"\x89PNG\r\n\x1a\n"

    def handle(self, task: ChallengeTaskInput, session_id: str) -> Dict[str, Any]:
        case_id = task.case_id.strip()
        logger.info(f"ReproductionHandler: Starting reproduction task for {case_id}")

        official_runner = os.path.join(settings.EXPERIMENTS_DIR, "run_experiment.py")
        if not os.path.exists(official_runner):
            official_runner = "/data/experiments/run_experiment.py"

        # 1. 确定运行模式与执行命令
        is_online = os.path.exists(official_runner)
        work_dir = os.path.join(self.file_writer.root, f"data/{self.team_name}/work/{case_id}")
        os.makedirs(work_dir, exist_ok=True)

        env = os.environ.copy()
        env["RESEARCH_EXPERIMENT_CASE"] = case_id
        env["RESEARCH_WORKSPACE_TEAM"] = self.team_name
        env["RESEARCH_RESULT_ROOT"] = self.file_writer.root

        if is_online:
            logger.info(f"ReproductionHandler: Online mode detected using {official_runner}")
            cmd = [sys.executable, official_runner, "--case", case_id]
        else:
            logger.info("ReproductionHandler: Local offline mode detected")
            local_script = self._find_local_script()
            data_dir = self._find_data_dir()

            if not local_script or not data_dir:
                logger.error(f"ReproductionHandler: Materials missing for {case_id}")
                return self._fallback(case_id, status="materials_missing")

            # 验证对应题目的数据源文件是否存在
            case_data_file = os.path.join(data_dir, f"{case_id}.json")
            if not os.path.exists(case_data_file):
                logger.error(f"ReproductionHandler: Case data file {case_data_file} not found")
                return self._fallback(case_id, status="materials_missing")

            task_id = self.TASK_IDS.get(case_id, f"TASK_{case_id.replace('-', '_')}_SINGLE_MACHINE")
            cmd = [
                sys.executable,
                local_script,
                "--case", case_id,
                "--output", work_dir,
                "--data", data_dir,
                "--team", self.team_name,
                "--run-id", f"run_{case_id}",
                "--task-id", task_id
            ]

        # 2. 执行子进程调度，硬限 140 秒（预留 10 秒供双写核验与降级处理）
        try:
            logger.info(f"ReproductionHandler: Invoking command: {' '.join(cmd)}")
            proc = subprocess.run(
                cmd,
                env=env,
                capture_output=True,
                text=True,
                timeout=140
            )

            # 解析执行过程中的事件流
            events = self._parse_json_lines(proc.stdout)
            logger.info(f"ReproductionHandler: Subprocess finished with returncode={proc.returncode}, captured {len(events)} events")

            if proc.returncode != 0:
                logger.error(f"ReproductionHandler: Execution failed (code {proc.returncode}): {proc.stderr}")
                return self._fallback(case_id, status="failed")

            # 3. 定位并解析 submission.json
            submission_data = self._locate_and_parse_submission(case_id, work_dir, proc.stdout)
            if not submission_data:
                logger.error("ReproductionHandler: submission.json not found or failed to parse")
                return self._fallback(case_id, status="failed")

            # 确保 case_id 严格一致
            submission_data["case_id"] = case_id

            # 4. 核验 PNG 图表真实性
            if not self._verify_and_sync_figures(case_id, submission_data, work_dir):
                logger.error(f"ReproductionHandler: Figure verification failed for {case_id}")
                return self._fallback(case_id, status="failed")

            # 5. 使用 Pydantic 模型确保结构合规
            validated = ReproductionOutput.model_validate(submission_data)
            final_result = validated.model_dump()

            # 6. 双写落盘至队伍产物目录并回读核验
            rel_json_path = f"data/{self.team_name}/{case_id}.json"
            self.file_writer.write_json_and_verify(rel_json_path, final_result)
            logger.info(f"ReproductionHandler: Successfully completed reproduction for {case_id}")
            return final_result

        except subprocess.TimeoutExpired:
            logger.error(f"ReproductionHandler: Process timeout (140s exceeded) for {case_id}")
            return self._fallback(case_id, status="failed")
        except Exception as e:
            logger.error(f"ReproductionHandler: Unexpected error during execution: {e}", exc_info=True)
            return self._fallback(case_id, status="failed")

    def _locate_and_parse_submission(self, case_id: str, work_dir: str, stdout_text: str) -> Optional[Dict[str, Any]]:
        """从候选位置检索并解析 submission.json"""
        candidate_paths = [
            os.path.join(work_dir, "submission.json"),
            os.path.join(self.file_writer.root, "submission.json"),
            os.path.join(self.file_writer.root, f"data/{self.team_name}/{case_id}.json"),
            os.path.join(f"/tmp/repro_{case_id}", "submission.json")
        ]

        for p in candidate_paths:
            if os.path.isfile(p) and os.path.getsize(p) > 0:
                try:
                    with open(p, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if isinstance(data, dict) and data.get("status") == "completed":
                        return data
                except Exception as e:
                    logger.debug(f"Failed to read submission from {p}: {e}")

        # 尝试从 stdout 最后一行解析（线上 run_experiment.py 会将 submission 序列化打印到 stdout）
        if stdout_text:
            lines = [l.strip() for l in stdout_text.splitlines() if l.strip()]
            for line in reversed(lines):
                if line.startswith("{") and line.endswith("}"):
                    try:
                        data = json.loads(line)
                        if isinstance(data, dict) and "metrics" in data and "figures" in data:
                            return data
                    except Exception:
                        pass
        return None

    def _verify_and_sync_figures(self, case_id: str, submission: Dict[str, Any], work_dir: str) -> bool:
        """
        核验 PNG 图表真实性：
        1. 路径规范与实体文件存在性（若在 work 目录则同步复制到队伍公开目标目录）
        2. 8 字节 PNG 真实二进制魔数核验
        3. PIL 完整性校验（阻断空文件、损坏文件）
        4. 元数据完整性核验：caption, x_label, y_label, legend 均不得为空
        """
        figures = submission.get("figures", [])
        if not isinstance(figures, list) or len(figures) == 0:
            logger.warning(f"No figures reported for {case_id}")
            return False

        for fig in figures:
            if not isinstance(fig, dict):
                return False

            # 元数据完整性检查
            for field in ("caption", "x_label", "y_label", "legend"):
                val = str(fig.get(field, "")).strip()
                if not val:
                    logger.error(f"Figure field '{field}' is missing or empty in {case_id}")
                    return False

            rel_path = fig.get("path", "")
            if not rel_path or ".." in rel_path:
                logger.error(f"Invalid figure relative path: {rel_path}")
                return False

            # 寻找实际生成的图表源文件
            possible_source_paths = [
                os.path.join(work_dir, rel_path),
                os.path.join(self.file_writer.root, rel_path),
                os.path.join(work_dir, "data", "figure", self.team_name, f"{case_id}.png"),
                os.path.join(self.file_writer.root, "data", "figure", self.team_name, f"{case_id}.png")
            ]

            actual_src = None
            for p in possible_source_paths:
                if os.path.isfile(p) and os.path.getsize(p) > 0:
                    actual_src = p
                    break

            if not actual_src:
                logger.error(f"Figure file not found anywhere for {rel_path}")
                return False

            # 确保文件被同步拷贝到标准产物路径: self.file_writer.root / rel_path
            canonical_target = os.path.join(self.file_writer.root, rel_path)
            if os.path.abspath(actual_src) != os.path.abspath(canonical_target):
                os.makedirs(os.path.dirname(canonical_target), exist_ok=True)
                shutil.copyfile(actual_src, canonical_target)

            # 核验目标文件真实性
            if not os.path.isfile(canonical_target) or os.path.getsize(canonical_target) == 0:
                logger.error(f"Canonical figure target {canonical_target} missing or empty")
                return False

            # 1. 8 字节 PNG 魔数校验
            try:
                with open(canonical_target, "rb") as f:
                    header = f.read(8)
                    if header != self.PNG_MAGIC_BYTES:
                        logger.error(f"Figure {canonical_target} is not a valid PNG (invalid magic header: {header})")
                        return False
            except Exception as e:
                logger.error(f"Error checking PNG magic bytes: {e}")
                return False

            # 2. PIL 图像校验
            try:
                from PIL import Image
                with Image.open(canonical_target) as img:
                    img.verify()
            except Exception as e:
                logger.error(f"PIL verification failed for {canonical_target}: {e}")
                return False

        return True

    def _fallback(self, case_id: str, status: str = "failed") -> Dict[str, Any]:
        """
        合规优雅降级输出：
        绝不编造 observed 指标与图表，指标一律置为 null，图表置空。
        同时落盘写入产物目录并回读核验。
        """
        logger.warning(f"ReproductionHandler: Fallback triggered for {case_id} with status '{status}'")
        metric_items = []
        specs = self.METRIC_SPECS.get(case_id)
        if specs:
            for name, unit in specs:
                metric_items.append({
                    "name": name,
                    "unit": unit,
                    "reference": None,
                    "observed": None,
                    "relative_error": None
                })
        else:
            for i in range(1, 4):
                metric_items.append({
                    "name": f"Metric_{i}",
                    "unit": "unit",
                    "reference": None,
                    "observed": None,
                    "relative_error": None
                })

        fallback_result = {
            "case_id": case_id,
            "status": status,
            "metrics": metric_items,
            "figures": []
        }

        # 写入队伍目录并核验
        rel_json_path = f"data/{self.team_name}/{case_id}.json"
        try:
            self.file_writer.write_json_and_verify(rel_json_path, fallback_result)
        except Exception as e:
            logger.error(f"ReproductionHandler: Failed to write fallback result to disk: {e}")

        return fallback_result

    def _find_local_script(self) -> Optional[str]:
        """定位本地离线实验脚本 experiment.py"""
        candidates = [
            os.path.join(os.getcwd(), "research-experiments", "experiment.py"),
            os.path.join(os.path.dirname(__file__), "..", "..", "research-experiments", "experiment.py"),
            os.path.join(os.getcwd(), "research-experiments", "repo", "experiment.py"),
            os.path.join(os.path.dirname(__file__), "..", "..", "research-experiments", "repo", "experiment.py"),
        ]
        for c in candidates:
            abs_c = os.path.abspath(c)
            if os.path.isfile(abs_c):
                return abs_c
        return None

    def _find_data_dir(self) -> Optional[str]:
        """定位本地公开实验数据目录"""
        candidates = [
            os.path.join(os.getcwd(), "research-experiments", "publicdata"),
            os.path.join(os.getcwd(), "research-experiments", "data"),
            os.path.join(os.path.dirname(__file__), "..", "..", "research-experiments", "publicdata"),
            os.path.join(os.path.dirname(__file__), "..", "..", "research-experiments", "data"),
        ]
        for c in candidates:
            abs_c = os.path.abspath(c)
            if os.path.isdir(abs_c):
                return abs_c
        return None

    def _parse_json_lines(self, stdout_text: str) -> List[Dict[str, Any]]:
        """解析 stdout 中输出的 JSON Lines 事件"""
        events = []
        if not stdout_text:
            return events
        for line in stdout_text.splitlines():
            line = line.strip()
            if line.startswith("{") and line.endswith("}"):
                try:
                    events.append(json.loads(line))
                except Exception:
                    pass
        return events
