# 科研助手 Agent 竞赛项目大纲与实现方案

> 赛题：2026 CCF 网络大会 · 第一届全国高校 Agent 网络创新挑战赛 · 赛题 1「科研助手」
> 文档版本：2026-10-12

---

## 一、赛题核心理解

### 1.1 任务全景

| 类型 | 编号 | 满分 | 关键难点 |
|------|------|-----:|---------|
| Chat | A-* | 5 分 | 科研语境对话 + 追问澄清 |
| Literature_Retrieval | B-* | 15 分 | 本地 PDF 语义检索 + 真实文件名核验 |
| Survey | C-* | 25 分（事实15+引文10） | PDF 正文读取 + 页码级引用追溯 |
| Reproduction | D-* | 40 分（流水线20+数据图表20） | 调用冻结脚本 + 真实运行图表 |
| Idea | E-* | 15 分 | 8大槽位覆盖 + 观察/论文边界区分 |

**总分 100 分 × 25 题（每类5题）= 自动榜分（占综合成绩 70%）**

### 1.2 评分公式摘要（需精确实现）

```
检索(B): max(0, min(15, 15H/N - 0.75U))
综述事实(C): max(0, min(15, 15C/K - 3F))
引文溯源(C): max(0, min(10, 10V/M - 2H))
要点覆盖(E): 研究动机1.5+技术路线1.5+实验设计1.5+基准数据集1.5+量化指标1.5+复现瓶颈3+多文献互补3+场景可行性1.5
实验流水线(D): 通过检查点数/8 × 20
数据图表(D): 三项指标12分 + 图表检查8分
```

---

## 二、系统架构设计

### 2.1 整体架构

```
┌─────────────────────────────────────────────────┐
│            POST /solve  (FastAPI/Flask)          │
│  ┌──────────┐   dispatch.json   ┌─────────────┐  │
│  │  Router  │──────────────────▶│ Task Parser │  │
│  └──────────┘                   └─────────────┘  │
│       │                               │           │
│  ┌────▼────────────────────────────────▼────────┐ │
│  │              Task Dispatcher                 │ │
│  └──┬──────┬──────┬──────┬──────────────────────┘ │
│     │      │      │      │                         │
│  ┌──▼─┐ ┌──▼─┐ ┌──▼─┐ ┌──▼─┐  ┌──────┐          │
│  │Chat│ │ B  │ │ C  │ │ D  │  │  E   │          │
│  │    │ │Ret │ │Sur │ │Rep │  │ Idea │          │
│  └────┘ └────┘ └────┘ └────┘  └──────┘          │
│                                                   │
│  ┌──────────────────────────────────────────────┐ │
│  │              共享基础设施层                    │ │
│  │  PDF解析器 | 向量索引 | LLM客户端 | 文件写入器 │ │
│  └──────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────┘
```

### 2.2 Docker 镜像结构

```
agenthack-base:1.1.1
  └── our-agent:latest
        ├── /app/
        │   ├── main.py          # FastAPI 入口，GET /health + POST /solve
        │   ├── router.py        # 五类题型分发
        │   ├── handlers/
        │   │   ├── chat.py
        │   │   ├── retrieval.py
        │   │   ├── survey.py
        │   │   ├── reproduction.py
        │   │   └── idea.py
        │   ├── core/
        │   │   ├── pdf_reader.py   # pymupdf/pdfplumber
        │   │   ├── llm_client.py   # CHALLENGE_LLM_BASE_URL 封装
        │   │   ├── vector_index.py # 本地向量检索
        │   │   └── file_writer.py  # 写入+回读校验
        │   └── utils/
        │       ├── schema.py       # Pydantic 输出 schema
        │       └── evidence.py     # 证据链管理
        └── Dockerfile
```

---

## 三、各题型技术方案

### 3.1 A 类 Chat（5分 / 总体简单）

**实现要点：**
- 直接将 `input` 发给 LLM，要求回答为科研语境、产出 `answer` + `clarifying_question`
- 输出校验：两字段均非空，JSON 干净无包装

**评分拿满策略：**
- answer 使用 Prompt 模板强调"科研对话风格"
- clarifying_question 要针对研究范围（而非常识问题）

---

### 3.2 B 类 Literature_Retrieval（15分 / 关键分项）

**技术路线：**

```
题目 input 关键词提取
       │
       ▼
遍历 /data/papers/*.pdf
  ├─ 读取全文（pymupdf）
  ├─ 建立 BM25 / 向量索引（离线或懒加载）
  └─ 计算相关性得分
       │
       ▼
过滤阈值 + 去重
       │
       ▼
排序输出 papers[{filename, reason}]
```

**关键约束：**
- `filename` 必须是 `/data/papers/` 下实际存在的完整文件名（含空格、中文）
- `reason` 必须具体说明与检索需求的匹配点（非摘要复述）
- 排除不相关：排除标题相关但正文无内容的（必须读正文）

**评分公式 `15H/N - 0.75U`** → 宁可少报也不误报（U 每个 -0.75 分）

---

### 3.3 C 类 Survey（25分 / 最高权重）

**技术路线：**

```
指定 PDF materials 列表
       │
       ▼
精读每篇 PDF → 建立"事实-页码-论文"三元组库
       │
       ▼
LLM 综述生成（使用结构化 Prompt）
  ├─ 研究脉络梳理
  ├─ 方法对比
  ├─ 指标/数据对比
  └─ 结论与局限
       │
       ▼
[编号] / [编号, p.X] 标注 → 事实追溯
       │
       ▼
## 参考文献 + 写入 data/expert/C-xx-综述-队伍名.md
       │
       ▼
JSON markdown 字段 = 文件内容（逐字一致）
```

**评分关键：**
- `15C/K - 3F`：严重事实错误 F 每个 -3分，必须 zero hallucination
- `10V/M - 2H`：引用幻觉 H 每个 -2分，页码必须真实可核验
- 至少 800 字符，至少 5 篇引用

---

### 3.4 D 类 Reproduction（40分 / 最高难度分项）

**实现路线（核心：调用冻结脚本，不造假）：**

```python
# Agent 收到 D 类任务后
import subprocess, json, os

case_id = task["case_id"]  # e.g. "D-03"

result = subprocess.run(
    ["python", "/data/experiments/run_experiment.py", "--case", case_id],
    capture_output=True, text=True, timeout=150
)

# 读取平台写入的 submission.json
submission = json.load(open(f"/output/submission.json"))

# 校验三项指标名称/单位与题目 input 一致
# 校验图片文件真实存在
# 写入本队结果目录
```

**D 类5题公开指标（已知，可本地预先验证）：**

| 题号 | 指标1 | 指标2 | 指标3 |
|------|-------|-------|-------|
| D-01 | Macro-F1 (分数) | Accuracy (%) | 运行时间 (秒) |
| D-02 | Recall@5 (%) | MRR@10 (分数) | 查询吞吐 (queries/s) |
| D-03 | 推理吞吐 (samples/s) | P95 延迟 (ms) | 缓存命中率 (%) |
| D-04 | 验证集准确率 (%) | 约束通过率 (%) | 搜索耗时 (分钟) |
| D-05 | 公平性 Jain 指数 (分数) | 归一化吞吐 (%) | 平均等待时间 (ms) |

**图表满分要点（8分）：**
- 文件真实存在（哈希核验）
- x_label / y_label / legend 完整
- 与运行证据哈希匹配

---

### 3.5 E 类 Idea（15分 / 8槽位）

**8 个必须覆盖的槽位（要点覆盖类评分）：**

| 槽位 | 分值 | 内容要求 |
|------|-----:|---------|
| 研究动机 | 1.5 | 结合指定论文说明已有方法局限 |
| 技术路线 | 1.5 | 核心创新机制（区别于已有方法） |
| 实验设计 | 1.5 | 具体实验流程、消融方案 |
| 基准数据集 | 1.5 | 明确列出数据集名称及规模 |
| 量化评价指标 | 1.5 | 具体指标名称和计算方式 |
| 复现瓶颈反思 | 3.0 | 题目模拟观察的边界说明 |
| 多文献互补机制 | 3.0 | ≥2篇论文的互补关系 |
| 场景可行性与落地约束 | 1.5 | 可行性分析、失败边界 |

**关键约束：** 模拟观察只能作为"待验证现象"，不能写成论文实测结论

---

## 四、技术选型建议

| 组件 | 推荐方案 | 备注 |
|------|---------|------|
| Web 框架 | FastAPI + uvicorn | 轻量，支持异步 |
| PDF 解析 | pymupdf (fitz) | 速度快，支持文本提取 |
| 向量检索 | sentence-transformers + faiss-cpu | 离线，无网络 |
| BM25 检索 | rank_bm25 | 轻量，纯 Python |
| LLM 调用 | httpx + 自建重试封装 | 需携带 X-Session-ID |
| 输出校验 | pydantic v2 | 严格 schema 验证 |
| 图表生成 | matplotlib | D 类脚本已自动生成 |

---

## 五、调研清单（需自主调研）

### 5.1 PDF 解析与文献检索技术

**需调研的核心问题：**
- [ ] 如何处理扫描版 PDF（OCR fallback）
- [ ] 如何在有限内存（1024 MiB）下处理大规模 PDF 库
- [ ] 页码提取准确性：pymupdf vs pdfplumber vs pdfminer

**推荐论文来源（AI 六大会议）：**

| 会议 | 方向 | 关键词 |
|------|------|--------|
| ACL 2024/2025 | 文献检索、RAG | "RAG PDF extraction", "scientific document understanding" |
| EMNLP 2024 | 科学文献 NLP | "scientific information extraction" |
| SIGIR 2024/2025 | 信息检索 | "dense retrieval", "hybrid search BM25+dense" |
| NAACL 2024 | 问答+检索 | "multi-hop retrieval" |
| ACL Findings 2024 | 文献综述自动化 | "automated survey generation" |

**具体论文调研任务：**
- [ ] 搜索 "SciPDF Parser" / "Nougat" (Meta) / "Grobid" —— 选最适合竞赛环境的
- [ ] 调研 `rank_bm25` vs `whoosh` vs `elasticsearch` 离线性能对比
- [ ] 调研 sentence-transformers 模型哪个在科学文本最优（`allenai/specter2` vs `BAAI/bge-m3`）

---

### 5.2 RAG 与检索增强生成

**需调研的核心问题：**
- [ ] Chunk 策略：按段落 vs 按页码 vs 按句子
- [ ] 如何在 Survey 中保证引用准确性（防幻觉）
- [ ] Hybrid Search（BM25 + dense）融合权重

**推荐论文来源：**

| 论文 | 会议 | 要点 |
|------|------|------|
| "RAG vs Fine-Tuning" | ACL 2024 | 对比 RAG 与微调在知识密集任务 |
| "Lost in the Middle" | TMLR 2023 | LLM 中间位置遗忘问题 → 影响长文档 Survey |
| "Self-RAG" | NeurIPS 2023 | 自我检索反思机制 |
| "FreshLLMs" | EMNLP 2024 | 知识时效性 |
| RAPTOR (ICLR 2024) | ICLR 2024 | 递归摘要树检索 |

**调研任务：**
- [ ] 精读 "Lost in the Middle"（与 Survey 引用顺序设计直接相关）
- [ ] 调研 LangChain / LlamaIndex 的 citation 模块实现
- [ ] 搜索 SIGIR 2024: "grounded text generation with citations"

---

### 5.3 科学综述自动生成

**需调研的核心问题：**
- [ ] 如何自动生成带准确页码引用的综述
- [ ] 如何做事实一致性检验（防止 15C/K - 3F 中 F > 0）

**推荐论文来源：**

| 论文 | 会议 | 要点 |
|------|------|------|
| "AutoSurvey" | - | 自动综述生成 |
| "SurveyAgent" | ACL 2024 | Agent 驱动综述生成 |
| "MuMuQA" | AAAI 2024 | 多文档问答中的事实核验 |
| "FActScore" | EMNLP 2023 | 细粒度事实评分（与评分公式高度相关） |
| "RARR" | ACL 2023 | 检索增强修订（后处理纠错） |

**调研任务：**
- [ ] 精读 "FActScore" ——直接对应综述事实类评分逻辑
- [ ] 搜索 ACL Anthology: "survey generation citation accuracy"
- [ ] 搜索 EMNLP 2024: "hallucination detection scientific text"

---

### 5.4 Agent 框架与工具调用

**需调研的核心问题：**
- [ ] 单任务 180 秒内完成 25 题的并发策略
- [ ] Agent 如何高效调用本地工具（文件读写）

**推荐论文来源：**

| 论文 | 会议 | 要点 |
|------|------|------|
| ReAct | ICLR 2023 | 推理+行动交错 |
| ToolLLM | ICLR 2024 | 工具调用优化 |
| "AgentBench" | ICLR 2024 | Agent 评测框架 |
| "LLM-Agents Survey" | ACM 2024 | Agent 系统综述 |
| AutoGen | NeurIPS 2023 | 多 Agent 协作 |

**调研任务：**
- [ ] 搜索 ASE-2026 现有论文库中 "Agentic" 相关论文（已有本地资料）
- [ ] 重点读：`From Plan to Action- How Well Do Agents Follow the Plan?.pdf`
- [ ] 重点读：`DCAS- Decoupling CLI Agent Scaffolding.pdf`

---

### 5.5 实验复现（D 类专项）

**需调研的核心问题：**
- [ ] 如何在 Docker 容器内可靠调用子进程
- [ ] 如何解析 stdout JSON Lines 并处理失败
- [ ] 图表哈希核验的具体机制

**调研任务：**
- [ ] 本地运行所有 5 个公开实验（D-01 ～ D-05），记录输出格式
- [ ] 验证 `calibrate.py` 通过（确认依赖版本）
- [ ] 测试超时处理：subprocess timeout=150 的边界行为
- [ ] 研究 `references.json` 中容差设计（timing_sensitive 指标容差大）

---

### 5.6 Docker 工程与接入

**需调研的核心问题：**
- [ ] agenthack-base:1.1.1 镜像内置了什么（避免重复安装）
- [ ] 非 root 用户（agent）写入目录的权限配置
- [ ] `RESEARCH_WORKSPACE_TEAM` 环境变量读取方式

**调研任务：**
- [ ] 下载并 `docker load` 基础镜像，`docker inspect` 查看内置依赖
- [ ] 测试 `/health` 和 `/solve` 端点的标准响应格式
- [ ] 确认 `X-Session-ID` header 正确传递方式

---

## 六、项目实现里程碑

### Phase 1：基础框架（Day 1-2）

- [ ] 搭建 FastAPI `/health` + `/solve` 骨架
- [ ] 实现 dispatch.json 解析 + 五类路由分发
- [ ] 实现标准 Pydantic 输出 Schema（5 类）
- [ ] 实现文件写入 + 回读校验（含 Markdown 一致性检查）
- [ ] 本地跑通 D-01 ～ D-05 公开实验

### Phase 2：核心能力（Day 3-5）

- [ ] **PDF 解析层**：pymupdf 全文 + 页码提取，建立文件名→段落索引
- [ ] **B 类检索**：BM25 + 向量检索双路，结果去重排序，reason 生成
- [ ] **C 类 Survey**：证据三元组构建，结构化综述 Prompt，引用生成
- [ ] **E 类 Idea**：8槽位 Prompt 模板，模拟观察边界强制区分
- [ ] **D 类 Reproduction**：subprocess 调用冻结脚本，解析输出，路径校验

### Phase 3：优化与防御（Day 6-7）

- [ ] **幻觉防御**：事实对比检查（Survey C 类 F 惩罚 -3/个）
- [ ] **引用核验**：页码回查（C 类 H 惩罚 -2/个）
- [ ] **B 类误报防御**：正文相关性二次过滤（U 惩罚 -0.75/个）
- [ ] **超时保护**：每题 160 秒软超时，降级返回 failed/空
- [ ] **路径安全**：禁止 `..`、绝对路径、跨队目录

### Phase 4：Docker 打包与测试（Day 8）

- [ ] Dockerfile 基于 agenthack-base:1.1.1 构建
- [ ] 非 root 用户 agent 权限测试
- [ ] 端到端联调：模拟平台 POST /solve 25题
- [ ] 运行 `validate_submission.py` 预检查
- [ ] 镜像 save 为 tar 上传

---

## 七、评分优化策略（得分最大化）

### 7.1 得分优先级排序

```
D 类（40分/题）> C 类（25分/题）> B 类（15分/题）= E 类（15分/题）> A 类（5分/题）
```

### 7.2 各类防御性策略

**B 类（检索）：宁少不误**
```
策略：设置高相关性阈值，不返回把握不大的论文
原因：H 每个命中 +15/N，U 每个误报 -0.75，误报代价轻但积累可观
```

**C 类（综述）：零幻觉原则**
```
策略：所有事实必须从 PDF 正文查到原文再引用
原因：F 每个 -3 分（严重），H 每个 -2 分
工程：建立"事实-页码"映射，引用前回查
```

**D 类（复现）：只用冻结脚本**
```
策略：100% 依赖平台 runner，不自行伪造任何数值
原因：平台有 strace + 文件哈希核验，造假=0分
工程：subprocess + timeout + 结果文件存在性校验
```

**E 类（Idea）：覆盖全部槽位**
```
策略：用结构化 Prompt 模板，强制 8 个章节标题
原因：每个槽位有固定分值，未覆盖=直接失分
工程：Prompt 中明确列出 8 项，后处理检查所有标题存在
```

### 7.3 时间管理

```
单题最大 180 秒，Agent 阶段总上限 90 分钟（25 题）
建议：A/B/E 各 ≤ 60 秒，C ≤ 120 秒，D ≤ 150 秒
并发：可同类型并发处理，注意文件写入互斥
```

---

## 八、本地现有资料利用

### 8.1 已有论文（agent_papers/）

| 分类 | 数量 | 与赛题相关性 |
|------|-----:|-----------|
| ASE-2026 | ~50篇 | B 类检索材料 + 技术参考 |
| ICSE-2026 | ~30篇 | B 类检索材料 + 技术参考 |
| ISSTA-2026 | ~1篇 | B 类检索材料 |

**重点阅读建议（与 Agent 构建最直接相关）：**
- `From Plan to Action- How Well Do Agents Follow the Plan?.pdf` → Agent 规划能力
- `DCAS- Decoupling CLI Agent Scaffolding.pdf` → Agent 脚手架设计
- `FallibleUser- An Imperfect User Agent for Realistic Evaluation.pdf` → 评估视角
- `AgentSpec_Customizable_Runtime_Enforcement_for_Safe_and_Reliable_LLM_Agents.pdf` → 安全约束

### 8.2 已有实验材料（research-experiments/）

- `experiment.py` / `run_experiment.py` — 直接用于 D 类
- `publicdata/D-01.json` ～ `D-05.json` — 本地测试数据
- `references.json` — 已知公开参考值和容差
- `calibrate.py` — 本地验证脚本

**立即可做：**
```bash
cd research-experiments
pip install -r requirements.txt
python calibrate.py --data publicdata --output calibration
```

---

## 九、需要自主调研的论文清单

### 9.1 必读（直接影响评分）

| 优先级 | 论文 | 来源 | 与评分的关联 |
|--------|------|------|------------|
| ⭐⭐⭐ | FActScore: Fine-grained Atomic Evaluation of Factual Precision | EMNLP 2023 | C类 `15C/K - 3F` |
| ⭐⭐⭐ | Lost in the Middle: How Language Models Use Long Contexts | TMLR 2023 | C类长文档引用顺序 |
| ⭐⭐⭐ | Self-RAG: Learning to Retrieve, Generate, and Critique | NeurIPS 2023 | B/C类检索准确率 |
| ⭐⭐⭐ | RARR: Researching and Revising What Language Models Say | ACL 2023 | C类事实纠错 |
| ⭐⭐⭐ | RAPTOR: Recursive Abstractive Processing for Tree-Organized Retrieval | ICLR 2024 | C类多层次检索 |

### 9.2 推荐（工程实现参考）

| 优先级 | 论文 | 来源 | 用途 |
|--------|------|------|------|
| ⭐⭐ | Nougat: Neural Optical Understanding for Academic Documents | Meta/EMNLP 2023 | PDF解析 |
| ⭐⭐ | SPECTER2: Adapting Scientific Document Representations | ACL 2023 | 科学文本向量化 |
| ⭐⭐ | Hybrid Retrieval with BM25 and Dense Encoders | SIGIR 2024 | B类混合检索 |
| ⭐⭐ | SurveyAgent: A Conversational System for Personalized Literature Survey | ACL 2024 | C/E类生成 |
| ⭐⭐ | ToolLLM: Facilitating Large Language Models to Master 16000+ Real-world APIs | ICLR 2024 | D类工具调用 |

### 9.3 搜索关键词清单（自行检索）

去以下来源搜索（推荐用 Semantic Scholar / Google Scholar / ACL Anthology）：

```
SIGIR 2024:
  - "grounded citation generation"
  - "dense passage retrieval evaluation"
  - "scientific document retrieval benchmark"

ACL 2024:
  - "survey generation with citations"
  - "faithful summarization scientific papers"
  - "citation hallucination detection"

EMNLP 2024:
  - "attribution in text generation"
  - "RAG factuality"
  - "scientific claim verification"

NeurIPS 2024:
  - "agent tool use benchmark"
  - "long-form generation factual consistency"

ICLR 2025:
  - "retrieval augmented generation faithfulness"
  - "agent planning"

AAAI 2024/2025:
  - "multi-document question answering"
  - "evidence-based text generation"
```

---

## 十、风险与应对

| 风险 | 概率 | 影响 | 应对 |
|------|------|------|------|
| D类运行超时 | 中 | -40分/题 | 本地测试每题耗时，预设 150s 超时 |
| C类引用幻觉 | 高 | -2分/个 | 回查机制，不用 LLM 直接生成页码 |
| B类误报 | 中 | -0.75/个 | 设高阈值，宁缺毋滥 |
| PDF 解析失败 | 中 | B/C 失分 | 多个解析库备用（pymupdf + pdfplumber） |
| 镜像非 root 权限 | 低 | 全部 0 分 | 提前用 agent 用户测试写入路径 |
| 内存超限（1024 MiB） | 中 | 崩溃 | 惰性加载索引，处理完释放 |

---

*生成时间：2026-10-12 | 基于 research-agent-spec.md / research-scoring-rules.md / research-description.md / research-experiments/README.md*
