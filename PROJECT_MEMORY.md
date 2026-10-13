# 科研助手 Agent 项目中枢记忆与状态看板 (PROJECT_MEMORY.md)

> **版本**：v1.0.0 (Living Document)  
> **最后更新**：2026-10-13  
> **当前 Git 分支**：`dev`  
> **GitHub 仓库**：`https://github.com/RuixinZhao/research-agent`  
> **平台环境基准**：`agenthack-base:1.1.1` (Linux/AMD64, 非 root `agent` 用户, Python 3.11.16)  
> **说明**：**本文档是所有开发会话（Sessions / Subagents）的唯一中枢真相源（Single Source of Truth）**。任何新会话或子 Agent 启动时，必须首先完整阅读本文档以对齐全局认知。

---

## 一、项目全局全景与核心契约

### 1.1 业务目标
参加 2026 全国高校 Agent 网络创新挑战赛·赛题 1「科研助手」，在 1024 MiB 内存受限容器内监听 `0.0.0.0:8080`，提供 `GET /health` 与 `POST /solve` 接口，自动完成 A/B/C/D/E 五类共 25 道评测任务。

### 1.2 评分项与分值优先级
```
总分 100 分 = 
  D 类 Reproduction (40分, 优先级 P0): 实验流水线 20 + 数据与图表 20
  C 类 Survey       (25分, 优先级 P1): 综述事实 15 (防 -3F) + 引文溯源 10 (防 -2H)
  B 类 Retrieval    (15分, 优先级 P1): 允许库检索 15 (防 -0.75U 误报)
  E 类 Idea         (15分, 优先级 P2): 8 大核心槽位覆盖 (防混淆模拟观察与实测结论)
  A 类 Chat         (5分,  优先级 P3): 科研专业解答 3 + 范围限定澄清追问 2
```

### 1.3 核心技术栈与内存铁律
1. **Web 框架**：FastAPI + Uvicorn 单进程异步（已内置于 base 镜像）。
2. **PDF 解析**：PyMuPDF (`fitz`)，物理页码对齐，按页流式处理后立即垃圾回收（GC），常驻内存 $< 30$MB。
3. **检索引擎**：SQLite FTS5 内置 BM25 算法，内存锁定 8MB，零外部网络服务依赖。
4. **LLM 客户端**：读取环境变量 `CHALLENGE_LLM_BASE_URL`，携带请求头 `X-Session-ID`。
5. **双写核验**：C 类与 E 类 Markdown 先落盘至 `data/expert/`，字符数 $\ge 800$，再赋值给 JSON 的 `markdown` 字段，逐字一致且回读校验。
6. **D 类真实性**：绝对禁止伪造 observed 指标与图表，必须由子进程主动调用 `/data/experiments/run_experiment.py`。
7. **依赖踩坑警示**：官方冻结环境为 `scikit-learn==1.5.2`，高版本 sklearn 废弃了 `multi_class` 参数，本地调试必须对齐依赖。

---

## 二、架构分工与多线程并发开发体系

当前会话作为**主干调度中枢（Main Orchestrator）**，负责代码骨架定义、公共基础设施接口、分支合并与进度统筹。具体的业务实现分发给 4 个独立的专业工作流（Sessions / Subagents）：

| 模块工作流 | 代号 / 分支 | 负责的核心文件 | 任务使命与考核指标 | 当前状态 |
| :--- | :--- | :--- | :--- | :---: |
| **主干调度 (Backbone)** | `dev` | `server.py`, `app/config.py`, `PROJECT_MEMORY.md` | 总体调度、HTTP 接口、安全路由与双写校验器 | **进行中** |
| **模块一：D 类复现与超时熔断** | `feat/repro-d` | `app/handlers/reproduction_handler.py`<br>`app/core/circuit_breaker.py` | 攻坚 40 分：双模调起官方 runner、捕获 JSON Lines、核验 PNG 图片、150s 优雅熔断 | **已完成** |
| **模块二：PDF 解析与 C/B 类文献** | `feat/rag-survey` | `app/core/pdf_parser.py`<br>`app/core/search_engine.py`<br>`app/handlers/survey_handler.py`<br>`app/handlers/retrieval_handler.py` | 攻坚 40 分：PyMuPDF 物理页对齐、SQLite FTS5 检索、三步综述链、防 -3F 事实错误与 -2H 幻觉、B 类负例拦截 | **已完成** |
| **模块三：A/E 类生成与 8 槽位** | `feat/chat-idea` | `app/handlers/chat_handler.py`<br>`app/handlers/idea_handler.py` | 攻坚 20 分：A 类限定性追问、E 类 8 大核心槽位结构化 Prompt、模拟观察边界硬隔离 | **已完成** |
| **模块四：Docker 打包与压测预检** | `feat/docker-bench` | `Dockerfile`<br>`scripts/run_mock_benchmark.py`<br>`scripts/validate_submission.py` | 交付闭环：基于 base:1.1.1 打包、非 root 权限测试、本地 25 题自动化 Mock 压测与提交预检 | **已完成** |

---

## 三、文件与目录路径契约（严格禁止改动）

```text
/data/papers/                          # [只读] 论文 PDF 存放路径
/data/experiments/                     # [只读] 官方复现脚本与数据
/output/data/<team>/dispatch.json      # [只读] 派题记录
/output/data/<team>/assigned/          # [只读] 输入题目 JSON
/output/data/<team>/<case_id>.json     # [可写] Agent 25 题输出 JSON
/output/data/expert/C-xx-综述-<team>.md # [可写] C 类综述 Markdown (>=800字)
/output/data/expert/E-xx-灵感Idea报告-<team>.md # [可写] E 类灵感 Markdown (>=800字)
/output/data/figure/<team>/D-xx.png    # [可写] D 类复现真实图表
```

---

## 四、各模块进度与合并日志

* **2026-10-13 20:00**：完成 4.8 万字顶会全景调研报告、全套开发落地手册编写，GitHub 仓库初次提交完成并推送。
* **2026-10-13 20:15**：确立主干-子模块多线程开发机制，创建 `PROJECT_MEMORY.md` 与多模块开发规范。
* **2026-10-13 20:25**：完成模块二开发：实现 `app/core/pdf_parser.py`（PyMuPDF 物理页对齐与 GC 回收）、`app/core/search_engine.py`（SQLite FTS5 内存检索引擎）、`app/handlers/retrieval_handler.py`（B 类负例拦截与宁缺毋滥机制，防 -0.75U）、`app/handlers/survey_handler.py`（C 类三步综述链、物理页码引文强校验与双写一致性，防 -3F/-2H），全套单元测试通过。
* **2026-10-13 20:30**：完成模块三开发：实现 `app/handlers/chat_handler.py`（A 类学术科研解答与范围限定追问、鲁棒 JSON 提取与落盘核验）与 `app/handlers/idea_handler.py`（E 类 8 大二级标题槽位严格对齐、模拟观察待验证与论文实测定论证据边界硬隔离保护、字数 $\ge 800$、双写回读核验），全套单测与 `/solve` 集成测试全部通过。
* **2026-10-13 20:35**：完成模块一开发：实现 `app/handlers/reproduction_handler.py` 与 `app/core/circuit_breaker.py`。实现线上/本地双模 runner 调度、捕获 JSON Lines 流、严格解析 `submission.json`、PNG 真实性核验（魔数、PIL 与元数据完整性）、超时与失败合规降级保护（指标置 null、不编造数值）。本地 D01~D05 离线测试及降级测试全部通过。
* **2026-10-13 20:40**：完成模块四开发：基于 `agenthack/base:1.1.1` 编写生产级 `Dockerfile`（非 root `agent` 用户、仅增补 `PyMuPDF==1.24.1` 极简依赖、配置 `.dockerignore` 保障构建轻量），完成 `scripts/validate_submission.py`（与根目录统一入口，严格校验 dispatch、25 题 Schema、C/E 双写一致性、D 类 PNG 魔数签名及安全沙箱防路径越界），完成 `scripts/run_mock_benchmark.py`（内置纯离线 Mock LLM Gateway，高保真模拟 25 题全集压测并联动自动预检）。全集 25 题 100% PASS，预检 100% PASS，全套单元测试与集成测试全部通过。



