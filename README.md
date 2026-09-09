# Deep Research Agent 使用与部署说明

这个项目是一个基于 **Notion + Deep Research Agent + DeepSeek + Tavily** 的自动研究工作流。

你可以在 Notion Database 里创建一个研究任务，然后运行 `notion_worker.py`，让 Agent 自动完成研究、生成学习笔记，并写回 Notion。

---

## 1. 项目整体流程

```text
Notion Database
    ↓
读取 Status = Todo 的任务
    ↓
notion_worker.py 构造完整研究 Prompt
    ↓
调用 deep_research.py 里的 run_deep_research_with_sources()
    ↓
┌── 阶段 1：研究 ─────────────────────────┐
│ Deep Agent + Tavily 搜索、抓取网页      │
│ 从 ToolMessage 里收割证据和来源 URL     │
└─────────────────────────────────────────┘
    ↓
┌── 阶段 2：写作 ─────────────────────────┐
│ 无工具的 DeepSeek 调用                  │
│ 把证据写成完整 Markdown 学习笔记        │
└─────────────────────────────────────────┘
    ↓
写回 Notion 页面正文
    ↓
更新 Result Summary / Resource URL / Status
```

### 为什么要分成两个阶段

`deepagents` 的 `create_deep_agent()` 会**无条件**给 Agent 装上一套文件工具：

```text
ls, read_file, write_file, edit_file, glob, grep, execute, task, write_todos
```

没有参数可以关掉它们。这带来一个具体后果：Agent 完全可以把笔记 `write_file` 到
`/home/user/notes/xxx.md`，然后在最后一条消息里只回一句「已保存」。如果流水线只读
最后一条消息，拿到的就是这句话，而不是笔记。

所以这里把研究和写作拆开：

| 阶段 | 用什么 | 为什么 |
|---|---|---|
| 研究 | Deep Agent（带文件工具） | 证据从 `ToolMessage` 里直接收割，不依赖 Agent 最后说什么，它爱存文件就存 |
| 写作 | 纯 `model.invoke()`，**没有任何工具** | 没有工具就无法「保存到文件并汇报成功」，笔记就是这次调用的直接输出 |

这比在 Prompt 里反复写「不要保存文件」可靠，因为它把问题从「说服模型」变成了
「模型没有这个能力」。

---

## 2. 项目文件结构

```text
deep-research-agent/
├── main.py                 # CLI 入口，交互式提问
├── deep_research.py        # 研究 + 写作两阶段流水线
├── notion_worker.py        # Notion 自动任务调度脚本
├── notion_tasks.py         # Notion API 读写 + Markdown 转换
├── tools.py                # Tavily search、网页抓取等工具
├── config.py               # 读取 .env，集中管理配置
├── .env                    # API Keys，本地保存，不要上传 GitHub
├── .env.example            # 配置模板，可以安全提交
├── requirements.txt        # Python 依赖
├── pyproject.toml          # 项目元数据与依赖
├── test_*.py               # 手工冒烟测试脚本
└── .venv/                  # Python 虚拟环境
```

各文件职责：

| 文件 | 作用 |
|---|---|
| `main.py` | 命令行入口，调用流水线并打印笔记和来源 |
| `deep_research.py` | 研究阶段 Agent + 写作阶段调用，暴露 `run_deep_research(question)` 和 `run_deep_research_with_sources(question)` |
| `notion_worker.py` | 从 Notion 读取任务、调用流水线、写回结果 |
| `notion_tasks.py` | 封装 Notion 查询、更新、追加正文，以及 Markdown → Notion blocks 转换 |
| `tools.py` | Tavily 搜索工具、网页抓取工具 |
| `config.py` | 加载 `.env`，缺 key 时给出清晰报错 |
| `.env` | 保存 DeepSeek、Tavily、Notion API keys |

`deep_research.py` 里两个主要函数：

```python
run_deep_research(question) -> str
    # 返回完整 Markdown 笔记

run_deep_research_with_sources(question) -> tuple[str, list[str]]
    # 返回 (笔记, 研究阶段实际用到的来源 URL 列表)
```

---

## 2.1 Markdown 会被转换成什么 Notion block

`notion_tasks.markdown_to_notion_blocks()` 支持：

| Markdown | Notion block |
|---|---|
| `# / ## / ###` | heading_1 / heading_2 / heading_3 |
| `#### ` | heading_3（Notion 没有 heading_4） |
| `- ` `* ` `+ ` | bulleted_list_item |
| `1. ` `1) ` | numbered_list_item |
| `> ` | quote |
| `---` `***` | divider |
| 三反引号代码块 | code（带语言标注） |
| 标准表格（带 `\| --- \|` 分隔行） | table + table_row（真正的 Notion 表格） |
| `**粗体**` `*斜体*` `` `代码` `` `[文字](url)` | rich_text 的 annotations 和 link |

两个容易踩的 Notion 限制已经处理好：

```text
单个 rich_text 最多 2000 字符  → 超长段落自动分块，不会被截断
单次 append 最多 100 个 block  → 长笔记自动分批写入
```

所以让模型输出标准 Markdown 就行，不需要为 Notion 做特殊适配。

---

## 3. Notion Database 需要的字段

建议 Notion Database 至少包含以下属性：

| 属性名 | 类型 | 用途 |
|---|---|---|
| `Question` | Title | 研究问题 |
| `Status` | Status | `Todo` / `Running` / `Done` / `Error` |
| `Priority` | Select | High / Medium / Low，可选 |
| `Topic` | Multi-select | Theory / Coding Skill / Tool 等 |
| `Difficulty` | Select | Beginner / Medium / Advanced |
| `Source URL` | URL | 用户指定的主要研究链接，可选 |
| `Output Language` | Select | Chinese / English |
| `Result Summary` | Text / Rich text | 一句话总结 |
| `Error Message` | Text / Rich text | 报错信息 |
| `Resource URL` | URL | Agent 搜索到的主要参考链接 |
| `Resource URLs` | Text / Rich text | 多个参考链接，每行一个 |

`Status` 至少需要这些选项：

```text
Todo
Running
Done
Error
```

---

## 4. `.env` 配置

项目里有一份模板 `.env.example`，复制一份改名即可：

```powershell
copy .env.example .env
```

然后填入真实值：

```env
DEEPSEEK_API_KEY=你的DeepSeek_API_Key
TAVILY_API_KEY=你的Tavily_API_Key
NOTION_API_KEY=你的Notion_Integration_Token
NOTION_TASK_DATABASE_ID=你的Notion_Data_Source_ID
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
```

哪些是必需的：

| 变量 | 必需性 |
|---|---|
| `DEEPSEEK_API_KEY` | 必需，缺失时 import `config.py` 就会报错 |
| `TAVILY_API_KEY` | 必需 |
| `NOTION_API_KEY` | 只有用 `notion_worker.py` 时才需要 |
| `NOTION_TASK_DATABASE_ID` | 只有用 `notion_worker.py` 时才需要 |
| `NOTION_PARENT_PAGE_ID` | 可选，只有 `tools.save_note_to_notion()` 会用 |
| `DEEPSEEK_MODEL` / `DEEPSEEK_BASE_URL` | 可选，有默认值 |

Notion 相关的变量是惰性读取的，所以只想用 `main.py` 做纯研究时，不配 Notion 也能跑。

注意：

```text
.env 不要上传 GitHub
不要在等号两边加空格
不要使用中文冒号
不要把 key 发给别人
```

正确：

```env
TAVILY_API_KEY=tvly-xxxx
```

错误：

```env
TAVILY_API_KEY = tvly-xxxx
TAVILY_API_KEY：tvly-xxxx
```

---

## 5. 本地启动步骤：Windows PowerShell

进入项目目录：

```powershell
cd C:\Users\14457\deep-research-agent\deep-research-agent
```

激活虚拟环境：

```powershell
.\.venv\Scripts\Activate.ps1
```

确认当前目录里有关键文件：

```powershell
dir
```

应该能看到：

```text
deep_research.py
notion_worker.py
notion_tasks.py
tools.py
.env
```

安装依赖：

```powershell
python -m pip install -r requirements.txt
```

检查 `.env` 是否生效：

```powershell
python -c "from dotenv import load_dotenv; load_dotenv(); import os; print('DEEPSEEK:', bool(os.getenv('DEEPSEEK_API_KEY'))); print('TAVILY:', bool(os.getenv('TAVILY_API_KEY'))); print('NOTION:', bool(os.getenv('NOTION_API_KEY'))); print('DATABASE:', bool(os.getenv('NOTION_TASK_DATABASE_ID')))"
```

期望输出：

```text
DEEPSEEK: True
TAVILY: True
NOTION: True
DATABASE: True
```

---

## 6. 测试 Notion API 是否可用

运行：

```powershell
python -c "from dotenv import load_dotenv; load_dotenv(); from notion_client import Client; import os; notion=Client(auth=os.environ['NOTION_API_KEY']); print(notion.users.me())"
```

如果成功，说明 Notion API key 和网络基本可用。

如果报错：

```text
SSL: UNEXPECTED_EOF_WHILE_READING
```

通常是代理或网络问题。先检查代理：

```powershell
python -c "import os; print('HTTP_PROXY=', os.environ.get('HTTP_PROXY')); print('HTTPS_PROXY=', os.environ.get('HTTPS_PROXY')); print('http_proxy=', os.environ.get('http_proxy')); print('https_proxy=', os.environ.get('https_proxy'))"
```

清除代理：

```powershell
Remove-Item Env:HTTP_PROXY -ErrorAction SilentlyContinue
Remove-Item Env:HTTPS_PROXY -ErrorAction SilentlyContinue
Remove-Item Env:http_proxy -ErrorAction SilentlyContinue
Remove-Item Env:https_proxy -ErrorAction SilentlyContinue
```

如果必须走代理，例如 Clash 端口是 7890：

```powershell
$env:HTTP_PROXY="http://127.0.0.1:7890"
$env:HTTPS_PROXY="http://127.0.0.1:7890"
```

---

## 7. 测试 Deep Research Agent 本体

运行：

```powershell
python main.py
```

输入一个问题，例如：

```text
Explain what API keys are from theory and engineering practice.
```

如果能输出完整 Markdown 学习笔记，并在末尾列出 `=== Sources ===`，说明流水线基本可用。

`python deep_research.py` 效果相同，两个入口都可以。

一次完整运行大致的耗时和规模（供参考）：

```text
研究阶段  约 2-3 分钟，收集到数万字证据
写作阶段  约 1 分钟，产出 1.5-2 万字笔记
```

如果觉得太慢或太贵，调小 `deep_research.py` 里的：

```python
MAX_EVIDENCE_CHARS = 40000
```

---

## 8. 测试 Notion Worker

先在 Notion Database 里创建一条任务：

| Question | Status | Difficulty | Output Language |
|---|---|---|---|
| Explain what LangChain tools are | Todo | Beginner | Chinese |

然后运行（`--once` 表示只处理一条任务就退出，适合测试）：

```powershell
python notion_worker.py --once
```

正常运行日志大致是：

```text
Notion worker running a single pass.
============================================================
Found task:
Page ID: ...
Question: Explain what LangChain tools are
Topic: []
Difficulty: Beginner
Source URL:
============================================================
Updating status to Running...
Topic is empty. Classifying topic with LLM...
Detected topics: ['Theory', 'Tool / Framework']
Building full research prompt...
Running deep research pipeline...
Cleaning model output...
Updating Resource URLs (137 found, writing up to 25)...
Appending result to Notion page...
Generating Result Summary...
Updating status to Done...
Task completed successfully.
```

运行成功后，Notion 里应该看到：

```text
Status → Done
页面正文 → 完整学习笔记
Result Summary → 一句话总结
Resource URL / Resource URLs → 参考链接
```

---

## 9. `notion_worker.py` 的两种运行模式

两种模式都由命令行参数控制，**不需要改代码**。

### 9.1 开发测试模式：只运行一次

适合本地测试。

```powershell
python notion_worker.py --once
```

只处理一条 `Status = Todo` 的任务，处理完就退出。

---

### 9.2 长期运行模式：循环检查 Notion

适合部署到服务器。

```powershell
python notion_worker.py
```

轮询间隔：

```python
POLL_INTERVAL_SECONDS = 60
```

循环的行为：

```text
队列里还有任务  → 立刻处理下一条，不等待（积压能快速清空）
队列为空        → sleep 60 秒再查
单条任务出错    → 标记成 Error，继续处理下一条，不会退出
Ctrl + C        → 干净退出
```

---

## 10. Worker 调用 Agent 的核心逻辑

`notion_worker.py` 里最核心的是：

```python
full_question = build_question_from_task(task)
result, research_urls = run_deep_research_with_sources(full_question)
result = clean_agent_output(result)
validate_result(result)
update_resource_urls(page_id, urls[:MAX_RESOURCE_URLS])
append_result_to_task_page(page_id, result)
summary = summarize_result_one_sentence(result, task.get("output_language", "Chinese"))
update_result_summary(page_id, summary)
update_task_status(page_id, "Done")
```

含义：

```text
build_question_from_task()
    把 Notion 里的 Question / Topic / Difficulty / Source URL 组合成完整 Prompt

run_deep_research_with_sources()
    跑研究 + 写作两阶段，返回 (笔记, 研究阶段真实用到的来源 URL)

clean_agent_output()
    清理 “Now let me compile...”“好的，” 等行首元话术，
    并丢掉 H1 标题之前的所有闲聊

validate_result()
    确认结果确实是笔记正文：够长、以 # 开头、不含虚拟文件路径
    不满足就抛错，任务标记成 Error

update_resource_urls()
    写入来源链接，最多 MAX_RESOURCE_URLS 条

append_result_to_task_page()
    把完整 Markdown 正文写入 Notion 页面

summarize_result_one_sentence()
    生成一句话 Result Summary
    这一步失败不会让整个任务失败，因为正文已经写进去了

update_task_status()
    把任务状态改成 Done 或 Error
```

---

## 11. 部署到阿里云 ECS：手动运行

整个流程在服务器上跑，**本地电脑不参与、可以关机**：

```text
手机 Notion 新建任务 (Status = Todo)
        ↓
ECS 上常驻的 notion_worker.py 每 60 秒查一次 Notion API
        ↓
ECS 自己调用 DeepSeek + Tavily 完成研究
        ↓
写回 Notion 页面正文
        ↓
手机刷新 Notion 就能看到笔记
```

### 11.1 登录 ECS

```bash
ssh root@你的服务器公网IP
```

公网 IP 在阿里云控制台 → 云服务器 ECS → 实例列表里能看到。

登录后命令提示符会显示 `root@iZxxxxx:~#`，`@` 前面就是**当前用户名**（通常是 `root`，有些镜像是 `ecs-user`）。后面的部署脚本会自动读取它，你不需要记。

### 11.2 安装 git 和 uv

```bash
sudo apt update
sudo apt install -y git curl
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.bashrc
```

**为什么用 uv 而不是 apt 装 Python**：本项目要求 Python 3.13，而 Ubuntu 22.04 自带 3.10、24.04 自带 3.12，`apt` 装不到 3.13。uv 会自动下载并管理正确的 Python 版本，还能按 `uv.lock` 精确还原依赖，和你本地环境完全一致。

验证：

```bash
uv --version
```

### 11.3 拉取项目

```bash
git clone https://github.com/Unknownhalfcold/deep-research-agent.git
cd deep-research-agent
```

现在你所在的这个目录，就是我说的**项目路径**（用 `pwd` 可以打印出来，比如 `/root/deep-research-agent`）。同样，部署脚本会自动检测，你不用手动填。

### 11.4 创建环境并安装依赖

```bash
uv venv --python 3.13
uv sync
```

uv 会自己下载 Python 3.13，在 `.venv/` 里建好环境并装好全部依赖。

### 11.5 创建 `.env`

`.env` **不在 Git 里**（里面是 API key，绝不能提交），所以 clone 下来是没有的，必须在服务器上重新建一份：

```bash
cp .env.example .env
nano .env
```

填入真实的 key：

```env
DEEPSEEK_API_KEY=你的key
TAVILY_API_KEY=你的key
NOTION_API_KEY=你的key
NOTION_TASK_DATABASE_ID=你的data source id
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
```

nano 里保存退出：`Ctrl + O` → 回车 → `Ctrl + X`。

### 11.6 先手动跑一次

在交给 systemd 之前，**一定先手动确认能跑通**。否则服务会在后台不断重启失败，日志很难看。

先在手机或电脑的 Notion 里建一条 `Status = Todo` 的任务，然后：

```bash
.venv/bin/python notion_worker.py --once
```

`--once` 表示处理一条任务就退出。看到 `Task completed successfully.` 并且 Notion 页面里出现了笔记，就说明成功了。

---

## 12. 部署到阿里云 ECS：systemd 后台运行

确认第 11.6 步手动运行成功后，再配置后台服务。

systemd 是 Linux 的服务管理器。把 worker 交给它之后，进程会开机自启、崩溃自动重启、你退出 SSH 也不会被杀掉。

### 12.1 一条命令安装

项目里带了部署脚本，**它会自动检测当前用户名和项目路径**，不需要你手动改任何配置：

```bash
bash deploy/install_service.sh
```

脚本做的事：

```text
1. 检查 .venv 和 .env 是否存在，缺了就明确报错并告诉你怎么补
2. 检查 .env 里的 key 能否正常读取
3. 用检测到的用户名和路径生成 /etc/systemd/system/notion-agent.service
4. daemon-reload、设置开机自启、启动服务
5. 打印服务状态
```

看到 `Active: active (running)` 就成功了。

注意服务用的是**轮询模式**（`ExecStart` 不带 `--once`），会一直运行；带了 `--once` 的话跑一次就退出，systemd 会不停重启它。

### 12.2 日常运维命令

查看实时日志（最常用，`Ctrl + C` 退出查看，不影响服务运行）：

```bash
journalctl -u notion-agent -f
```

查看状态：

```bash
sudo systemctl status notion-agent
```

改完代码后重启：

```bash
git pull
sudo systemctl restart notion-agent
```

停止 / 彻底关闭开机自启：

```bash
sudo systemctl stop notion-agent
sudo systemctl disable --now notion-agent
```

### 12.3 服务起不来时怎么排查

先看日志，**报错原因一定在里面**：

```bash
journalctl -u notion-agent -n 50 --no-pager
```

常见原因：

| 日志里的现象 | 原因 | 解决 |
|---|---|---|
| `RuntimeError: ... is not set` | `.env` 没建或 key 填错 | 回到 11.5 |
| `No such file or directory: .venv/bin/python` | 虚拟环境没建好 | 回到 11.4 |
| 不停 `Started` / `Failed` 循环 | 启动就崩，被 `Restart=always` 反复拉起 | 先 `sudo systemctl stop notion-agent`，再手动 `.venv/bin/python notion_worker.py --once` 看完整报错 |
| `SSL: UNEXPECTED_EOF_WHILE_READING` | 服务器网络到 Notion/DeepSeek 不通 | 见 13.4，考虑换香港/新加坡地域 |

---

## 13. 常见报错与解决方式

### 13.1 `No module named notion_tasks`

原因：Terminal 当前目录不对。

解决：

```powershell
cd C:\Users\14457\deep-research-agent\deep-research-agent
```

确认：

```powershell
dir
```

必须能看到：

```text
notion_tasks.py
notion_worker.py
```

---

### 13.2 `ImportError: cannot import name 'update_resource_urls'`

原因：`notion_tasks.py` 里没有顶层函数：

```python
def update_resource_urls(page_id: str, urls: list[str]) -> None:
```

检查：

```powershell
python -c "import notion_tasks; print(notion_tasks.__file__); print(hasattr(notion_tasks,'update_resource_urls'))"
```

期望输出：

```text
...
True
```

---

### 13.3 `KeyError: 'TAVILY_API_KEY'`

原因：`.env` 没有被加载，或者变量名写错。

解决：

1. 确认 `.env` 在项目根目录。
2. 确认代码顶部有：

```python
from dotenv import load_dotenv
load_dotenv()
```

3. 测试：

```powershell
python -c "from dotenv import load_dotenv; load_dotenv(); import os; print(bool(os.getenv('TAVILY_API_KEY')))"
```

---

### 13.4 `SSL: UNEXPECTED_EOF_WHILE_READING`

原因：访问 Notion / Tavily / 外部 API 时，HTTPS 连接被代理或网络中断。

解决方向：

```text
1. 清除错误代理
2. 设置正确代理端口
3. 更换网络
4. 部署到阿里云香港 / 新加坡 ECS
5. 给 Notion API 操作加 retry
```

---

### 13.5 Agent 返回 `/home/user/notes/...`

原因：`create_deep_agent()` 无条件给 Agent 装了 `write_file` 等文件工具，Agent 于是把
笔记写进虚拟文件系统，最后一条消息只回一句「已保存」。

想确认自己的 Agent 到底拿到了哪些工具，可以打印出来：

```powershell
python -c "from deep_research import get_research_agent; a=get_research_agent(); print(sorted(a.nodes['tools'].bound.tools_by_name.keys()))"
```

**这个问题已经通过两阶段架构解决**（见第 1 节）：写作阶段是一次没有任何工具的
`model.invoke()`，模型没有能力保存文件，所以笔记必然是调用的直接输出。

worker 里仍然保留了一道兜底检查：

```python
validate_result(result)
    # 太短        → 抛错
    # 不以 # 开头 → 抛错
    # 含 /home/user/notes → 抛错
```

如果这个报错重新出现，说明写作阶段的 Prompt 或模型出了问题，而不是文件工具的问题。

---

### 13.6 `UnicodeEncodeError: 'charmap' codec can't encode characters`

原因：Windows 控制台默认不是 UTF-8，`print()` 中文笔记时会崩。

`main.py`、`deep_research.py`、`notion_worker.py` 里都已经加了：

```python
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
```

如果在别的脚本里还遇到，可以在运行前设置环境变量：

```powershell
$env:PYTHONIOENCODING="utf-8"
```

---

## 14. 推荐开发顺序

```text
1. 本地 deep_research.py 能单独运行
2. 本地 notion_worker.py 能处理一条 Todo
3. Result Summary / Resource URL / 页面正文都能正确写入
4. 再上传到 GitHub
5. ECS 手动运行成功
6. 再配置 systemd 后台服务
7. 最后再考虑多任务、队列、并发和 Web UI
```

---

## 15. 安全注意事项

不要把这些内容上传 GitHub：

```text
.env
API Keys
Notion Integration Token
DeepSeek API Key
Tavily API Key
```

项目的 `.gitignore` 已经包含：

```gitignore
.env
.env.*
!.env.example
.venv
__pycache__/
*.py[oc]
```

提交前务必确认 `.env` 真的被忽略了。`.gitignore` 里写了不代表生效，比如文件已经被
`git add` 过就不再受忽略规则约束：

```powershell
git check-ignore -v .env
```

输出应该是（说明第 13 行的规则命中了它）：

```text
.gitignore:13:.env      .env
```

如果这条命令**没有任何输出**，说明 `.env` 没被忽略，一次 `git add .` 就会把 key
提交进 Git 历史。

如果 API key 曾经被提交或暴露，改代码没用——历史里还留着。必须去对应平台
（DeepSeek / Tavily / Notion）重新生成 key 并替换。

---

## 16. 最小使用方式总结

每天本地运行：

```powershell
cd C:\Users\14457\deep-research-agent\deep-research-agent
.\.venv\Scripts\Activate.ps1
python notion_worker.py
```

Notion 里新增任务：

```text
Question: 你想研究的问题
Status: Todo
Difficulty: Beginner / Medium / Advanced
Output Language: Chinese
```

Agent 会自动完成：

```text
读取任务 → 搜索资料 → 生成笔记 → 写回 Notion → 标记 Done
```
