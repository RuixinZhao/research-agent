import os
import sys
import json
import shutil
import logging
import subprocess
from pathlib import Path
from typing import Dict, Any, List, Optional

import httpx

from app.config import settings
from app.core.circuit_breaker import TaskTimeoutGuard, TaskTimeoutException
from app.core.model_source import save_source
from app.handlers.base_handler import BaseHandler
from app.schemas.task import ChallengeTaskInput
from app.schemas.response import ReproductionOutput

logger = logging.getLogger(__name__)


class ReproductionHandler(BaseHandler):
    """
    D 类复现任务处理器（分值 40 分，P0 核心优先级）。
    对齐平台最新的 layered-d-v3 规范与 d-model-source-v1 来源验证标准。

    核心流程：
    1. 材料读取：优先从 /data/experiments/{case_id} 读取 method.md, protocol.json, sample.json，
       缺省回退至本地 research-experiments-v1/{case_id}；
    2. 代码生成：通过平台 Gateway 请求模型生成 run_experiment(request) 完整 Python 3.9 代码，
       支持 60s 超时及遇截断 (finish_reason=length) 最多 1 次重试；
    3. 源码提取与落盘：完整保存原始 generation-response.json，并调用 model_source.save_source
       严格校验 finish_reason==stop 与 AST 语法树，提取保存至 implementation.py；
    4. 官方 Runner 调度：在注入环境变量后调用官方 run_experiment.py，解析 stdout 最终答卷 JSON；
    5. 误差计算与图表验真：核验 8 字节 PNG 魔数与 PIL 完整性，计算 relative_error；
    6. 合规优雅降级与 180s 熔断保护：遇材料缺失或执行失败时指标数值一律置为 null，拒绝伪造假数据。
    """

    METRIC_SPECS = {
        "D-01": [("Macro-F1", "分数"), ("Accuracy", "%"), ("运行时间", "秒")],
        "D-02": [("Recall@5", "%"), ("MRR@10", "分数"), ("查询吞吐", "queries/s")],
        "D-03": [("推理吞吐", "samples/s"), ("P95 延迟", "ms"), ("缓存命中率", "%")],
        "D-04": [("验证集准确率", "%"), ("约束通过率", "%"), ("搜索耗时", "分钟")],
        "D-05": [("公平性 Jain 指数", "分数"), ("归一化吞吐", "%"), ("平均等待时间", "ms")],
    }

    PNG_MAGIC_BYTES = b"\x89PNG\r\n\x1a\n"

    def __init__(self):
        super().__init__()

    def _read_experiment_materials(self, case_id: str) -> Dict[str, str]:
        """
        依次读取 method.md、protocol.json、sample.json。
        优先读取 /data/experiments/{case_id}，缺省则回退至本地 research-experiments-v1/{case_id}。
        """
        project_root = Path(__file__).resolve().parents[2]
        candidates = [
            Path("/data/experiments") / case_id,
            Path(settings.EXPERIMENTS_DIR) / case_id,
            project_root / "research-experiments-v1" / case_id,
            Path(os.getcwd()) / "research-experiments-v1" / case_id,
        ]

        target_dir = None
        for cand in candidates:
            if cand.is_dir():
                target_dir = cand
                break

        if not target_dir:
            logger.warning(f"ReproductionHandler: Materials directory not found for {case_id}")
            return {}

        req_files = ["method.md", "protocol.json", "sample.json"]
        materials = {}
        for fname in req_files:
            p = target_dir / fname
            if not p.is_file():
                logger.warning(f"ReproductionHandler: Missing material file {p} for {case_id}")
                return {}
            try:
                materials[fname.split(".")[0]] = p.read_text(encoding="utf-8")
            except Exception as e:
                logger.error(f"ReproductionHandler: Failed to read material {p}: {e}")
                return {}

        return materials

    def _build_generation_prompt(
        self,
        case_id: str,
        materials: Dict[str, str],
        task_input: Optional[str] = None,
        retry_reason: Optional[str] = None
    ) -> str:
        """
        构造严格的代码生成提示词，严禁外部网络请求与非标准库依赖，
        要求仅输出一个包含 def run_experiment(request): 的 ```python 代码块。
        """
        method = materials.get("method", "")
        protocol = materials.get("protocol", "")
        sample = materials.get("sample", "")
        input_desc = str(task_input or f"请复现 {case_id} 实验，输出指标与图表")

        prompt = (
            "请根据以下公开方法和协议，自行实现完整的Python3.9标准库算法。\n"
            "必须定义 def run_experiment(request): 函数，不得联网、打印日志或读取隐藏标签。\n"
            "只返回一个完整的```python代码块，不要省略函数、返回补丁或拆分成多段。\n\n"
            f"【任务信息】\n{input_desc}\n\n"
            f"【公开方法 (method.md)】\n{method}\n\n"
            f"【协议规范 (protocol.json)】\n{protocol}\n\n"
            f"【公开样例 (sample.json)】\n{sample}\n"
        )

        if retry_reason:
            prompt += (
                f"\n【重要重试说明】\n前一次生成失败：{retry_reason}\n"
                "请务必针对上述原因修复，并输出一个单一、完整且无截断的 ```python 代码块。"
            )

        return prompt

    def _call_platform_llm(self, prompt: str, work_dir: Path, timeout: int = 60) -> dict:
        """
        使用 httpx 调用赛事 Gateway 请求大模型生成代码，检查 finish_reason=='stop'。
        若遇截断 (finish_reason=='length') 且时间充裕，执行 1 次重试提示。
        完整保存 generation-response.json（不包含请求头或 API Key）。
        """
        base_url = (
            os.environ.get("PLATFORM_LLM_URL")
            or os.environ.get("CHALLENGE_LLM_BASE_URL")
            or settings.CHALLENGE_LLM_BASE_URL
        ).rstrip("/")

        api_key = (
            os.environ.get("PLATFORM_API_KEY")
            or os.environ.get("CHALLENGE_LLM_API_KEY")
            or settings.CHALLENGE_LLM_API_KEY
        )

        model = (
            os.environ.get("PLATFORM_LLM_MODEL")
            or os.environ.get("CHALLENGE_LLM_MODEL")
            or settings.CHALLENGE_LLM_MODEL
        )

        endpoint = base_url if base_url.endswith("/chat/completions") else f"{base_url}/chat/completions"

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are an expert scientific algorithm engineer. "
                        "You strictly output only Python 3.9 standard library code. "
                        "Do not use third-party libraries, do not make network calls, do not write log files or print statements. "
                        "You must define run_experiment(request) that conforms to the specification. "
                        "Output exactly one ```python ... ``` code block without any explanations or multiple code blocks."
                    )
                },
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.2,
            "stream": False,
        }

        work_dir = Path(work_dir)
        work_dir.mkdir(parents=True, exist_ok=True)
        response_file = work_dir / "generation-response.json"

        def _do_request(body_data: dict, req_timeout: int) -> dict:
            with httpx.Client(timeout=req_timeout) as client:
                resp = client.post(endpoint, json=body_data, headers=headers)
                resp.raise_for_status()
                return resp.json()

        # 首次调用
        data = _do_request(payload, timeout)
        response_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

        # 检查是否因长度限制截断
        choices = data.get("choices", [])
        if choices and choices[0].get("finish_reason") == "length":
            logger.warning("ReproductionHandler: Model output truncated (finish_reason=length). Retrying once...")
            retry_prompt = (
                prompt + "\n\n"
                "【重要修复提示】上一次生成的代码因长度超限被截断（finish_reason=length）。"
                "请务必精简代码，仅保留核心算法与必要逻辑，确保在单一 ```python ... ``` 代码块内完整闭合输出 def run_experiment(request):。"
            )
            payload["messages"] = [
                payload["messages"][0],
                {"role": "user", "content": retry_prompt}
            ]
            try:
                data = _do_request(payload, timeout)
                response_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception as e:
                logger.error(f"ReproductionHandler: Retry LLM call failed: {e}")

        return data

    def _save_implementation(self, response: dict, work_dir: Path) -> Path:
        """
        调用 app.core.model_source.save_source 将源码安全解析并保存至 work_dir / 'implementation.py'。
        若格式不合规或 finish_reason != 'stop' 则抛出 ValueError。
        """
        work_dir = Path(work_dir)
        work_dir.mkdir(parents=True, exist_ok=True)
        impl_path = work_dir / "implementation.py"
        source_sha256 = save_source(response, impl_path)
        logger.info(f"ReproductionHandler: Saved implementation to {impl_path} (sha256={source_sha256})")
        return impl_path

    def _find_official_runner(self) -> Optional[Path]:
        """定位官方 runner 脚本路径"""
        project_root = Path(__file__).resolve().parents[2]
        candidates = [
            Path("/data/experiments/run_experiment.py"),
            Path(settings.EXPERIMENTS_DIR) / "run_experiment.py",
            project_root / "research-experiments-v1" / "run_experiment.py",
            Path(os.getcwd()) / "research-experiments-v1" / "run_experiment.py",
        ]
        for cand in candidates:
            if cand.is_file():
                return cand
        return None

    def _invoke_official_runner(self, case_id: str, impl_path: Path, timeout: int = 90) -> Optional[dict]:
        """
        在注入环境变量后调用官方 run_experiment.py，解析 stdout 最终输出的 submission JSON。
        """
        runner_path = self._find_official_runner()
        if not runner_path:
            logger.error(f"ReproductionHandler: Official runner script not found for {case_id}")
            return None

        env = os.environ.copy()
        env["RESEARCH_EXPERIMENT_CASE"] = case_id
        env["RESEARCH_WORKSPACE_TEAM"] = self.team_name
        env["RESEARCH_RESULT_ROOT"] = self.file_writer.root
        env["RESEARCH_LAYERED_D"] = "layered-d-v3"
        env["RESEARCH_D_SOURCE_PROVENANCE"] = "d-model-source-v1"

        cmd = [sys.executable, str(runner_path), "--case", case_id, "--implementation", str(impl_path)]
        logger.info(f"ReproductionHandler: Invoking official runner: {' '.join(cmd)}")

        try:
            proc = subprocess.run(
                cmd,
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout
            )
            logger.info(f"ReproductionHandler: Runner exited with code {proc.returncode}")

            if proc.returncode != 0:
                logger.error(f"ReproductionHandler: Runner failed (code {proc.returncode}): {proc.stderr}")
                # 依然尝试检查是否有 submission 文件由 runner 写入磁盘
                disk_file = Path(self.file_writer.root) / "data" / self.team_name / f"{case_id}.json"
                if disk_file.is_file():
                    try:
                        return json.loads(disk_file.read_text(encoding="utf-8"))
                    except Exception:
                        pass
                return None

            # 解析 stdout 中的最后一项有效 JSON
            if proc.stdout:
                for line in reversed(proc.stdout.strip().splitlines()):
                    line = line.strip()
                    if line.startswith("{") and line.endswith("}"):
                        try:
                            data = json.loads(line)
                            if isinstance(data, dict) and "metrics" in data:
                                return data
                        except Exception:
                            pass

            # 若 stdout 未解析到，尝试从磁盘输出读取
            disk_file = Path(self.file_writer.root) / "data" / self.team_name / f"{case_id}.json"
            if disk_file.is_file():
                try:
                    return json.loads(disk_file.read_text(encoding="utf-8"))
                except Exception:
                    pass

            return None

        except subprocess.TimeoutExpired:
            logger.error(f"ReproductionHandler: Runner timeout ({timeout}s exceeded) for {case_id}")
            return None
        except Exception as e:
            logger.error(f"ReproductionHandler: Error invoking runner for {case_id}: {e}", exc_info=True)
            return None

    def _parse_submission_and_compute_errors(self, submission: dict, case_id: str) -> dict:
        """
        保留相对误差计算逻辑：当 reference!=0 且 observed!=None 时，
        计算 relative_error = abs(obs - ref) / abs(ref)，否则置为 None。
        """
        submission["case_id"] = case_id
        metrics = submission.get("metrics", [])
        if isinstance(metrics, list):
            for m in metrics:
                if not isinstance(m, dict):
                    continue
                ref = m.get("reference")
                obs = m.get("observed")
                if ref is not None and ref != 0 and obs is not None:
                    try:
                        m["relative_error"] = abs(float(obs) - float(ref)) / abs(float(ref))
                    except (ValueError, TypeError, ZeroDivisionError):
                        m["relative_error"] = None
                else:
                    m["relative_error"] = None

        return submission

    def _verify_and_sync_figures(
        self,
        case_id: str,
        submission: Dict[str, Any],
        work_dir: Path,
        is_online: bool = False
    ) -> bool:
        """
        核验 PNG 图表真实性：
        1. 存在性与路径安全性（禁止相对路径越界）；
        2. 8 字节 PNG 魔数头；
        3. PIL 完整性校验；
        4. 元数据(caption, x_label, y_label, legend)齐全性。
        """
        figures = submission.get("figures", [])
        if not isinstance(figures, list) or len(figures) == 0:
            if not is_online:
                logger.info(f"ReproductionHandler: Empty figures allowed for {case_id}")
                return True
            logger.warning(f"ReproductionHandler: No figures reported for {case_id}")
            return False

        work_dir_str = str(work_dir)
        for fig in figures:
            if not isinstance(fig, dict):
                return False

            for field in ("caption", "x_label", "y_label", "legend"):
                val = str(fig.get(field, "")).strip()
                if not val:
                    logger.error(f"ReproductionHandler: Figure field '{field}' is missing or empty in {case_id}")
                    return False

            rel_path = fig.get("path", "")
            if not rel_path or ".." in rel_path:
                logger.error(f"ReproductionHandler: Invalid figure path: {rel_path}")
                return False

            possible_source_paths = [
                os.path.join(work_dir_str, rel_path),
                os.path.join(self.file_writer.root, rel_path),
                os.path.join(work_dir_str, "data", "figure", self.team_name, f"{case_id}.png"),
                os.path.join(self.file_writer.root, "data", "figure", self.team_name, f"{case_id}.png"),
                os.path.join("/data/experiment-results", rel_path),
            ]

            actual_src = None
            for p in possible_source_paths:
                if os.path.isfile(p) and os.path.getsize(p) > 0:
                    actual_src = p
                    break

            if not actual_src:
                logger.error(f"ReproductionHandler: Figure file not found for {rel_path}")
                return False

            canonical_target = os.path.join(self.file_writer.root, rel_path)
            if os.path.abspath(actual_src) != os.path.abspath(canonical_target):
                os.makedirs(os.path.dirname(canonical_target), exist_ok=True)
                shutil.copyfile(actual_src, canonical_target)

            if not os.path.isfile(canonical_target) or os.path.getsize(canonical_target) == 0:
                logger.error(f"ReproductionHandler: Canonical figure target {canonical_target} missing or empty")
                return False

            # 1. 8 字节 PNG 魔数头校验
            try:
                with open(canonical_target, "rb") as f:
                    header = f.read(8)
                    if header != self.PNG_MAGIC_BYTES:
                        logger.error(f"ReproductionHandler: Figure {canonical_target} invalid magic: {header}")
                        return False
            except Exception as e:
                logger.error(f"ReproductionHandler: Error checking PNG magic bytes: {e}")
                return False

            # 2. PIL 图像校验
            try:
                from PIL import Image
                with Image.open(canonical_target) as img:
                    img.verify()
            except Exception as e:
                logger.error(f"ReproductionHandler: PIL verification failed for {canonical_target}: {e}")
                return False

        return True

    def _fallback(self, case_id: str, status: str = "failed") -> Dict[str, Any]:
        """
        合规优雅降级输出：
        三项指标 name/unit 优先对齐 protocol，数值置为 None，figures 置为空，拒绝捏造假数据，
        落盘写入产物目录并回读核验。
        """
        logger.warning(f"ReproductionHandler: Fallback triggered for {case_id} with status '{status}'")

        metric_items = []
        materials = self._read_experiment_materials(case_id)
        if "protocol" in materials:
            try:
                proto_data = json.loads(materials["protocol"])
                metrics_spec = proto_data.get("metrics", [])
                if isinstance(metrics_spec, list) and len(metrics_spec) == 3:
                    for item in metrics_spec:
                        metric_items.append({
                            "name": item.get("name", "Metric"),
                            "unit": item.get("unit", "unit"),
                            "reference": None,
                            "observed": None,
                            "relative_error": None
                        })
            except Exception:
                pass

        if not metric_items:
            specs = self.METRIC_SPECS.get(case_id)
            if specs:
                default_names = ["Macro-F1", "Accuracy", "运行时间"]
                for idx, spec in enumerate(specs):
                    name = None
                    unit = "unit"
                    ref = None

                    if isinstance(spec, (list, tuple)):
                        if len(spec) >= 3:
                            name = str(spec[0])
                            unit = str(spec[1])
                            ref = float(spec[2]) if spec[2] is not None else None
                        elif len(spec) == 2:
                            if isinstance(spec[0], (int, float)):
                                ref = float(spec[0])
                                unit = str(spec[1])
                                name = default_names[idx] if idx < len(default_names) else f"Metric_{idx+1}"
                            else:
                                name = str(spec[0])
                                unit = str(spec[1])
                                ref = None
                        elif len(spec) == 1:
                            name = str(spec[0])
                            unit = "unit"
                            ref = None
                    elif isinstance(spec, dict):
                        name = spec.get("name")
                        unit = spec.get("unit", "unit")
                        ref = spec.get("reference")

                    if not name:
                        name = f"Metric_{idx+1}"

                    metric_items.append({
                        "name": name,
                        "unit": unit,
                        "reference": ref,
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

        rel_json_path = f"data/{self.team_name}/{case_id}.json"
        try:
            self.file_writer.write_json_and_verify(rel_json_path, fallback_result)
        except Exception as e:
            logger.error(f"ReproductionHandler: Failed to write fallback result to disk: {e}")

        return fallback_result

    def handle(self, task: ChallengeTaskInput, session_id: str) -> Dict[str, Any]:
        """
        D 类复现任务主执行链路，在 180s 任务超时熔断预算内严格受控调度。
        """
        case_id = task.case_id.strip()
        logger.info(f"ReproductionHandler: Starting reproduction task for {case_id}")

        guard = TaskTimeoutGuard(case_id=case_id, timeout_seconds=175)
        try:
            with guard:
                # 1. 材料源读取
                materials = self._read_experiment_materials(case_id)
                if not materials:
                    logger.error(f"ReproductionHandler: Materials missing for {case_id}")
                    return self._fallback(case_id, status="materials_missing")

                # 2. 构造代码生成提示词
                prompt = self._build_generation_prompt(case_id, materials, task_input=task.input)

                work_dir = Path(self.file_writer.root) / f"data/{self.team_name}/work/{case_id}"
                work_dir.mkdir(parents=True, exist_ok=True)

                # 3. Gateway 请求模型生成代码（时限 60s）
                try:
                    response_json = self._call_platform_llm(prompt, work_dir=work_dir, timeout=60)
                except Exception as e:
                    logger.error(f"ReproductionHandler: LLM code generation failed for {case_id}: {e}")
                    return self._fallback(case_id, status="failed")

                # 4. 提取源码并落盘保存
                try:
                    impl_path = self._save_implementation(response_json, work_dir=work_dir)
                except Exception as e:
                    logger.error(f"ReproductionHandler: Failed to extract/save implementation for {case_id}: {e}")
                    return self._fallback(case_id, status="failed")

                # 5. 调用官方 runner 执行（时限 90s）
                submission = self._invoke_official_runner(case_id, impl_path=impl_path, timeout=90)
                if not submission:
                    logger.error(f"ReproductionHandler: Official runner failed or returned empty for {case_id}")
                    return self._fallback(case_id, status="failed")

                # 6. 计算相对误差 relative_error
                submission = self._parse_submission_and_compute_errors(submission, case_id)

                # 7. 核验 PNG 图表真实性
                is_online = Path("/data/experiments/run_experiment.py").is_file()
                if not self._verify_and_sync_figures(case_id, submission, work_dir=work_dir, is_online=is_online):
                    logger.error(f"ReproductionHandler: Figure verification failed for {case_id}")
                    return self._fallback(case_id, status="failed")

                # 8. Pydantic 模型合规校验
                validated = ReproductionOutput.model_validate(submission)
                final_result = validated.model_dump()

                # 9. 双写落盘至队伍产物目录并回读核验
                rel_json_path = f"data/{self.team_name}/{case_id}.json"
                self.file_writer.write_json_and_verify(rel_json_path, final_result)
                logger.info(f"ReproductionHandler: Successfully completed reproduction for {case_id}")
                return final_result

        except TaskTimeoutException:
            logger.error(f"ReproductionHandler: Task execution timed out (175s guard exceeded) for {case_id}")
            return self._fallback(case_id, status="failed")
        except Exception as e:
            logger.error(f"ReproductionHandler: Unexpected error for {case_id}: {e}", exc_info=True)
            return self._fallback(case_id, status="failed")
