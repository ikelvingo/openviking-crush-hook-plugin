# openviking-crush-hook-plugin

Hooks that connect [Crush](https://github.com/ikelvingo/openviking-crush-hook-plugin) sessions to an
[OpenViking](https://github.com/volcengine/openviking) memory server. Two small, non-blocking
Python hooks give your agent a persistent memory:

- **Capture** — syncs every session transcript into OpenViking and commits (archive + memory
  extraction) once enough new context accumulates.
- **Recall** — before answering, the agent queries OpenViking with the current question and gets
  relevant past memories injected into the session as `<openviking-context>`.

No credentials are stored in this repo. All identity (server URL, API key, actor peer id) is read
at runtime from environment variables or your local OpenViking config files.

---

## How it works

```
Crush session (crush.db)
        │
        ├── [PreToolUse: capture] ──► OpenViking API
        │      • diff transcript vs per-session watermark
        │      • upload new user/assistant turns  → POST /api/v1/sessions/<id>/messages
        │      • commit when pending tokens ≥ threshold → POST /api/v1/sessions/<id>/commit
        │
        └── [PreToolUse: recall] ──► OpenViking API
               • read latest user message from crush.db
               • POST /api/v1/search/recall (peer_scope: actor)
               • inject rendered result into the tool result context
```

| File | Role |
| --- | --- |
| `ov_common.py` | Shared library: identity resolution, HTTP client, per-session state, crush.db read access |
| `ov_capture.py` | Write path: upload transcript turns, auto-commit on threshold |
| `ov_recall.py` | Read path: recall relevant memories and inject them into the session |

Both hooks **never block** (short timeouts, silent failure) and never modify session data.

---

## Prerequisites

1. A running **OpenViking server** you can reach (self-hosted or hosted).
2. **OpenViking CLI** (`ov`) on your machine.
3. **Crush** with `PreToolUse` hooks enabled (any OS).

---

## 1. Install the OpenViking CLI

```bash
npm i -g @openviking/cli
```

Alternative (Python package):

```bash
pip install openviking --upgrade --force-reinstall
```

Verify and diagnose your setup:

```bash
ov doctor
```

`ov doctor` checks your config file, Python version, and embedding/VLM provider connectivity
without needing a running server.

---

## 2. Configure the CLI and server

The OpenViking server itself needs a config file (create `~/.openviking/ov.conf` per the
[OpenViking docs](https://github.com/volcengine/openviking), or point `OPENVIKING_CONFIG_FILE`
at it).

The CLI/client config can be generated interactively:

```bash
ov config
```

or written by hand. The hooks read the CLI config from (first match wins):

1. `OPENVIKING_CLI_CONFIG_FILE` env var
2. `~/.openviking/ovcli-crush.conf`
3. `~/.openviking/ovcli.conf`

Create `~/.openviking/ovcli-crush.conf` with placeholders replaced by **your** values:

```json
{
  "url": "https://your-openviking-server:8443",
  "api_key": "YOUR_API_KEY",
  "actor_peer_id": "crush"
}
```

> **Security note:** keep this file private (it holds your API key). It is never read by the
> hooks from any other location and is not part of this repository.

---

## 3. Install the hooks

Copy the three Python files into Crush's hook directory:

```bash
mkdir -p ~/.crush/hooks
cp ov_common.py ov_capture.py ov_recall.py ~/.crush/hooks/
```

The hooks use `CRUSH_SESSION_ID`, which Crush provides automatically to hook processes.

---

## 4. Register the hooks in crush.json

Edit `~/.config/crush/crush.json` and add the `hooks.PreToolUse` entries (use the absolute path
to your hooks directory):

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "",
        "command": "python /absolute/path/to/hooks/ov_capture.py",
        "timeout": 30
      },
      {
        "matcher": "^(bash|edit|write|multiedit|view|grep|glob|ls)$",
        "command": "python /absolute/path/to/hooks/ov_recall.py",
        "timeout": 15
      }
    ]
  }
}
```

Restart Crush. Done — capture and recall are now active.

---

## Configuration reference

Identity (env vars override the config file):

| Variable | Purpose |
| --- | --- |
| `OPENVIKING_URL` / `OPENVIKING_BASE_URL` | Server URL |
| `OPENVIKING_API_KEY` / `OPENVIKING_BEARER_TOKEN` | API key |
| `OPENVIKING_PEER_ID` | Actor peer id (defaults to `cli`) |
| `OPENVIKING_CLI_CONFIG_FILE` | Override the CLI config file path |

Capture tuning:

| Variable | Default | Meaning |
| --- | --- | --- |
| `OV_COMMIT_THRESHOLD` | `20000` | Commit when pending tokens reach this |
| `OV_COMMIT_KEEP_RECENT` | `20` | Turns kept unarchived on commit |
| `OV_CAPTURE_MAX_MSG` | `30000` | Max chars per captured message |

Recall tuning:

| Variable | Default | Meaning |
| --- | --- | --- |
| `OV_RECALL_MIN_INTERVAL` | `25` | Min seconds between recalls per session |
| `OV_RECALL_MAX_CHARS` | `1600` | Max chars of injected memory |
| `OV_RECALL_LIMIT` | `6` | Events/entities recalled per query |
| `OV_RECALL_MIN_QUERY_LEN` | `3` | Min query length to trigger recall |

---

## Behavior notes

- Recall fires only when a matching tool is about to run; if the agent answers without tools,
  no recall happens that turn.
- Each user question triggers recall at most once (dedup by query hash).
- Recalled memory is injected as context (`<openviking-context>`); the agent may use or ignore it.
- Explore memories manually with the `ov` CLI at any time.

## Troubleshooting

Hook activity is logged to `~/.crush/hooks/state/ov_hooks.log`. Per-session state (watermarks,
dedup hashes) lives in `~/.crush/hooks/state/*.json`.

- No recall happening → check `ov doctor`, confirm `url`/`api_key` in `ovcli-crush.conf`, and
  that the matcher includes a tool the agent actually calls.
- Capture not committing → lower `OV_COMMIT_THRESHOLD` or watch `pending_tokens` in the log.

---

## License

Apache-2.0-compatible hook scripts. OpenViking is Apache-2.0.

---

# openviking-crush-hook-plugin（中文）

将 [Crush](https://github.com/ikelvingo/openviking-crush-hook-plugin) 会话接入
[OpenViking](https://github.com/volcengine/openviking) 记忆服务器的两个小型 hook，为你的
agent 提供持久记忆：

- **Capture（写入）** — 将会话记录同步进 OpenViking，累积到阈值后自动 commit（归档 + 记忆提取）。
- **Recall（读取）** — 回答前按当前问题从 OpenViking 召回相关历史记忆，以 `<openviking-context>`
  注入会话。

本仓库**不含任何凭据**。服务器地址、API key、actor peer id 均在运行时从环境变量或本机
OpenViking 配置文件读取。

---

## 工作原理

```
Crush 会话 (crush.db)
        │
        ├── [PreToolUse: capture] ──► OpenViking API
        │      • 按会话水位线 diff 增量
        │      • 上传新增 user/assistant 轮次 → POST /api/v1/sessions/<id>/messages
        │      • pending tokens 达阈值时 commit → POST /api/v1/sessions/<id>/commit
        │
        └── [PreToolUse: recall] ──► OpenViking API
               • 从 crush.db 读取最新用户消息
               • POST /api/v1/search/recall（peer_scope: actor）
               • 把召回结果注入工具结果的 context 字段
```

| 文件 | 职责 |
| --- | --- |
| `ov_common.py` | 公共库：身份解析、HTTP 客户端、按会话的状态存储、crush.db 只读访问 |
| `ov_capture.py` | 写入路径：上传对话轮次，阈值自动 commit |
| `ov_recall.py` | 读取路径：召回相关记忆并注入会话 |

两个 hook **永不阻塞**（超时短、静默失败），也不修改会话数据。

---

## 前置条件

1. 一个可访问的 **OpenViking 服务器**（自托管或托管）。
2. 本机安装 **OpenViking CLI**（`ov`）。
3. 开启 `PreToolUse` hook 的 **Crush**（任意系统）。

---

## 1. 安装 OpenViking CLI

```bash
npm i -g @openviking/cli
```

或用 Python 包：

```bash
pip install openviking --upgrade --force-reinstall
```

验证与诊断：

```bash
ov doctor
```

`ov doctor` 会检查配置文件、Python 版本、embedding/VLM 服务连通性，无需服务器运行即可诊断。

---

## 2. 配置服务器与 CLI

服务器端配置文件为 `~/.openviking/ov.conf`（按
[OpenViking 文档](https://github.com/volcengine/openviking) 创建，或用
`OPENVIKING_CONFIG_FILE` 指向其他位置）。

CLI 配置可交互生成：

```bash
ov config
```

也可手写。hook 读取 CLI 配置的顺序（先命中者优先）：

1. 环境变量 `OPENVIKING_CLI_CONFIG_FILE`
2. `~/.openviking/ovcli-crush.conf`
3. `~/.openviking/ovcli.conf`

创建 `~/.openviking/ovcli-crush.conf`，把占位符替换为**你自己的**值：

```json
{
  "url": "https://your-openviking-server:8443",
  "api_key": "YOUR_API_KEY",
  "actor_peer_id": "crush"
}
```

> **安全提示：**该文件包含 API key，务必保持私有；hook 只从这里读取，且该文件不属于本仓库。

---

## 3. 安装 hook

把三个 Python 文件复制到 Crush 的 hook 目录：

```bash
mkdir -p ~/.crush/hooks
cp ov_common.py ov_capture.py ov_recall.py ~/.crush/hooks/
```

hook 使用 `CRUSH_SESSION_ID` 环境变量，Crush 会自动提供给 hook 进程。

---

## 4. 在 crush.json 中注册

编辑 `~/.config/crush/crush.json`，添加 `hooks.PreToolUse` 配置（路径改为你实际的绝对路径）：

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "",
        "command": "python /absolute/path/to/hooks/ov_capture.py",
        "timeout": 30
      },
      {
        "matcher": "^(bash|edit|write|multiedit|view|grep|glob|ls)$",
        "command": "python /absolute/path/to/hooks/ov_recall.py",
        "timeout": 15
      }
    ]
  }
}
```

重启 Crush 即生效。

---

## 配置参考

身份（环境变量优先于配置文件）：

| 变量 | 用途 |
| --- | --- |
| `OPENVIKING_URL` / `OPENVIKING_BASE_URL` | 服务器地址 |
| `OPENVIKING_API_KEY` / `OPENVIKING_BEARER_TOKEN` | API key |
| `OPENVIKING_PEER_ID` | actor peer id（默认 `cli`） |
| `OPENVIKING_CLI_CONFIG_FILE` | 指定 CLI 配置文件路径 |

Capture 调参：

| 变量 | 默认 | 含义 |
| --- | --- | --- |
| `OV_COMMIT_THRESHOLD` | `20000` | pending tokens 达到该值触发 commit |
| `OV_COMMIT_KEEP_RECENT` | `20` | commit 时保留未归档的轮次数 |
| `OV_CAPTURE_MAX_MSG` | `30000` | 单条消息最大捕获字符数 |

Recall 调参：

| 变量 | 默认 | 含义 |
| --- | --- | --- |
| `OV_RECALL_MIN_INTERVAL` | `25` | 每个会话两次召回最小间隔（秒） |
| `OV_RECALL_MAX_CHARS` | `1600` | 注入记忆的最大字符数 |
| `OV_RECALL_LIMIT` | `6` | 每次召回的事件/实体条数 |
| `OV_RECALL_MIN_QUERY_LEN` | `3` | 触发召回的最小查询长度 |

---

## 行为说明

- 召回只在匹配工具即将被调用时触发；若 agent 不调工具直接回答，该轮不召回。
- 每个用户问题最多召回一次（按 query hash 去重）。
- 召回内容以 `<openviking-context>` 上下文注入，agent 可用可忽略。
- 随时可用 `ov` CLI 手动检索记忆。

## 故障排查

hook 日志位于 `~/.crush/hooks/state/ov_hooks.log`，按会话的状态（水位线、去重 hash）在
`~/.crush/hooks/state/*.json`。

- 无召回 → 运行 `ov doctor`，检查 `ovcli-crush.conf` 的 `url`/`api_key`，确认 matcher 覆盖了
  agent 实际调用的工具。
- 不 commit → 调低 `OV_COMMIT_THRESHOLD`，或在日志中观察 `pending_tokens`。

---

## License

Apache-2.0 兼容 hook 脚本。OpenViking 为 Apache-2.0。
