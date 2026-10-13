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
