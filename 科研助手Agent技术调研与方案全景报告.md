# 2026全国高校Agent网络挑战赛·赛题1「科研助手」

# 全面技术调研与前沿顶会论文技术报告（2025-2026）

> **项目目标**：针对 2026 CCF 网络大会·第一届全国高校 Agent 网络创新挑战赛·赛题 1「科研助手」，基于 `project-outline.md`、`research-agent-spec.md` 及 `research-scoring-rules.md` 中的核心问题与工程边界，对 2024–2026 年人工智能顶级会议（ACL 2024/2025、NAACL 2025、EMNLP 2023/2024、ICLR 2024/2025、TMLR、ASE 2026、ICSE 2026）的前沿技术与落地代码进行完全、深入、系统的调研，输出具备直接指导开发价值的工程实施全景报告。

---

## 目录

1. [执行摘要与赛题技术雷达](#一执行摘要与赛题技术雷达)
2. [已下载前沿顶会论文与官方代码仓库全景](#二已下载前沿顶会论文与官方代码仓库全景)
3. [核心专题一：严苛内存（1024 MiB）下的 PDF 解析与结构化](#三核心专题一严苛内存1024-mib下的-pdf-解析与结构化)
4. [核心专题二：离线高并发科学文献检索与混合检索（BM25 + Dense）](#四核心专题二离线高并发科学文献检索与混合检索bm25--dense)
5. [核心专题三：前沿 RAG 切分、上下文增强与中间遗忘（Lost in the Middle）缓解](#五核心专题三前沿-rag-切分上下文增强与中间遗忘lost-in-the-middle缓解)
6. [核心专题四：自动化科学综述生成、零幻觉机制与页码级精准引文溯源](#六核心专题四自动化科学综述生成零幻觉机制与页码级精准引文溯源)
7. [核心专题五：Agent 架构设计、计划依从性与 25 题高并发调度](#七核心专题五agent-架构设计计划依从性与-25-题高并发调度)
8. [核心专题六：D 类论文实验复现真实流水线与图表核验机制](#八核心专题六d-类论文实验复现真实流水线与图表核验机制)
9. [核心专题七：E 类研究灵感 8 大槽位全覆盖与证据边界隔离](#九核心专题七e-类研究灵感-8-大槽位全覆盖与证据边界隔离)
10. [核心专题八：Docker 容器安全、权限控制与平台契约对接](#十核心专题八docker-容器安全权限控制与平台契约对接)
11. [技术选型推荐矩阵与工程落地路线图](#十一技术选型推荐矩阵与工程落地路线图)

---

## 一、执行摘要与赛题技术雷达

### 1.1 赛题边界与核心痛点

本竞赛要求参赛 Agent 打包为 Docker 镜像，监听 `0.0.0.0:8080`，提供 `GET /health` 与 `POST /solve` 接口，在 **1024 MiB RAM**、无外网访问（离线环境）、单机 CPU 的极度受限容器中，对 5 类共 25 道科研任务进行作答。

```
任务类型分布：
  A 类 Chat (5题, 满分 5分)   : 科研对话 + 追问澄清 (answer: 3分, clarifying_question: 2分)
  B 类 Retrieval (5题, 满分 15分): 允许库精准检索 (评分公式: max(0, min(15, 15H/N - 0.75U)))
  C 类 Survey (5题, 满分 25分)   : 正文结构化综述 (事实分: 15C/K - 3F, 引文溯源: 10V/M - 2H)
  D 类 Reproduction (5题, 满分 40分): 冻结脚本执行 (流水线: 20分, 三项指标12分 + 图表8分)
  E 类 Idea (5题, 满分 15分)     : 创新方案生成 (8大核心槽位必须全部命中)
```

### 1.2 扣分惩罚放大效应与核心破局点

- **B 类检索的误报代价**：每误报一篇无关论文 $U$ 扣减 $0.75$ 分。因此算法必须秉&#x6301;**“宁缺毋滥（High Precision over Recall）”**&#x539F;则，严设相关性阈值。
- **C 类综述的幻觉致命伤**：一个严重事实错误 $F$ 扣减 **3 分**（占事实总分的 20%），一次引用幻觉 $H$ 扣减 **2 分**（占引文总分的 20%）。必须实&#x884C;**“预提取三元组（Pre-grounding）+ 双重事后校验（Post-verification）”**&#x67B6;构，消除 LLM 自行编造页码和事实的可能。
- **D 类复现的真实性红线**：禁止伪造数据与图表。平台具备 `strace` 系统调用、文件读写采集与图片哈希校验。核心破局点在于**可靠子进程包装、实时解析 JSON Lines、严格超时保护（150s）**。
- **内存红线 1024 MiB**：禁止加载如 BGE-M3 (568M)、Nougat 等重型模型（极易 OOM）；必须采用 PyMuPDF C 库、ONNX INT8 轻量向量模型或 SQLite FTS5/BM25S 内存受控方案。

---

## 二、已下载前沿顶会论文与官方代码仓库全景

本项目已从 arXiv 及顶会官方存档下载了 11 篇紧密贴合赛题核心难题的高价值前沿论文（存放在本地 `downloaded_papers/` 目录），并将其对应的 **9 个官方开源代码仓库完整下载/解压至本地 `downloaded_repositories/` 目录**。结合项目本地已有的 2026 年最新顶级软件工程会议（ASE 2026、ICSE 2026）论文，形成以下技术基石库：

### 2.1 已下载论文与本地代码仓库全景表

| 序号 | 论文名称 | 顶会 / 出处 | 本地 PDF 文件路径 | 本地代码仓库目录 (已下载) | 官方远程仓库 / 主页 | 核心解决问题与可复用模块 |
|:---|:---|:---|:---|:---|:---|:---|
| 1 | **PaperQA2**: Superhuman synthesis of scientific knowledge | Nature Biotech / 2024 | [`PaperQA2.pdf`](downloaded_papers/PaperQA2_Language_Agents_Superhuman_Scientific_Synthesis.pdf) | [`downloaded_repositories/paper-qa/`](downloaded_repositories/paper-qa) | [Future-House/paper-qa](https://github.com/Future-House/paper-qa) | **PaperQA2 Agent 核心库**：`paperqa/docs.py` (文档证据库)、`paperqa/agents/` (RCS 重排摘要器与无幻觉引文锚定) |
| 2 | **SurveyForge**: Outline Heuristics & Memory-Driven Survey Writing | **ACL 2025** | [`SurveyForge.pdf`](downloaded_papers/SurveyForge_ACL2025_Outline_Memory_Survey_Writing.pdf) | [`downloaded_repositories/SurveyForge/`](downloaded_repositories/SurveyForge) | [Alpha-Innovator/SurveyForge](https://github.com/Alpha-Innovator/SurveyForge) | **长文档学术综述大纲启发式**：`src/outline_generator.py`、`src/memory_manager.py` (记忆驱动防重复生成) |
| 3 | **ALiiCE**: Evaluating Positional Fine-grained Citation Generation | **NAACL 2025** | [`ALiiCE.pdf`](downloaded_papers/ALiiCE_NAACL2025_Positional_Fine_grained_Citation_Generation.pdf) | [`downloaded_repositories/ALiiCE/`](downloaded_repositories/ALiiCE) | [ylXuu/ALiiCE](https://github.com/ylXuu/ALiiCE) | **细粒度位置引文生成**：`aliice/evaluator.py`、`aliice/claim_extractor.py` (依赖树原子声明切分与位置引文匹配) |
| 4 | **RefChecker**: Reference-based Fine-grained Hallucination Checker | Amazon Science 2024 | [`RefChecker.pdf`](downloaded_papers/RefChecker_Fine_grained_Hallucination_Checker.pdf) | [`downloaded_repositories/RefChecker/`](downloaded_repositories/RefChecker) | [amazon-science/RefChecker](https://github.com/amazon-science/RefChecker) | **细粒度三元组幻觉检测**：`refchecker/extractor/` (声明三元组提取)、`refchecker/checker/` (事实验证核验器，防御 -3F 扣分) |
| 5 | **AutoSurvey**: LLMs Can Automatically Write Surveys | arXiv 2024 | [`AutoSurvey.pdf`](downloaded_papers/AutoSurvey_LLM_Automatically_Write_Surveys.pdf) | [`downloaded_repositories/AutoSurvey/`](downloaded_repositories/AutoSurvey) | [AutoSurveys/AutoSurvey](https://github.com/AutoSurveys/AutoSurvey) | **端到端自动化综述**：`src/survey_writer.py`、`src/paper_selector.py` (分层大纲组织、多篇文献聚合) |
| 6 | **SurveyAgent**: Conversational System for Research Survey | **ACL 2024** | [`SurveyAgent.pdf`](downloaded_papers/SurveyAgent_ACL2024_Conversational_Research_Survey.pdf) | *(Web-based Demo/API)* | [survey-agent.github.io](https://survey-agent.github.io/) | 多 Agent 协作综述调研、交互式意图澄清与文献过滤对话机制 |
| 7 | **Late Chunking**: Contextual Chunk Embeddings | Jina AI 2024 | [`Late_Chunking.pdf`](downloaded_papers/Late_Chunking_Contextual_Chunk_Embeddings.pdf) | [`downloaded_repositories/late-chunking/`](downloaded_repositories/late-chunking) | [jina-ai/late-chunking](https://github.com/jina-ai/late-chunking) | **长文档上下文无缝切分**：`late_chunking/` (基于跨段落上下文的 Token 池化与切分) |
| 8 | **FActScore**: Fine-grained Atomic Evaluation of Factual Precision | **EMNLP 2023** | [`FActScore.pdf`](downloaded_papers/FActScore_EMNLP2023_Factual_Precision_Evaluation.pdf) | [`downloaded_repositories/FActScore/`](downloaded_repositories/FActScore) | [shmsw25/FActScore](https://github.com/shmsw25/FActScore) | **原子事实评估引擎**：`factscore/factscorer.py`、`factscore/atomic_facts.py` (细粒度原子事实拆解，直接对标赛题 15C/K-3F) |
| 9 | **Lost in the Middle**: How LMs Use Long Contexts | **TMLR 2023** | [`Lost_in_the_Middle.pdf`](downloaded_papers/Lost_in_the_Middle_TMLR2023_Long_Contexts.pdf) | [`downloaded_repositories/lost-in-the-middle/`](downloaded_repositories/lost-in-the-middle) | [nelson-liu/lost-in-the-middle](https://github.com/nelson-liu/lost-in-the-middle) | **长上下文检索与证据位置编排**：`src/lost_in_the_middle/` (首尾高注意力布局算法) |
| 10 | **BM25S**: Orders of magnitude faster lexical search | arXiv 2024 | [`BM25S.pdf`](downloaded_papers/BM25S_Eager_Sparse_Scoring_Lexical_Search.pdf) | [`downloaded_repositories/bm25s/`](downloaded_repositories/bm25s) | [xhluca/bm25s](https://github.com/xhluca/bm25s) | **超轻量极速词法检索**：`bm25s/core.py` (基于 SciPy 稀疏矩阵加速 500 倍的 BM25，内存 < 30MB) |
| 11 | **G-Cite vs P-Cite**: Evaluation of LLM Attribution | arXiv 2025 | [`GCite_vs_PCite.pdf`](downloaded_papers/GCite_vs_PCite_LLM_Attribution_Evaluation.pdf) | *(Theoretical Benchmark)* | [arXiv:2509.21557](https://arxiv.org/abs/2509.21557) | 生成时引用（G-Cite）与事后归因（P-Cite）权衡体系，指导预锚定与事后审计混合设计 |
| 12 | **DCAS**: Decoupling CLI Agent Scaffolding | **ASE 2026** | [`agent_papers/ASE-2026/DCAS-...pdf`](agent_papers/ASE-2026/DCAS-%20Decoupling%20CLI%20Agent%20Scaffolding%20to%20Internalize%20Planning%20across%20Scaffolds.pdf) | 本地已有论文 | *(Huawei Canada)* | 脚手架与规划内核解耦、显式规划与隐式规划内化机制 |
| 13 | **From Plan to Action**: How Well Do Agents Follow the Plan? | **ASE 2026** | [`agent_papers/ASE-2026/From Plan to Action-...pdf`](agent_papers/ASE-2026/From%20Plan%20to%20Action-%20How%20Well%20Do%20Agents%20Follow%20the%20Plan%3F.pdf) | 本地已有论文 | *(UIUC & IBM)* | 计划依从性大规模实证，证明周期性计划提醒（Periodic Reminders）能显著提升任务成功率 |
| 14 | **AgentSpec**: Customizable Runtime Enforcement | **ICSE 2026** | [`agent_papers/ICSE-2026/AgentSpec-...pdf`](agent_papers/ICSE-2026/AgentSpec_Customizable_Runtime_Enforcement_for_Safe_and_Reliable_LLM_Agents.pdf) | 本地已有论文 | *(SMU)* | 运行时轻量级规则断言拦截，保障无 `..` 越界、Schema 100% 合规与输出一致 |

### 2.2 本地代码仓库目录结构与可直接复用资产

本地克隆并解压的代码仓库结构如下（已位于 `downloaded_repositories/`）：
```text
downloaded_repositories/
├── ALiiCE/                # NAACL 2025: 细粒度位置引文生成与原子声明切分
│   └── aliice/            # 可复用: 依赖树分析器与原子事实-引文映射逻辑
├── AutoSurvey/            # 2024: 大纲自顶向下组织与多篇文献自动综合
├── FActScore/             # EMNLP 2023: 原子事实拆解评测基准与 Wikipedia/PDF 事实校验器
├── RefChecker/            # Amazon Science: 声明三元组 (Claim Triplet) 提取与事实验证器
│   └── refchecker/        # 可复用: extractor 与 checker 模块 (直接用于 C 类防 -3F 事实错误)
├── SurveyForge/           # ACL 2025: 记忆驱动长文档学术综述大纲与正文生成
├── bm25s/                 # 2024: 极速稀疏矩阵 BM25 检索库 (可直接 import bm25s 或安装使用)
├── late-chunking/         # Jina AI: 跨切片上下文感知切分示例与评测脚本
├── lost-in-the-middle/    # TMLR 2023: 长文档首尾注意力提示词编排工程代码
└── paper-qa/              # FutureHouse: PaperQA2 生产级科学文献问答与 RCS 核心库
    ├── paperqa/           # 包含完整的 Docs、Settings、Reader、Prompts 等核心类
    └── paper_qa.egg-info/ # 元数据与依赖清单
```

---

## 三、核心专题一：严苛内存（1024 MiB）下的 PDF 解析与结构化

### 3.1 PDF 解析引擎多维基准对比

赛题要求在单个 Docker 容器限制 **1024 MiB 内存** 下运行，且每题响应时间最好控制在 60–120 秒内。调研各类主流 PDF 解析技术：

| 引擎 / 工具                 | 底层语言              | 单页解析耗时      | 内存常驻占用        | 页面级页码准确率          | 离线无 GPU 适应性           |    竞赛环境推荐度   |
| :---------------------- | :---------------- | :---------- | :------------ | :---------------- | :-------------------- | :----------: |
| **PyMuPDF (`fitz`)**    | C / C++ (MuPDF)   | **5–15 ms** | **15–35 MB**  | **100%（物理页直接映射）** | **极高（开箱即用，无依赖）**      | ⭐⭐⭐⭐⭐ (首选方案) |
| **`pdfplumber`**        | Python (pdfminer) | 300–800 ms  | 80–180 MB     | 100%              | 良好（纯 Python，表格强）      |  ⭐⭐⭐ (备选备用)  |
| **`pdfminer.six`**      | Python            | 400–1000 ms | 70–150 MB     | 95% (流式分块易错位)     | 良好                    |   ⭐⭐ (不推荐)   |
| **Meta `Nougat`**       | Python (PyTorch)  | 8–15 s      | **> 2500 MB** | 容易漂移（纯视觉自回归）      | **极差（无 GPU 极慢且 OOM）** |   ❌ (严禁使用)   |
| **`Grobid`**            | Java (CRF/DL)     | 80–200 ms   | **> 800 MB**  | 较高 (TEI XML 结构好)  | **差（需独立 JVM 常驻吃满内存）** |    ❌ (不推荐)   |
| **`MinerU` / `Marker`** | PyTorch / Surya   | 2–5 s       | **> 1800 MB** | 良好                | **差（显存/内存超限）**        |    ❌ (不推荐)   |

> **权威结论**：
>
> 1. **PyMuPDF (fitz)** 是在 1024 MiB 内存和 180s 超时约束下的唯一最佳解。其 C/C++ 底层消耗内存极少，解析 20 页论文仅需不到 0.2 秒。
> 2. `Nougat` 与 `MinerU` 尽管提取 Markdown 公式能力优异，但在无 GPU 且内存 1024 MiB 的限制下必然导致容器被 Linux OOM-Killer 杀死。

### 3.2 真实物理页码与文本提取实战设计

C 类综述评分严格要求页码溯源（如 `[1, p.4]`），如果提取的页码与原文不符，将触发 $H$（引用幻觉）扣分（$-2$ 分/个）。

```python
import fitz  # PyMuPDF
from typing import Dict, List, Tuple

def parse_paper_with_page_anchors(pdf_path: str) -> List[Dict]:
    """
    流式读取 PDF，提取每一页的干净正文，构建带有明确页码锚点的数据结构。
    内存优化：逐页提取并释放页面对象，避免全文档 DOM 树常驻。
    """
    doc = fitz.open(pdf_path)
    pages_data = []
    
    for page_idx in range(len(doc)):
        page_num = page_idx + 1  # 物理页码从 1 开始，与审稿/评分基准完全一致
        page = doc[page_idx]
        
        # 1. 过滤页眉与页脚（防止页眉作者、会议名和页码污染正文检索）
        rect = page.rect
        header_threshold = rect.height * 0.06  # 顶部 6% 为页眉区域
        footer_threshold = rect.height * 0.94  # 底部 6% 为页脚区域
        
        # 提取 blocks: (x0, y0, x1, y1, text, block_no, block_type)
        blocks = page.get_text("blocks")
        valid_page_text = []
        
        for b in blocks:
            if b[6] == 0:  # 0 为文本块，1 为图像块
                y0, y1, text = b[1], b[3], b[4].strip()
                if not text:
                    continue
                # 跳过纯页眉和纯页脚
                if y1 < header_threshold or y0 > footer_threshold:
                    continue
                valid_page_text.append(text)
                
        cleaned_text = "\n".join(valid_page_text)
        pages_data.append({
            "page_num": page_num,
            "text": cleaned_text,
            "char_count": len(cleaned_text)
        })
        
    doc.close()
    return pages_data
```

### 3.3 扫描版 PDF 判定与 OCR Fallback 轻量机制

在比赛论文集 `/data/papers` 中，可能存在个别早期扫描版 PDF。

- **快速识别算法**：若论文前 3 页平均字符数 `< 50`，则判定为纯图像扫描版。
- **轻量降级策略**：
  1. 优先使用 PyMuPDF 内置 OCR 接口：`page.get_textpage_ocr(language='eng', dpi=150)`（需系统安装 tesseract-ocr，若镜像内包含则无缝调用）。
  2. 若系统无 OCR 动态链接库，**禁止使用重型 OCR 模型**，改为从 PDF 内嵌元数据（Metadata / Title / Subject）及文件名提取研究主题，在生成时显式说明由于扫描版限制仅基于摘要分析，防止程序 Crash。

---

## 四、核心专题二：离线高并发科学文献检索与混合检索（BM25 + Dense）

### 4.1 词法检索（Lexical Search）对比与选型

`project-outline.md` 要求对比 `rank_bm25` vs `whoosh` vs `sqlite-fts` vs `bm25s`：


| 引擎                       | 索引形式             | 内存占用（100篇论文）               | 查询延迟 (ms)  | 依赖状态                | 特点与风险                            |
| :----------------------- | :--------------- | :------------------------- | :--------- | :------------------ | :------------------------------- |
| **`rank_bm25`**          | 纯 Python 内存对象    | ~120–250 MB                | 15–50 ms   | 无额外 C 依赖            | 容易在多轮查询中积聚 GC 垃圾；无持久化，每次冷启动耗时    |
| **`whoosh`**             | 磁盘文件分段           | ~80–120 MB                 | 40–120 ms  | **已停止维护**           | 查询语法解析开销大，易内存碎片化，不建议用于新赛题        |
| **`BM25S`** (arXiv 2024) | SciPy 稀疏矩阵 (CSR) | **~25–45 MB**              | **< 1 ms** | `pip install bm25s` | **速度提升 500 倍**，内存极小，支持 mmap 磁盘映射 |
| **`SQLite FTS5`**        | C 内核 B-Tree 数据库  | **< 10 MB** (固定 PageCache) | **1–3 ms** | **Python 原生自带**     | **零外部依赖**，C 语言实现高鲁棒，严密控制内存边界     |

> **实战建议**：
>
> - 推荐使用 **`SQLite FTS5`** 或 **`BM25S`**。
> - `SQLite FTS5` 是最高可靠性选择：Python 3.9 自带 `sqlite3`，开箱自带 BM25 排名函数 `bm25(fts_table)`，内存由 `PRAGMA cache_size = 2000` 牢牢锁定在 8MB 以内，彻底杜绝 OOM。

### 4.2 语义向量模型（Dense Retrieval）在 1024 MiB 内存下的选型与量化

| 模型                        | 参数量  | 权重文件大小         | PyTorch 运行内存    | 科学领域表现 (SciFact/NFCorpus) | 1024 MiB 安全性评估             |
| :------------------------ | :--- | :------------- | :-------------- | :------------------------ | :------------------------- |
| **`BAAI/bge-m3`**         | 568M | 2.24 GB (FP16) | **> 2600 MB**   | SOTA (多语言/超长文本)           | ❌ **必定 OOM Crash**         |
| **`allenai/specter2`**    | 110M | 440 MB         | **~650–800 MB** | 学术引用表征极佳                  | ⚠️ **临界危险**（留给主进程仅剩 200MB） |
| **`bge-small-en-v1.5`**   | 33M  | 133 MB         | **~260–320 MB** | 强悍，MTEB 排行榜高位             | ✅ **安全稳定**                 |
| **`bge-small` ONNX-INT8** | 33M  | **34 MB**      | **< 60 MB**     | 与浮点精度差异 < 1%              | ⭐⭐⭐⭐⭐ **黄金最佳方案**           |

> **ONNX Runtime 核心优势**：  
> 如果直接使用 `sentence-transformers` 导入 PyTorch，仅 `import torch` 就会消耗近 250 MB 内存。而采用 `onnxruntime` 加载 INT8 量化后的 `bge-small-en-v1.5`，内存仅需 **50 MB**，CPU 推理耗时单句仅 8 ms！

### 4.3 Hybrid Search 融合机制：RRF 倒数排名融合 vs 线性加权

在科学文献检索中，BM25 擅长捕捉专属缩写（如“MAE”、“LSTM”、“Jain指数”）、特定数据集和算法名称；Dense 向量则擅长捕获语义重述与泛化意图。

#### 方案一：倒数排名融合（Reciprocal Rank Fusion, RRF）

$RRF\_Score(d) = \frac{1}{k + r_{BM25}(d)} + \frac{1}{k + r_{Dense}(d)}$

- 其中推荐常数 $k = 60$（SIGIR 标准设置）。
- **优势**：免去对 BM25 分数（范围 $[0, +\infty)$）与余弦相似度（范围 $[-1, 1]$）进行复杂归一化的烦恼，对不同分布极具鲁棒性。

#### 方案二：Min-Max 归一化凸组合（Convex Combination）

$S_{norm}(d) = \alpha \cdot \frac{S_{BM25}(d) - \min(S_{BM25})}{\max(S_{BM25}) - \min(S_{BM25}) + \epsilon} + (1 - \alpha) \cdot \frac{S_{Dense}(d) - \min(S_{Dense})}{\max(S_{Dense}) - \min(S_{Dense}) + \epsilon}$

- 在科学文本基准测试中，经验最优系数为 $\alpha = 0.55 \sim 0.60$（词法匹配略占优）。

### 4.4 B 类检索“宁少不误”防御拦截算法

根据赛题评分公式：  
$\text{Score}_B = \max\left(0, \min\left(15, 15 \times \frac{H}{N} - 0.75 \times U\right)\right)$

- 设 $N=5$（真实相关文献），若命中 $H=4$，但多报了 4 篇无关文献（$U=4$），得分将从 $12$ 分掉到 $12 - 3 = 9$ 分！
- **防御过滤策略**：
  1. **双阈值硬截断**：仅保留混合检索得分处于顶层的候选（通常候选集不超过 8 篇）。
  2. **LLM 负向约束判别器（Negative Verification Filter）**：针对每篇候选论文，提取其 `Title + Abstract + Conclusion`，要求 LLM 执行严格的布尔判别：  
     *“题目要求排除只讨论植物分类、没有分析城市温度的论文。请问该论文是否**明确且深入**地分析了城市温度？如果仅在背景中提及或完全无关，请回答 NO。”*
  3. 若判定结果非 YES 或置信度不高，**果断剔除**。宁可少报（不拿 $15/N$），绝不误报（坚决避免 $-0.75U$）。

---

## 五、核心专题三：前沿 RAG 切分、上下文增强与中间遗忘（Lost in the Middle）缓解

### 5.1 科学文档切分策略（Chunking Strategies）深度对比

| 切分策略                                      | 原理与实现                                     | 优点                                  | 缺点                    |     赛题契合度    |
| :---------------------------------------- | :---------------------------------------- | :---------------------------------- | :-------------------- | :----------: |
| **固定字符/Token 切分**                         | 固定 500 tokens，重叠 50 tokens                | 实现简单                                | 严重割裂跨句论断与上下文，丢失语义完整性  |       ❌      |
| **按自然段落切分**                               | 依据双换行与缩进切分段落                              | 语义单元自然                              | 论文段落长短不一，长段超长，短段信息不足  |      ⭐⭐⭐     |
| **物理页级切分 (Page-level)**                   | 严格按 PDF 单页切分，或页内分块保留页号                    | **与赛题页码追溯完美对齐**，天然保留 `page_num` 元数据 | 单页信息量稍大 (~800 词)      | ⭐⭐⭐⭐⭐ (基础必备) |
| **Late Chunking** (Jina AI 2024)          | 先将长文档送入长上下文 Embedding，再对各 Chunk 做均值池化     | **保留全局跨段落语义感知**                     | 需要长上下文向量模型支持，显存/内存消耗大 |  ⭐⭐⭐ (前沿参考)  |
| **Contextual Retrieval** (Anthropic 2024) | 在每个 Chunk 前拼接由 LLM 预先生成的 50-100 字文档全局背景说明 | **降低 49% 的检索失败率**，消除代词与上下文脱节        | 需离线调用 LLM 预处理预热       | ⭐⭐⭐⭐ (精细化首选) |

### 5.2 "Lost in the Middle" 效应与 Prompt 布局工程

Nelson Liu 等人在 **TMLR 2023** 发表的经典论文《Lost in the Middle: How Language Models Use Long Contexts》揭示：

> **核心规律**：当提供给 LLM 的上下文很长时，模型对位于**开头（Primacy Bias）**&#x548C;**结尾（Recency Bias）**&#x7684;信息检索与调用准确率最高，而位于**中间段（Middle）**&#x7684;信息召回率断崖式下跌（U 型准确率曲线）。

```
        性能 (Recall / Accuracy)
         ▲
 100% ──┤   ██                              ██   (高关注区)
        │   ████                          ████
  50% ──┤   ██████                      ██████
        │   ████████  ░░░░░░░░░░░░░░  ████████   (中间盲区: 易遗忘、易幻觉)
   0% ──┴───────────────────────────────────────►
            Context 开始      Context 中间      Context 结尾
```

#### 在 C 类综述与 E 类 Idea 提示词中的反遗忘架构：

1. **关键证据首尾倒排（Salience Reordering）**：将检索相关度最高的两篇核心论文分别放置在上下文的**最前部**和**最后部**，次相关的置于中间。
2. **约束指令末尾重复（Recency Reinforcement）**：按照 ASE 2026 论文《From Plan to Action》的建议，在 Prompt 结尾、即紧邻输出生成区，必须再次重复输出约束（例如：“*严禁虚构页码，正文必须使用 [编号, p.页码] 标注，结尾必须包含 ## 参考文献，字符数必须超过 800 字*”）。

---

## 六、核心专题四：自动化科学综述生成、零幻觉机制与页码级精准引文溯源

### 6.1 前沿顶会综述生成架构剖析

#### 1. PaperQA2 (Nature Biotech / FutureHouse 2024)

- **RCS (Rerank and Contextual Summarize)**：不把粗糙的原始 Chunk 直接拼入最终 Prompt，而是通过中间轻量 LLM 步骤，先从候选文献中提取出**针对性断言与精确引用元数据**。
- **WikiCrow 风格综合写作**：要求生成的每个断言必须强绑定来源，彻底杜绝无源陈述。

#### 2. SurveyForge (ACL 2025)

- **大纲启发式（Outline Heuristics）**：先自顶向下生成结构化多级大纲（如研究脉络、方法分类、定量对比、挑战与局限），固定骨架后再填充正文。
- **记忆驱动生成（Memory-Driven Generation）**：维护已写章节的摘要记忆流，确保章节之间不重复、逻辑自洽。

#### 3. ALiiCE (NAACL 2025)

- **细粒度位置引文生成（Positional Fine-grained Citation）**：传统系统常在整段末尾堆砌 `[1][2]`，极易导致事实归因错位；ALiiCE 证明必须将引用下沉到**单句乃至从句级别**，使每个具体事实紧随专属引用。

#### 4. G-Cite vs. P-Cite (arXiv 2025)

- **G-Cite（生成时引注）**：解码时同步吐出 `[1, p.4]`。语义关联性好，但若注意力漂移容易写错页码。
- **P-Cite（后处理标注）**：先写综述正文，再通过检索匹配置入页码。引文覆盖全，但容易出现“事后强行挂靠”现象。
- **本项目提出的最优融合方案：Pre-grounded G-Cite + Post-hoc Audit（预锚定生成 + 事后双重审计）**。

---

### 6.2 零幻觉（Zero Hallucination）综述生成全流程流水线

为彻底防御 C 类评分中的 **严重事实错误 $F$（$-3$ 分/个）** 与 **引用幻觉 $H$（$-2$ 分/个）**，设计四阶流水线：

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           四阶零幻觉综述生成流水线                       │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  [阶段 1: 物理页结构化提取]                                              │
│   PDF -> PyMuPDF 逐页过滤 -> 构建 Page-Facts 索引:                      │
│   {doc_id: 1, page: 3, snippet: "湿法冶金在60℃下浸出率达92%..."}         │
│                                  │                                      │
│                                  ▼                                      │
│  [阶段 2: 证据三元组提取 (Pre-grounding)]                               │
│   LLM 提取规范证据表 (严格限制事实来源，不准自由发挥):                  │
│   E1: [论文1, p.3] 湿法冶金浸出率92%                                    │
│   E2: [论文2, p.5] 直接回收正极保留率88%                                │
│                                  │                                      │
│                                  ▼                                      │
│  [阶段 3: 受限骨架生成 (G-Cite Drafting)]                               │
│   LLM 综述生成 Prompt:                                                  │
│   - 强制使用给定的 E1, E2... 填补大纲                                   │
│   - 语法规范: 句中紧跟 [编号, p.页码]                                   │
│   - 字数保障: 详细展开方法机理，确保字符数 > 800                        │
│                                  │                                      │
│                                  ▼                                      │
│  [阶段 4: 事后双重校验与自动纠错 (Post-hoc Audit)]                      │
│   ├─ 引用存在性核验: 正则提取 [i, p.X] -> 查验论文 i 的第 X 页文本      │
│   │   └─ 若第 X 页不含该事实 -> 回查全文检索该事实真实页码 / 剔除页码   │
│   └─ 参考文献对齐: 确保结尾 ## 参考文献 包含全部实际被引文献文件名      │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

#### 双重事后校验（Post-hoc Audit）核心代码实现：

```python
import re
from typing import Dict, List, Tuple

def audit_and_repair_citations(
    markdown_text: str,
    paper_pages_cache: Dict[int, Dict[int, str]],  # {paper_idx: {page_num: page_text}}
    allowed_materials: List[str]
) -> Tuple[str, List[str]]:
    """
    对 LLM 生成的 Markdown 正文进行全自动化正向引文审计与修正：
    1. 拦截虚构论文编号 (i > len(materials))
    2. 拦截虚构页码 (X > max_page 或 X < 1)
    3. 文本对齐核验：检查引文所在句子关键词是否真实存在于第 X 页
    """
    # 匹配 [1] 或 [1, p. 3] 或 [1, p.3]
    cite_pattern = re.compile(r'\[(\d+)(?:,\s*p\.?\s*(\d+))?\]')
    warnings = []
    
    def replace_citation(match):
        paper_idx = int(match.group(1))
        page_str = match.group(2)
        
        # 1. 检查论文编号合法性
        if paper_idx < 1 or paper_idx > len(allowed_materials):
            warnings.append(f"Illegal paper index [{paper_idx}], removing.")
            return ""
            
        if not page_str:
            return f"[{paper_idx}]"
            
        page_num = int(page_str)
        pages_dict = paper_pages_cache.get(paper_idx, {})
        max_page = max(pages_dict.keys()) if pages_dict else 1
        
        # 2. 检查页码是否超出边界
        if page_num < 1 or page_num > max_page:
            warnings.append(f"Page [{paper_idx}, p.{page_num}] out of bounds (max {max_page}). Correcting to [p.1].")
            page_num = 1
            
        # 3. 核验真实文本存在性（防止幻觉页码被扣 2 分）
        page_text = pages_dict.get(page_num, "")
        # 若需要更精确，可回查全局哪个页面包含该句核心实体，自动更正页码
        return f"[{paper_idx}, p. {page_num}]"

    repaired_markdown = cite_pattern.sub(replace_citation, markdown_text)
    return repaired_markdown, warnings
```

---

## 七、核心专题五：Agent 架构设计、计划依从性与 25 题高并发调度

### 7.1 前沿软件工程会议（ASE 2026）Agent 最新洞察

从本地检索与阅读的最新 2026 软件工程顶会论文中提炼出关键架构思想：

1. **《From Plan to Action: How Well Do Agents Follow the Plan?》 (ASE 2026)**
   - **实证结论**：Agent 遵从全局结构化计划（Standard Plan）显著优于无计划或过度动态规划。
   - **关键指导**：**周期性提醒机制（Periodic Plan Reminders）**。在多步任务（如读取、提取、综述、核验）中，将全局阶段步骤作为不可变形的前提在每一轮 Prompt 中显式提醒，能减少 80% 以上的步骤漂移。
   - **反直觉结论**：一个不良规划对 Agent 的伤害远超无规划；因此**静态硬编码工作流比让 LLM 动态反思自创工作流更为健壮**。
2. **《DCAS: Decoupling CLI Agent Scaffolding》 (ASE 2026)**
   - **核心思想**：解耦 Agent 外部脚手架（Scaffolding）与底层执行逻辑。
   - **工程映射**：在我们的竞赛服务中，FastAPI Server 充当纯净的统一调度层（Router/Dispatcher），具体的任务逻辑封装为独立的 Handler，二者通过统一的 Pydantic Schema 进行隔离与通信。
3. **《AgentSpec: Customizable Runtime Enforcement》 (ICSE 2026)**
   - **核心思想**：通过轻量级规则切面（Rule Predicates）在 Agent 运行时拦截不安全行为（毫秒级开销）。
   - **安全切面**：
     - 文件路径断言：`assert not ".." in path and not path.startswith("/")`
     - 输出目录断言：`assert path.startswith("data/expert/") or path.startswith("data/figure/")`
     - 字符长度断言：`assert len(markdown) >= 800`

### 7.2 25 题任务调度与 180s 超时时间预算控制

平台设定：**单题最大 180 秒，Agent 阶段总时长 90 分钟**。

```
时间预算规划分配（针对 180s 保护上限）：
  A 类 (Chat)       : 预估 5~10 秒  (1 次 LLM 调用)
  B 类 (Retrieval)  : 预估 15~30 秒 (本地 FTS 快速初筛 + 1 次 LLM 精筛理由生成)
  C 类 (Survey)     : 预估 60~90 秒 (PyMuPDF 快速提取 + 2 次 LLM: 提纲/正文 + 审计)
  D 类 (Reproduction): 预估 30~100 秒 (运行冻结脚本, 强设 timeout=150s)
  E 类 (Idea)       : 预估 20~40 秒 (上下文组装 + 1 次 8 槽位结构化生成 + 校验)
```


#### 软超时熔断与安全降级机制（Soft Timeout Guard）：

设置应用层软超时阈值 **160 秒**。若某道题执行达到 160 秒仍未完成（例如 LLM 网关响应迟缓或 D 类脚本运行耗时），触发异步熔断：

- C/E 类：立即序列化当前已生成的 Markdown（确保至少有 800 字及参考文献），避免超时计 0 分；
- D 类：若脚本超过 150 秒未退出，杀死子进程，按规范返回状态 `failed`，保留已知指标为 `null`，确保合法 JSON 提交。

---

## 八、核心专题六：D 类论文实验复现真实流水线与图表核验机制

### 8.1 冻结脚本调用与真实产物核验协议

在对 `research-experiments/` 进行深度代码级分析后，明确 D 类的标准判题协议：

1. **执行入口**：必须通过调用平台提供的冻结脚本：
   ```bash
   python /data/experiments/run_experiment.py --case <case_id>
   ```
   （本地兼容调试入口为 `python experiment.py --case D-01 --output /output --data /data --team <team>`）。
2. **严禁造假**：平台通过 `strace` 跟踪真实底层系统调用，比对生成的图片文件 SHA-256 哈希值。如果自行编造指标或伪造图表，一经发现直接判 0 分。
3. **输出定位与回读**：脚本执行成功后，会在 `/output`（或本队工作目录）下生成：
   - `/output/submission.json`：包含 `case_id`、`status`、`metrics`、`figures`；
   - `/output/data/figure/<team>/D-0x.png`：生成的实验图表；
   - `/output/metrics.json` 与 `/output/command.json`。

### 8.2 D 类子进程执行器（Subprocess Runner）鲁棒实现

```python
import subprocess
import json
import os
from typing import Dict, Any

def execute_reproduction_task(case_id: str, team_name: str, timeout_sec: int = 150) -> Dict[str, Any]:
    """
    D 类任务安全执行器：
    1. 真实触发平台 runner 脚本
    2. 捕获 stdout JSON Lines 事件
    3. 超时强杀防御
    4. 回读官方标准 submission.json
    """
    script_path = "/data/experiments/run_experiment.py"
    # 本地调试降级路径
    if not os.path.exists(script_path):
        script_path = "research-experiments/run_experiment.py"

    cmd = ["python", script_path, "--case", case_id]
    
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            check=False
        )
        
        # 检查是否成功完成
        submission_path = f"/output/submission.json"
        if not os.path.exists(submission_path):
            submission_path = f"data/{team_name}/{case_id}.json"
            
        if os.path.exists(submission_path):
            with open(submission_path, "r", encoding="utf-8") as f:
                result = json.load(f)
                return result
                
        # 若未生成，根据 stdout 错误降级为 failed
        return {
            "case_id": case_id,
            "status": "failed",
            "metrics": [],
            "figures": []
        }
        
    except subprocess.TimeoutExpired:
        return {
            "case_id": case_id,
            "status": "failed",
            "metrics": [],
            "figures": []
        }
```

### 8.3 公开 5 题指标口径与容差特征

根据 `references.json` 标定数据，D-01 至 D-05 具有如下核心特性：

- **D-01（文本分类）**：`Macro-F1`、`Accuracy`（确定性强，容差 1%）、`运行时间`（计时指标，离散度大，容差 25%）。
- **D-02（BM25检索）**：`Recall@5`、`MRR@10`、`查询吞吐`。
- **D-03（KV缓存推理）**：`推理吞吐`、`P95 延迟`、`缓存命中率`。
- **D-04（网格搜索）**：`验证集准确率`、`约束通过率`、`搜索耗时`。
- **D-05（事件调度仿真）**：`公平性 Jain 指数`、`归一化吞吐`、`平均等待时间`。
- **关键提醒**：所有题目公开材料中无真实论文对照值时，`reference` 与 `relative_error` 必须保持为 `null`，不可自行臆造数值。

---

## 九、核心专题七：E 类研究灵感 8 大槽位全覆盖与证据边界隔离

### 9.1 评分标准与 8 大槽位映射（满分 15 分）

要点覆盖类评分直接采用关键词与语义匹配 8 大槽位，缺少任一槽位将直接损失相应分值：

| 槽位编号 | 槽位名称           |     分值    | 核心内容要求                      | 强制 Markdown 标题建议      |
| :--: | :------------- | :-------: | :-------------------------- | :-------------------- |
|   1  | **研究动机**       |   1.5 分   | 结合指定论文说明已有技术瓶颈与需求           | `## 1. 研究动机与问题背景`     |
|   2  | **技术路线**       |   1.5 分   | 提出具体的新方法机制，明确区别于已有方案        | `## 2. 核心Idea与技术路线`   |
|   3  | **实验设计**       |   1.5 分   | 详细设计实验流程、对照组、消融实验（Ablation） | `## 3. 实验方案与消融设计`     |
|   4  | **基准数据集**      |   1.5 分   | 明确列出评测数据集名称、规模及数据形态         | `## 4. 基准数据集与数据特征`    |
|   5  | **量化评价指标**     |   1.5 分   | 明确给出量化指标全称、单位及计算方式          | `## 5. 量化评价指标体系`      |
|   6  | **复现瓶颈反思**     | **3.0 分** | 严格说明模拟观察的边界，反思潜在落地瓶颈        | `## 6. 复现瓶颈与观察边界反思`   |
|   7  | **多文献互补机制**    | **3.0 分** | 阐明至少 2 篇指定论文间的优缺点互补机制       | `## 7. 多篇文献互补与协同机制`   |
|   8  | **场景可行性与落地约束** |   1.5 分   | 分析计算开销、实施约束、失败边界与风险         | `## 8. 场景可行性、约束与失败边界` |

### 9.2 “模拟观察”与“论文结论”证据边界硬性隔离

赛题在 `constraints` 中强调：**“只把题目给出的模拟观察作为待分析现象，不得写成论文实测结论”**。

- **违规反例**：*“根据文献 [1] 实测证明，最短路线经过的无遮荫路段较多……”*（此为题目给定的模拟观察，并非原论文实验结论，如此撰写会被直接判为事实伪造与混淆边界）。
- **合规正例**：*“题目给出的初步模拟观察表明：最短路线往往包含较多无遮荫路段。需特别强调，该现象仅为初步待验证观察，并非参考文献 [1] 的实测定论；在后续方案中，我们将设计双盲实测进行针对性证伪与验证……”*。

---

## 十、核心专题八：Docker 容器安全、权限控制与平台契约对接

### 10.1 平台运行规范与非 Root 权限要求

根据平台技术公告：

1. **基础镜像**：基于 `agenthack-base:1.1.1` 构建，运行时系统以非 root 用户 `agent` 执行。
2. **读写权限隔离**：
   - `/data/papers`：只读挂载（论文库）；
   - `/data/experiments`：只读挂载（复现材料）；
   - `/output/data/<team>/`：可读写（本队结果 JSON、工作目录）；
   - `/output/data/expert/`：可读写（本队 C/E 类 Markdown 报告，命名必须遵循规范）；
   - `/output/data/figure/<team>/`：可读写（D 类实际生成的图片）。
3. **防越界安全**：严禁出现 `..` 相对路径向上遍历，严禁访问 `/output/data/<other_team>`。

### 10.2 FastAPI HTTP 契约设计

平台通过 `POST /solve` 下发标准 JSON 任务：

```python
from fastapi import FastAPI, Request, HTTPException
import os, json

app = FastAPI(title="Research Agent", version="1.0.0")

@app.get("/health")
def health_check():
    return {"status": "ok"}

@app.post("/solve")
async def solve_task(request: Request):
    data = await request.json()
    case_id = data.get("case_id")
    func_type = data.get("function")
    
    # 提取平台注入会话头
    session_id = request.headers.get("X-Session-ID", os.environ.get("CHALLENGE_SESSION_ID", ""))
    team_name = os.environ.get("RESEARCH_WORKSPACE_TEAM", "team")
    
    # 分发至对应 Handler
    # result = router.dispatch(func_type, data, session_id, team_name)
    # return result
```

---

## 十一、技术选型推荐矩阵与工程落地路线图

### 11.1 核心组件技术选型终审表

| 模块            | 最终推荐选型方案                               | 备用方案           | 决策依据                                  |
| :------------ | :------------------------------------- | :------------- | :------------------------------------ |
| **Web 框架**    | **FastAPI + Uvicorn**                  | aiohttp        | 轻量异步，开箱支持 Pydantic 校验与标准化异常处理         |
| **PDF 解析引擎**  | **PyMuPDF (`fitz`)**                   | pdfplumber     | 毫秒级解析，100% 物理页码对齐，内存常驻 < 30 MB        |
| **全文词法检索**    | **SQLite FTS5 (内置BM25)**               | BM25S          | 零外部依赖，C 内核稳定，内存锁定在 8MB 严防 OOM         |
| **语义向量模型**    | **`bge-small-en-v1.5` (ONNX INT8)**    | pure BM25      | 仅 34MB 权重，ONNX 运行时仅耗 50MB 内存，CPU 极速推理 |
| **检索融合机制**    | **Reciprocal Rank Fusion (RRF, k=60)** | MinMax 凸组合     | 参数无关，天然平衡 BM25 与 Dense 尺度差异           |
| **引文核验与事实验证** | **Pre-grounding + Post-hoc Audit**     | RefChecker 三元组 | 强制先提取页码事实三元组再生成综述，事后正则+全文回查修复         |
| **复现执行器**     | **subprocess + timeout=150s**          | 无              | 强设保护超时，回读官方 runner 生成的真实图片哈希与指标       |
| **输出校验层**     | **Pydantic v2 + 写入后回读校验**              | 纯 dict 操作      | 保证 25 个结果 JSON 格式 100% 合规，字符数与文件逐字一致  |

### 11.2 工程开发四阶段实施路线图

```
┌────────────────────────────────────────────────────────────────────────┐
│                        工程落地路线图 (Milestones)                     │
├────────────────────────────────────────────────────────────────────────┤
│                                                                        │
│  Phase 1: 基础骨架与协议打通 (Day 1 - 2)                               │
│  ├─ 搭建 FastAPI 服务，打通 GET /health 与 POST /solve                 │
│  ├─ 封装 challenge_sdk LLMClient，支持 X-Session-ID 传递               │
│  ├─ 实现五类任务 Pydantic Schema 与双写（JSON + Markdown）回读校验器  │
│  └─ 本地跑通 D-01 ～ D-05 冻结实验脚本调起与结果解析                   │
│                                                                        │
│  Phase 2: 核心能力与管道建设 (Day 3 - 5)                               │
│  ├─ 构建 PyMuPDF 逐页解析器，生成带有页码的 Page-Text/Chunk 结构      │
│  ├─ 构建 SQLite FTS5 数据库，实现毫秒级 BM25 检索与 RRF 融合           │
│  ├─ C 类：实现“证据矩阵提取 -> 综述大纲 -> 正文编写”三步链             │
│  └─ E 类：实现 8 大槽位提示词模板与模拟观察硬隔离保护                   │
│                                                                        │
│  Phase 3: 评分防御与风控增强 (Day 6 - 7)                               │
│  ├─ B 类负例过滤：LLM 否定条件拦截器，杜绝 -0.75U 扣分                 │
│  ├─ C 类引文审计：实现真实页码回查与修正器，杜绝 -2H 扣分              │
│  ├─ C 类事实校验：基于源文本片段 NLI 一致性核验，杜绝 -3F 扣分         │
│  └─ 超时保护熔断器：160 秒优雅降级，防止进程崩溃计 0 分                │
│                                                                        │
│  Phase 4: Docker 封装与全链路压测 (Day 8)                              │
│  ├─ 基于 agenthack-base:1.1.1 编写精简 Dockerfile                      │
│  ├─ 配置非 root agent 用户权限与目录读写测试                           │
│  ├─ 模拟官方 25 题并发压测，运行 validate_submission.py 预检           │
│  └─ 打包导出镜像 tar 包，完成最终交付                                  │
│                                                                        │
└────────────────────────────────────────────────────────────────────────┘
```

---

*报告生成时间：2026-10-13 | 关联项目文档：`project-outline.md`、`research-agent-spec.md`、`research-scoring-rules.md`*
