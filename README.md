# 2026 全国高校 Agent 网络创新挑战赛 · 赛题 1「科研助手」

本项目是参加 **2026 CCF 网络大会 · 第一届全国高校 Agent 网络创新挑战赛 · 赛题 1「科研助手」** 的参赛智能体工程仓库。

---

## 核心文档索引

1. **[科研助手 Agent 产品开发与工程落地手册](./科研助手Agent产品开发与工程落地手册.md)**  
   包含完整的分层架构设计、官方基础镜像（`agenthack-base:1.1.1`）配置、FastAPI 接口契约、PyMuPDF 流式解析、SQLite FTS5 离线检索、五大题型处理器实现、防幻觉与回读校验机制。
2. **[全面技术调研与前沿顶会论文技术报告](./科研助手Agent技术调研与方案全景报告.md)**  
   涵盖 PaperQA2、RefChecker、FActScore、ALiiCE、Late Chunking、Lost in the Middle 等 11 篇顶会论文（2024–2026）深度剖析与开源仓库实践。
3. **[赛题技术规格与评测标准文档](./research-agent-spec.md)**  
   官方 v2 输入输出协议、评测接口与运行规则。
4. **[客观评分规则与打榜说明](./research-scoring-rules.md)**  
   7 项客观打榜指标（Chat 5 分、检索 15 分、综述事实 15 分、引文溯源 10 分、要点覆盖 15 分、实验流水线 20 分、数据与图表 20 分）。

---

## 目录结构

```text
.
├── 科研助手Agent产品开发与工程落地手册.md   # 系统架构与实现手册
├── 科研助手Agent技术调研与方案全景报告.md   # 顶会调研与开源技术库
├── project-outline.md                     # 早期方案大纲与调研清单
├── research-agent-spec.md                 # 赛题输入输出格式规范 (v2)
├── research-scoring-rules.md              # 评分规则与打榜流程
├── research-description.md                # 参赛者赛题说明文档
├── research-experiments/                  # D 类公开小实验与离线标定材料
│   ├── publicdata/                        # D-01 ~ D-05 公开数据
│   ├── experiment.py                      # 离线实验核心执行器
│   ├── calibrate.py                       # 本地标定与验证工具
│   └── references.json                    # 官方已知参考指标与容差
└── downloaded_papers/                     # 核心参考文献集
```

---

## 快速开始

### 1. 本地环境对齐
```bash
# 建议使用 Python 3.9 ~ 3.11 环境
pip install -r research-experiments/requirements.txt
pip install PyMuPDF fastapi uvicorn httpx
```

### 2. D 类离线实验验证
```bash
cd research-experiments
python calibrate.py --data publicdata --output /tmp/calibration
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

