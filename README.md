# 2026 全国高校 Agent 网络创新挑战赛 · 赛题 1「科研助手」

本项目是参加 **2026 CCF 网络大会 · 第一届全国高校 Agent 网络创新挑战赛 · 赛题 1「科研助手」** 的参赛智能体工程仓库。

---

## 核心文档索引与平台最新规范同步

1. **[赛题输入输出格式规范 (research-agent-spec.md)](./research-agent-spec.md)**  
   与赛事平台 (`http://aiagent-anic.com/challenges/challenge-tbd`) 实时同步的最新规范：
   - 派题模式为 **1-3-2-3-2 案例版**（共 11 题：A 随机 1 题、B 固定 3 题、C 固定 2 题、D 固定 3 题、E 固定 2 题）；
   - 正式派题配置为 `rules_version: "research-assistant-objective-v3"` 与 `schema_version: 3`；
   - 严格执行 **`c1-output-limits-v1`** 篇幅红线：C 类综述正文 $\le 5000$ 字符（引用标记 $\le 40$ 次），E 类 Idea 正文 $\le 4500$ 字符；
   - 云端运行时限更新：A/B 类每题 540s，C/D/E 类每题 900s。
2. **[参赛者赛题说明文档 (research-description.md)](./research-description.md)**  
   说明科研助手 Agent 的五大题型、输入输出协议、论文证据要求、复现提交规则与安全边界。
3. **[客观评分规则与打榜说明 (research-scoring-rules.md)](./research-scoring-rules.md)**  
   7 项客观打榜指标（Chat 5 分、检索 15 分、综述事实 15 分、引文溯源 10 分、要点覆盖 15 分、实验流水线 20 分、数据与图表 20 分，满分 100 分）。
4. **[D 类官方实验材料与准入规范 (research-experiments-20261020-source-v1-local/)](./research-experiments-20261020-source-v1-local/)**  
   包含最新 `layered-d-v3` 协议与 `d-model-source-v1` 来源准入标准，通过赛事 Gateway 动态生成 Python 3.9 算法并调起官方 runner。
5. **[科研助手 Agent 产品开发与工程落地手册](./科研助手Agent产品开发与工程落地手册.md)**  
   包含完整的分层架构设计、官方基础镜像（`agenthack-base:1.1.1`）配置、FastAPI 接口契约、PyMuPDF 流式解析、SQLite FTS5 离线检索、五大题型处理器实现、防幻觉与双写核验机制。
6. **[全面技术调研与前沿顶会论文技术报告](./科研助手Agent技术调研与方案全景报告.md)**  
   涵盖 PaperQA2、RefChecker、FActScore、ALiiCE、Late Chunking、Lost in the Middle 等 11 篇顶会论文（2024–2026）深度剖析与开源仓库实践。

---

## 目录结构

```text
.
├── app/                                   # 核心应用源码 (FastAPI + 各类 Handlers + Core 模块)
├── server.py                              # 服务端入口 (GET /health, POST /solve)
├── model_source.py                        # 官方准入来源提取与 Python 3.9 AST 校验工具
├── research-agent-spec.md                 # 赛题输入输出格式规范 (最新 11 题版)
├── research-description.md                # 参赛者说明文档 (最新 11 题版)
├── research-scoring-rules.md              # 评分规则与打榜流程 (最新版)
├── research-experiments-20261020-source-v1-local/ # D 类最新 layered-d-v3 与 d-model-source-v1 材料
├── scripts/
│   ├── validate_submission.py             # 交付成果自动化合规预检流水线 (支持 11 题与 25 题)
│   └── run_live_llm.py                    # 真实大模型调用评测脚本
├── tests/                                 # 75+ 项全量自动化回归测试集
├── Dockerfile                             # 官方基础镜像构建文件 (AMD64, 非 root, <220MB)
└── downloaded_papers/                     # 核心参考文献库 (PDF)
```

---

## 快速自测与交付验证

### 1. 本地单元测试回归
```bash
PYTHONPATH=. pytest tests/ -v
# 75 项测试全量 PASS
```

### 2. 交付物自动化合规预检 (Pre-flight Validation)
```bash
python3 scripts/validate_submission.py team
# 核验 11 题 / 25 题产物结构、UTF-8 编码、C/E 篇幅与引用限制、D 类图表魔数签名
```

### 3. Docker 镜像构建与冒烟测试
```bash
# 构建生产镜像 (amd64)
docker build --platform linux/amd64 -t research-agent:latest .

# 启动容器并测试 /health
docker run -d --name smoke_test -p 8080:8080 -e TEAM_ID=eval_team_test research-agent:latest
curl http://127.0.0.1:8080/health
# 返回: {"status":"healthy","telemetry_configured":true}
```

---

## 🚀 AGY-Research Studio · 科研助手多智能体具象化控制台

系统内置了现代化高科技深色质感前端具象化控制台（基于 FastAPI + TailwindCSS + Lucide + Marked.js + Chart.js 单页应用），用于全方位、具象化直观体现科研 Agent 的中枢思考、架构拓扑、证据链溯源与多模态成果：

### 启动方式
```bash
python server.py
```
启动后在浏览器打开：
👉 **`http://localhost:8080/`**

### 控制台具象化核心板块：
1. **🌐 Agent 架构全景拓扑 (Architecture Topology)**：五大专项 Agent（Chat, Retrieval, Survey, Reproduction, Idea）与底层安全基础设施（SQLite FTS5、PyMuPDF、PaperQA2 证据链、RefChecker 双重审计、150s 熔断保护）动态交互拓扑与时序流。
2. **⚡ 任务推演与交互工作台 (Task Playground)**：支持一键加载 25 道基准赛题或自定义输入题目，动态展示 5 大阶段时序流动效（题目解析 ➔ 物理页检索 ➔ 学术推理/复现 ➔ 事实审计 ➔ 双写核验）。
3. **📑 多模态成果阅览器 (Artifact Viewer)**：
   - **C类/E类成果**：Markdown 深度排版、实时字数统计徽章（$\ge 800$ 字）、**可交互物理页码引文徽章**（点击即可弹出真实物理页证据溯源浮层）、8 大核心二级标题覆盖率雷达、模拟观察待验证证据隔离区警示框；
   - **D类复现成果**：真实生成的 PNG 实验曲线图（魔数绿标 `89 50 4E 47` 验真）、Observed vs Reference 指标对比卡片与误差分析；
   - **A类学术对话**：学术机理解析卡片 + 变量范围限定澄清追问；
   - **B类排他检索**：命中文献列表 + 排他规则拦截日志。
4. **🏆 100分基准评测大盘 (Benchmark 100 Pts Radar)**：100 分总分看板（D类40分、C类25分、B类15分、E类15分、A类5分）、5x5 矩阵全景卡片、内置一键触发自动化预检流水线（`validate_submission.py` 100% PASS 徽章）。
5. **📚 文献资产库 (Paper Explorer)**：直观浏览 11 篇顶会论文元数据与物理页切片分布。

