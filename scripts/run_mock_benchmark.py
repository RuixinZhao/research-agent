#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
科研助手 Agent 本地 25 题全链路自动化压测套件 (run_mock_benchmark.py)

功能与使命：
1. 搭建仿真大赛环境，构造 A/B/C/D/E 全类别 25 道真实科研测试用例；
2. 自动生成标准 data/<team>/dispatch.json 与 data/<team>/assigned/*.json 题目；
3. 内置高并发无依赖 Mock LLM Gateway（监听 127.0.0.1:8000/v1），保障纯离线压测 100% 零外网阻断；
4. 支持自动拉起 / 托管 server.py 服务容器与探活健康检查；
5. 并发 / 串行高压测试 25 题，精确度量每道用例的耗时、状态码与返回结果；
6. 压测完成后无缝串联 scripts/validate_submission.py，执行 100% 交付物全量预检。
"""

from __future__ import annotations

import argparse
import http.server
import json
import logging
import os
import signal
import socket
import socketserver
import sys
from pathlib import Path

# 确保项目根目录与 scripts 目录在 sys.path 中
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import subprocess
import threading
import time
from typing import Any, Dict, List, Optional
import httpx

from validate_submission import SubmissionValidator

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("MockBenchmark")


class MockLLMHandler(http.server.BaseHTTPRequestHandler):
    """
    轻量级仿真 OpenAI-compatible LLM Gateway。
    专为科研助手离线压测定制，根据任务特征精准生成学术级返回。
    """

    def log_message(self, format: str, *args: Any) -> None:
        # 静默标准 HTTP 请求日志，避免刷屏
        pass

    def do_POST(self) -> None:
        if not self.path.startswith("/v1/chat/completions"):
            self.send_response(404)
            self.end_headers()
            return

        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode("utf-8")
        try:
            req_data = json.loads(body)
        except Exception:
            req_data = {}

        messages = req_data.get("messages", [])
        prompt_text = " ".join([m.get("content", "") for m in messages])

        # 智能辨识任务类型：Chat / Survey / Idea
        if '"answer"' in prompt_text or "限定追问" in prompt_text:
            # A 类 Chat 响应
            reply_content = json.dumps({
                "answer": (
                    "在科研场景的理论机理探究中，核心变量间的非线性耦合与动态响应特性是制约模型收敛与泛化性能的关键瓶颈。"
                    "针对此问题，需在明确形式化定义的基础上，剖析参数敏感性与特征流形分布，"
                    "通过设置基线对照组与消融实验，验证底层因果机制与统计显著性，确保在各种边界扰动下仍具备鲁棒的表现。"
                ),
                "clarifying_question": "请问本研究所拟采用的核心基准数据集规模是什么，以及对比实验中关键自变量的离散取值与控制边界如何限定？"
            }, ensure_ascii=False)
        elif "## 参考文献" in prompt_text or "综述研究主题" in prompt_text:
            # C 类 Survey 响应 (保证 >= 800 字符且含标准引文锚点)
            reply_content = """# 前沿科研学术深度综合综述报告

## 一、研究背景与核心问题综述
在大规模人工智能系统与自动化科学计算的演进过程中，多源异构知识的表示学习与端到端协同推理逐渐成为突破认知瓶颈的核心路径。传统方法在面对长文本上下文表征稀疏、语义关联漂移等复杂场景时，常因归纳偏置受限而无法建立稳定的跨尺度映射关系[1, p.1]。近期研究通过引入深层语义注意力对齐与拓扑结构正则化约束，显著改善了知识交互的表征保真度[2, p.2]。然而在物理计算资源与内存带宽严格受限的边缘计算环境中，如何在降低显存峰值占用的同时维持高保真推断能力，仍是当前学术界与工业界亟待解决的关键难题[1, p.3]。

## 二、代表性技术路线与方法机制对比分析
围绕上述挑战，学术界主要发展出两条互补的技术演进路线。第一类路线以基于结构化稀疏表征与自适应分块机制为代表，其核心机理在于通过局部上下文敏感度自适应动态切分知识流，从而大幅压缩冗余投影维度[2, p.3]。该路线优势在于工程实现具备高确定性吞吐，但在长跨度依赖捕获上存在局部特征截断风险。第二类路线则聚焦于多智能体动态对齐与细粒度反馈驱动的迭代优化范式[3, p.2]。此类方法通过显式建模证据链拓扑图结构，实现了细粒度语义片段的动态置信度标定与误差溯源[3, p.4]。对比分析表明，两类技术路线在计算吞吐量、内存 footprint 与鲁棒性边界上呈现出鲜明的互补权衡特性。

## 三、实验基准、数据集与量化性能深度评估
在标准科学文献评测基准与多模态下游任务的实验评估中，上述方法展现出不同的收敛轨迹。基线评测表明，采用稀疏压缩表征的模型在低延迟指标上提升明显，能够实现约 2.4 倍的吞吐加速[1, p.4]；而引入细粒度证据校验的智能体架构则在抗幻觉准确率上取得了显著优势，相较传统基线降低了约 37.5% 的错误归因率[2, p.4]。然而实验数据同时揭示，当输入噪声比例超过特定临界阈值时，两类方法均会出现性能阶跃式衰减，这证实了现有评估基准对边界极端工况的度量仍显不足。

## 四、现有方案局限性与跨路线互补性探讨
尽管现有方案在特定任务下取得了突出表现，但深入剖析其底层假设可发现若干共同局限性。首先，对于无标注长程依赖的动态捕获机制过度依赖静态预训练先验，缺乏在线元学习自适应调整能力[3, p.5]。其次，计算复杂度的渐近上界与硬件底层通信瓶颈之间的矛盾依然突出。因此，将结构化稀疏轻量检索与多智能体动态反思仲裁机制进行深层次融合，是构建下一代鲁棒科学计算底座的重要突破口。

## 五、未来发展演进路径与总结
面向未来，科学研究助手与端到端知识发现系统的演进应更加注重理论可解释性与跨模态物理约束对齐。通过在数学形式上统一特征空间投影，并建立多维度的综合性能基准，方能在兼顾低资源硬件约束的前提下，实现真正意义上的高阶自主认知推理。

## 参考文献
[1] Late Chunking Team. Late Chunking: Contextual Chunk Embeddings. 文件名: Late_Chunking_Contextual_Chunk_Embeddings.pdf
[2] PaperQA Team. PaperQA2: Language Agents Achieve Superhuman Scientific Synthesis. 文件名: PaperQA2_Language_Agents_Superhuman_Scientific_Synthesis.pdf
[3] RefChecker Team. RefChecker: Fine-grained Hallucination Checker. 文件名: RefChecker_Fine_grained_Hallucination_Checker.pdf
"""
        else:
            # E 类 Idea 响应 (保证 >= 800 字符且包含 8 大标准二级标题)
            reply_content = """# 自适应长上下文细粒度科研归因与协同创新方案

## 1. 研究动机与问题背景
在面对海量科研文献与复杂知识推理任务时，现有检索增强生成架构常受制于上下文窗口截断与检索相关性衰减。当引入高并发检索机制时，传统块切分容易破坏长程语义连贯性，导致下游推理阶段出现关键前提缺失与事实幻觉[1, p.1]。特别是在低资源计算设备与紧凑内存约束下，如何在保证毫秒级检索延迟的同时，最大化上下文表征的深层语义保真度，构成了当前学术界面临的根本挑战。

## 2. 核心技术路线与架构设计
本方案提出一种“两阶段自适应粗精结合”的端到端语义对齐框架。第一阶段采用动态轻量化稀疏分块算子，对输入文本流进行上下文感知的分级锚定，保留跨段落概念拓扑；第二阶段设计基于强化置信度感知的细粒度引文匹配网络，对提取的关键语义单元进行多维度交互重排，并结合跨注意力机制对潜在冲突证据进行显式仲裁与一致性过滤。

## 3. 实验设计与评估基准
评测将构建在公开权威学术基准（如 SCIVER、FActScore 与最新科研长文本评测集）之上。基线模型选取业内主流的 Dense Retrieval、BM25S 稀疏检索器以及经典双塔多层感知架构。实验采用标准严格的五折交叉验证协议，确保所有超参数调优过程与最终测试集严格正交隔离，杜绝数据泄露。

## 4. 定量评价指标与度量规范
评估涵盖三维综合度量体系：
1. 检索与归因精度：采用精确率 P@5、召回率 R@10 以及基于字符级跨度的归因覆盖度（Attribution Precision）；
2. 语义忠实度：利用细粒度二元事实一致性判别器（Factuality Score），量化抑制未经证实陈述的有效性；
3. 系统吞吐效率：统计单次推理端到端 P95 延迟（ms）及单卡并发处理吞吐（queries/s）。

## 5. 复现瓶颈与实现困难反思
在实际系统落地与复现探索中，主要存在两大潜在瓶颈：一是跨文档长程共指消解与代词歧义的消除难度较大，容易在多跳推理阶段引入级联误差；二是动态交互注意力计算量随上下文长度呈二次方增长，在只有 1024 MiB 内存配额的单机容器中极易触发内存溢出（OOM）。为此必须严格实施流式梯度投影与算子显存复用技术。

## 6. 多篇文献的方法互补性论证
本方案融合了多项前沿代表性研究的精髓[1, p.2]。文献[1]证明了保持上下文全局依赖对抑制语义断层至关重要，而文献[2]则在轻量化倒排索引和常数内存检索方面提供了严谨的工程范式。将两者在特征投影空间显式耦合，既继承了前者的全局语义捕获能力，又吸纳了后者的极致计算效率，形成结构上的闭环互补。

## 7. 真实场景可行性与工程约束
针对大赛与工业界严苛的单容器 1024 MiB 内存及 150 秒硬超时限制，全套系统采用纯单进程异步非阻塞 I/O 架构。所有中间张量计算均锁定在固定缓冲池内，执行即时垃圾回收（GC），确保常驻内存常年维持在 80MB 以下。整个推理流水线具备完全的离线独立运行能力，零外部网络服务依赖。

## 8. 模拟观察与实测结论边界声明
【重要边界声明】：题目中所给出的特定样例现象与初步模拟观察，仅作为启发本技术方案动机的待分析初始线索，严禁将其视为已经过严谨同行评议或已完成大规模实测的既定科学结论。本报告所提出的技术指标预期、性能优势分析及潜在改进幅度，均属于待在后续标准化实验基准中进行对照验证的科学设想与推论。

## 参考文献
[1] Late Chunking Team. Late Chunking: Contextual Chunk Embeddings. 文件名: Late_Chunking_Contextual_Chunk_Embeddings.pdf
[2] BM25S Team. BM25S: Eager Sparse Scoring Lexical Search. 文件名: BM25S_Eager_Sparse_Scoring_Lexical_Search.pdf
"""

        response_body = json.dumps({
            "id": f"mock-chatcmpl-{int(time.time()*1000)}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": req_data.get("model", "mock-model"),
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": reply_content},
                "finish_reason": "stop"
            }],
            "usage": {
                "prompt_tokens": 128,
                "completion_tokens": len(reply_content),
                "total_tokens": 128 + len(reply_content)
            }
        }, ensure_ascii=False).encode("utf-8")

        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(response_body)))
        self.end_headers()
        self.wfile.write(response_body)


class MockLLMServer:
    """Mock LLM Gateway 后台服务管理器"""

    def __init__(self, host: str = "127.0.0.1", port: int = 8000):
        self.host = host
        self.port = port
        self.server: Optional[socketserver.TCPServer] = None
        self.thread: Optional[threading.Thread] = None

    def start(self) -> bool:
        # 探测端口是否已被外部服务占用
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            if s.connect_ex((self.host, self.port)) == 0:
                logger.info(f"LLM 端口 {self.host}:{self.port} 已存在活动服务，复用现有 Gateway。")
                return False

        class ReusableTCPServer(socketserver.TCPServer):
            allow_reuse_address = True

        self.server = ReusableTCPServer((self.host, self.port), MockLLMHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        logger.info(f"✨ 仿真 Mock LLM Gateway 已启动，监听 http://{self.host}:{self.port}/v1")
        return True

    def stop(self) -> None:
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            logger.info("Mock LLM Gateway 已平稳停止。")


class MockBenchmarkRunner:
    """25 题全集压测执行调度引擎"""

    def __init__(self, base_url: str = "http://127.0.0.1:8080", team_name: str = "team", auto_start: bool = True):
        self.base_url = base_url.rstrip("/")
        self.team_name = team_name
        self.auto_start = auto_start
        self.server_process: Optional[subprocess.Popen] = None
        self.llm_server: Optional[MockLLMServer] = None
        self.client = httpx.Client(timeout=180.0)

    def _setup_mock_dispatch_environment(self) -> List[Dict[str, Any]]:
        """初始化 25 题派题数据与磁盘目录"""
        cases: List[Dict[str, Any]] = []

        func_map = {
            "A": "Chat",
            "B": "Literature_Retrieval",
            "C": "Survey",
            "D": "Reproduction",
            "E": "Idea",
        }

        # 真实存在的本地论文材料候选池
        pdf_candidates = [
            "Late_Chunking_Contextual_Chunk_Embeddings.pdf",
            "PaperQA2_Language_Agents_Superhuman_Scientific_Synthesis.pdf",
            "RefChecker_Fine_grained_Hallucination_Checker.pdf",
            "ALiiCE_NAACL2025_Positional_Fine_grained_Citation_Generation.pdf",
            "BM25S_Eager_Sparse_Scoring_Lexical_Search.pdf",
        ]

        for cat in ("A", "B", "C", "D", "E"):
            f_name = func_map[cat]
            for idx in range(1, 6):
                case_id = f"{cat}-{idx:02d}"

                if cat == "A":
                    title = f"科研学术深度对话-{case_id}"
                    input_text = f"请针对课题「基于深度强化学习的机器人轨迹控制 #{idx}」进行专业解答，并提出一个最关键的研究范围限定追问。"
                    materials = []
                    constraints = ["提出且仅提出一个最关键的范围限定追问"]
                elif cat == "B":
                    title = f"核心文献检索与去重-{case_id}"
                    input_text = f"检索关于学术问答合成、大模型幻觉抑制与细粒度引文归因方向的核心学术文献 #{idx}。"
                    materials = pdf_candidates
                    constraints = ["严防无关论文误报", "仅返回本地实际存在的完整 PDF 文件名"]
                elif cat == "C":
                    title = f"前沿综述调研与物理页码引文-{case_id}"
                    input_text = f"结合指定论文，对多智能体科研助手与上下文分块表征展开横向学术综述调研 #{idx}。"
                    materials = pdf_candidates[:3]
                    constraints = ["正文字符数>=800", "页码严格与物理真实页码对齐", "包含## 参考文献章节"]
                elif cat == "D":
                    title = f"论文算法真实复现实验-{case_id}"
                    input_text = f"真实执行 D 系列标准化离线实验流水线 #{idx}，度量三项量化指标并生成可视化图表。"
                    materials = [f"D-{idx:02d}.json"]
                    constraints = ["禁止伪造 observed 指标", "图表包含完整标注信息"]
                elif cat == "E":
                    title = f"创新科研设想与8大槽位对齐-{case_id}"
                    input_text = f"阅读检索增强与细粒度归因论文，提出下一代抗幻觉自适应生成方案 #{idx}。模拟观察表明单句引用准确率较低，但未测试段落级长上下文融合。"
                    materials = pdf_candidates[:2]
                    constraints = ["只把题目给出的模拟观察作为待分析现象，不得写成论文实测结论", "正文字符数>=800", "覆盖8大二级标题"]

                cases.append({
                    "case_id": case_id,
                    "function": f_name,
                    "title": title,
                    "input": input_text,
                    "materials": materials,
                    "constraints": constraints,
                    "expected_output": f"合规 {f_name} 输出格式",
                    "output_schema_ref": f_name
                })

        # 写入 dispatch.json 与 assigned/*.json
        dispatch_dir = Path("data") / self.team_name
        assigned_dir = dispatch_dir / "assigned"
        assigned_dir.mkdir(parents=True, exist_ok=True)

        dispatch_content = {
            "dispatch_id": f"dispatch-mock-{int(time.time())}",
            "team": self.team_name,
            "schema_version": 2,
            "cases_per_category": 5,
            "rules_version": "research-assistant-objective-v2",
            "case_ids": [c["case_id"] for c in cases],
            "cases": [
                {
                    "case_id": c["case_id"],
                    "function": c["function"],
                    "title": c["title"],
                    "question_file": f"data/{self.team_name}/assigned/{c['case_id']}.json",
                    "question_sha256": "mock_sha256_placeholder"
                }
                for c in cases
            ]
        }

        with open(dispatch_dir / "dispatch.json", "w", encoding="utf-8") as f:
            json.dump(dispatch_content, f, ensure_ascii=False, indent=2)

        for c in cases:
            with open(assigned_dir / f"{c['case_id']}.json", "w", encoding="utf-8") as f:
                json.dump(c, f, ensure_ascii=False, indent=2)

        logger.info(f"✨ 25 题派题清单与题目文件已初始化就绪: {dispatch_dir / 'dispatch.json'}")
        return cases

    def _ensure_services_ready(self) -> None:
        """检查并确保 LLM Gateway 与 Agent Server 处于就绪状态"""
        # 1. 启动仿真 LLM Gateway
        self.llm_server = MockLLMServer(host="127.0.0.1", port=8000)
        self.llm_server.start()

        # 2. 检查 Agent Server 探活
        server_ready = False
        try:
            r = self.client.get(f"{self.base_url}/health", timeout=2.0)
            if r.status_code == 200:
                server_ready = True
                logger.info(f"Agent Server 已在运行中: {self.base_url}")
        except Exception:
            server_ready = False

        if not server_ready and self.auto_start:
            logger.info("未探测到现有 Agent Server，正在以子进程自动拉起 server.py...")
            env = os.environ.copy()
            env["RESEARCH_WORKSPACE_TEAM"] = self.team_name
            env["CHALLENGE_LLM_BASE_URL"] = "http://127.0.0.1:8000/v1"
            self.server_process = subprocess.Popen(
                [sys.executable, "server.py"],
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )

            # 等待探活成功，最多轮询 15 秒
            for _ in range(30):
                time.sleep(0.5)
                try:
                    r = self.client.get(f"{self.base_url}/health", timeout=1.0)
                    if r.status_code == 200:
                        server_ready = True
                        logger.info("🚀 Agent Server 启动就绪并通过 /health 健康检查！")
                        break
                except Exception:
                    pass

        if not server_ready:
            raise RuntimeError(f"无法连通 Agent Server ({self.base_url})，请检查服务是否已正确启动。")

    def run_benchmark(self) -> bool:
        """执行 25 题全链路压测与耗时度量"""
        cases = self._setup_mock_dispatch_environment()
        self._ensure_services_ready()

        print("\n" + "=" * 76)
        print("⚡️ 科研助手 Agent 25 题全集高保真本地并发/串行全量压测开始")
        print(f"🎯 目标网关: {self.base_url}/solve | 队伍标识: {self.team_name}")
        print("=" * 76)

        results: List[Dict[str, Any]] = []
        t_start_all = time.perf_counter()

        for idx, case in enumerate(cases, start=1):
            cid = case["case_id"]
            fn = case["function"]
            t0 = time.perf_counter()
            error_msg = ""
            status_code = 0
            resp_keys = []

            try:
                resp = self.client.post(
                    f"{self.base_url}/solve",
                    json=case,
                    headers={"X-Session-ID": f"bench_sess_{cid}"}
                )
                elapsed = time.perf_counter() - t0
                status_code = resp.status_code

                if resp.status_code == 200:
                    data = resp.json()
                    resp_keys = list(data.keys())
                    success = (data.get("case_id") == cid)
                else:
                    success = False
                    error_msg = f"HTTP {resp.status_code}: {resp.text[:80]}"
            except Exception as e:
                elapsed = time.perf_counter() - t0
                success = False
                error_msg = str(e)[:80]

            results.append({
                "index": idx,
                "case_id": cid,
                "function": fn,
                "success": success,
                "latency": elapsed,
                "status_code": status_code,
                "error": error_msg,
                "keys": resp_keys
            })

            symbol = "✅ PASS" if success else "❌ FAIL"
            print(f"[{idx:02d}/25] {symbol} | {cid:<5} | {fn:<20} | 耗时: {elapsed:5.2f}s | 字段: {resp_keys}")
            if error_msg:
                print(f"        └─ 错误详情: {error_msg}")

        t_total = time.perf_counter() - t_start_all

        # 统计汇总
        pass_count = sum(1 for r in results if r["success"])
        fail_count = len(results) - pass_count
        latencies = [r["latency"] for r in results]
        avg_latency = sum(latencies) / len(latencies) if latencies else 0.0

        print("\n" + "=" * 76)
        print("📈 25 题全链路压测性能度量看板 (Benchmark Metrics Summary)")
        print(f"用例执行总数: {len(results)}")
        print(f"执行成功率  : {pass_count}/{len(results)} ({pass_count/len(results):.1%})")
        print(f"平均单题耗时: {avg_latency:.2f}s")
        print(f"最长单题耗时: {max(latencies):.2f}s (P99)")
        print(f"最短单题耗时: {min(latencies):.2f}s")
        print(f"全集总测试用时: {t_total:.2f}s")
        print("=" * 76)

        # 类别维度细化耗时
        for cat in ("A", "B", "C", "D", "E"):
            cat_items = [r for r in results if r["case_id"].startswith(cat)]
            cat_pass = sum(1 for r in cat_items if r["success"])
            cat_avg = sum(r["latency"] for r in cat_items) / len(cat_items) if cat_items else 0
            print(f"类别 [{cat}] ({len(cat_items)} 题): 通过率 {cat_pass}/{len(cat_items)} | 平均耗时: {cat_avg:.2f}s")

        print("=" * 76 + "\n")

        # 压测后即刻串联终审合规预检
        logger.info("🔗 正在执行交付成果规范性验证流水线 (validate_submission)...")
        validator = SubmissionValidator(team_name=self.team_name, verbose=False)
        val_success = validator.run()

        overall_ok = (pass_count == len(results)) and val_success
        return overall_ok

    def cleanup(self) -> None:
        if self.server_process:
            logger.info("正在清理 Agent Server 子进程...")
            self.server_process.terminate()
            try:
                self.server_process.wait(timeout=3.0)
            except subprocess.TimeoutExpired:
                self.server_process.kill()
            self.server_process = None

        if self.llm_server:
            self.llm_server.stop()
            self.llm_server = None


def main() -> int:
    parser = argparse.ArgumentParser(description="科研助手 Agent 25 题全集压测套件")
    parser.add_argument("--url", default="http://127.0.0.1:8080", help="Agent 服务入口 URL")
    parser.add_argument("--team", default=None, help="参赛队伍名称")
    parser.add_argument("--no-auto-start", action="store_true", help="不自动拉起 server.py")
    args = parser.parse_args()

    team = args.team or os.environ.get("RESEARCH_WORKSPACE_TEAM", "team")
    runner = MockBenchmarkRunner(
        base_url=args.url,
        team_name=team,
        auto_start=not args.no_auto_start
    )

    try:
        ok = runner.run_benchmark()
        return 0 if ok else 1
    finally:
        runner.cleanup()


if __name__ == "__main__":
    sys.exit(main())
