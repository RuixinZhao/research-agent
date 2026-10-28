# 核心安全铁律：API 密钥与机密数据零泄露规范 (Mandatory Security Rule: Zero-Tolerance Secret Protection)

> **级别**：最高强制执行级别（P0 - Blocking Red Line）  
> **适用范围**：所有代码生成、重构、调试、测试脚本编写、Git 提交以及对话交互。

---

## 1. 绝对禁止红线 (Absolute Prohibitions)

1. **绝对禁止在代码中硬编码任何真实密钥**：
   - 严禁在任何 `.py`、`.js`、`.ts`、`.sh`、`.json`、`.yaml`、`.md`、Jupyter Notebook 或其他代码/脚本文件中写入任何真实的 API Key（例如以 `sk-`、`ghp_`、`AIza` 开头的密钥）、Token、密码、数据库连接串或私钥。
   - 无论是正式业务代码、临时测试脚本（如 `test_*.py`, `live_test_*.py`）、运行脚本还是单次 Debug 脚本，均**绝对禁止**哪怕“临时放一下测试”的行为。
   - 示例或文档中如需展示，**必须且仅能使用显式的伪占位符**（例如：`your_api_key_here`、`<DEEPSEEK_API_KEY>`）。

2. **绝对禁止将包含真实密钥的文件添加至 Git**：
   - 严禁对 `.env`、包含敏感凭证的文件执行 `git add` 或 `git commit`。
   - 任何提交前，必须确保 `.env`、`*.key`、`*.pem`、`credentials.json` 已写入 `.gitignore`。

---

## 2. 凭证管理与调用标准流程 (Mandatory Credential Workflow)

1. **统一环境变量读取**：
   - 代码中访问 API 密钥，必须且仅能通过环境变量或受 `.gitignore` 保护的本地 `.env` 文件读取：
     ```python
     import os
     from dotenv import load_dotenv

     load_dotenv()
     api_key = os.getenv("API_KEY")
     if not api_key:
         raise ValueError("缺少必要的环境变量 API_KEY，请在 .env 中配置，严禁硬编码！")
     ```
   - 绝对不可为 `os.getenv("API_KEY", "sk-xxx")` 设置包含真实密钥的 fallback 默认值。

2. **提交前安全自检 (Pre-Commit Guard)**：
   - 在执行 `git add` 或 `git commit` 之前，必须主动核对 `git diff --cached`，检查是否存在任何敏感字符串模式（如 `sk-[a-zA-Z0-9]{20,}`）。
   - 若发现敏感信息，必须立即终止提交并报警。

---

## 3. 密钥泄露紧急处置与应急响应 (Incident Response Protocol)

一旦发现任何密钥曾经以明文形式出现在代码、终端日志或 Git 提交历史中：

1. **第一优先级：立即提醒用户在云端后台吊销（Revoke / Delete）该 Key**！
   - 必须向用户明确解释：**仅在本地修改或删除代码无法消除已泄露的安全隐患**。
   - 只有在云端平台控制台（如 DeepSeek、OpenAI、GitHub 等）删除或禁用该 Key，才能在根本上阻断外部盗刷。
2. **第二优先级：重写 Git 历史并全量强制推送**：
   - 严禁使用普通 commit 进行“事后删除”。
   - 必须使用 `git-filter-repo` 等工具将该敏感凭据从整个 Git 提交历史中彻底擦除，并全量强制推送到远端（`git push --force --all` 及 `--tags`）。
3. **第三优先级：核查并加固仓库访问权限**：
   - 提醒用户将 Public 仓库设置为 Private，或确认 GitHub 边缘缓存已失效。
