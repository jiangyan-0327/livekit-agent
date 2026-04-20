# Echuu Agent Local README

这份文档用于本机调试 `echuu` 的 LiveKit Agent，覆盖以下内容：

- 安装本机 LiveKit
- 启动本机 LiveKit
- 启动本地 agent
- 生成测试 token
- 用本地测试页验证自动进房、文本回复和语音播报

## 1. 目录说明

当前 `agent` 目录里的关键文件：

- `src/agent.py`
  - LiveKit agent 入口
- `.env.local`
  - agent 的模型、TTS、STT 配置
- `test-client.html`
  - 本地测试页，用来连接本机 LiveKit 验证 agent
- `pyproject.toml`
  - Python 依赖定义

此外，项目根目录还保留了一个 `.env`，用于提供 LiveKit 连接信息。

当前代码会同时读取：

- 根目录 `.env`
- `agent/.env.local`

## 2. 环境前提

建议环境：

- Windows
- Python 3.10+
- `uv`
- 本机可运行的 LiveKit Server

先确认 `uv` 可用：

```powershell
uv --version
```

## 3. 安装本机 LiveKit

你可以使用 LiveKit 官方提供的二进制或 Docker 方式。  
本机调试最简单的目标是：让本地有一个可访问的 LiveKit Server，监听：

```text
ws://127.0.0.1:7880
```

### 3.1 最小本地配置

根目录 `.env` 里需要至少有这些值：

```env
LIVEKIT_URL=ws://127.0.0.1:7880
LIVEKIT_API_KEY=devkey
LIVEKIT_API_SECRET=secret
LIVEKIT_AGENT_NAME=echuu-voice-agent
```

这套值是本地开发用，不适合生产环境。

### 3.2 启动 LiveKit

只要你本机的 LiveKit 启动后，确认下面这个地址可用即可：

```text
ws://127.0.0.1:7880
```

如果你已经通过其他方式启动了本机 LiveKit，这一步不需要重复做。

## 4. 安装 agent 依赖

进入 `agent` 目录：

```powershell
cd D:\python\echuu-agent\agent
```

安装依赖：

```powershell
uv sync
```

## 5. 配置 agent 环境变量

`agent/.env.local` 里需要配置这些内容：

```env
LIVEKIT_AGENT_NAME=echuu-voice-agent

ECHUU_AGENT_STT_MODEL=nova-3
ECHUU_AGENT_TTS_MODEL=cartesia/sonic-3
ECHUU_AGENT_TTS_VOICE=9626c31c-bec5-4cca-baa8-f8ba9e84c8bc
ECHUU_AGENT_TTS_ENABLED=true

ZAI_API_KEY=your_zai_api_key
ECHUU_AGENT_LLM_MODEL=glm-5.1
ECHUU_AGENT_LLM_BASE_URL=https://open.bigmodel.cn/api/paas/v4/
ECHUU_AGENT_TTS_LANGUAGE=zh
ECHUU_AGENT_LLM_TEMPERATURE=0.7
ECHUU_AGENT_LLM_MAX_TOKENS=200

DEEPGRAM_API_KEY=your_deepgram_api_key
ECHUU_AGENT_STT_LANGUAGE=zh-CN
CARTESIA_API_KEY=your_cartesia_api_key
```

最重要的几个开关：

- `ECHUU_AGENT_TTS_ENABLED=true`
- `CARTESIA_API_KEY`
- `DEEPGRAM_API_KEY`
- `ZAI_API_KEY`

如果文本能回复但没有语音，优先检查这几项。

## 6. 启动 agent

进入 `agent` 目录：

```powershell
cd D:\python\echuu-agent\agent
```

开发模式启动：

```powershell
uv run python src\agent.py dev
```

如果启动正常，终端会保持运行并等待 LiveKit 调度 agent 进房。

## 7. 启动本地测试页

为了验证本机 LiveKit，不要使用 `meet.livekit.io`。  
原因是它是公网 HTTPS 页面，而你的本机 LiveKit 是：

```text
ws://127.0.0.1:7880
```

更稳的做法是直接起本地静态服务。

在 `agent` 目录执行：

```powershell
cd D:\python\echuu-agent\agent
python -m http.server 8010
```

然后浏览器打开：

```text
http://127.0.0.1:8010/test-client.html
```

## 8. 生成测试 token

### 8.1 重要说明

如果要验证自动进房，请使用：

- 全新房间名
- 带 `agent dispatch` 的 token

不要反复复用同一个房间名。  
本地验证里已经确认过：旧房间复用时，token 里的 `roomConfig.agents` 不一定会重新触发 dispatch。

### 8.2 生成普通用户 token

```powershell
cd D:\python\echuu-agent\agent
@'
from datetime import timedelta
from livekit import api

room_name = "echuu-test-user"

token = (
    api.AccessToken("devkey", "secret")
    .with_identity("meet-user")
    .with_name("meet-user")
    .with_grants(
        api.VideoGrants(
            room_join=True,
            room=room_name,
            can_publish=True,
            can_subscribe=True,
        )
    )
    .with_ttl(timedelta(hours=6))
    .to_jwt()
)

print("ROOM=" + room_name)
print("TOKEN=" + token)
'@ | uv run python -
```

### 8.3 生成带 agent dispatch 的 token

把 `room_name` 改成一个新的名字，每次测试都换一个：

```powershell
cd D:\python\echuu-agent\agent
@'
from datetime import timedelta
from livekit import api

room_name = "echuu-test-20260420-1300"

token = (
    api.AccessToken("devkey", "secret")
    .with_identity("meet-user-agent")
    .with_name("meet-user-agent")
    .with_grants(
        api.VideoGrants(
            room_join=True,
            room=room_name,
            can_publish=True,
            can_subscribe=True,
        )
    )
    .with_room_config(
        api.RoomConfiguration(
            agents=[api.RoomAgentDispatch(agent_name="echuu-voice-agent")]
        )
    )
    .with_ttl(timedelta(hours=6))
    .to_jwt()
)

print("ROOM=" + room_name)
print("TOKEN=" + token)
'@ | uv run python -
```

输出会是两行：

- `ROOM=...`
- `TOKEN=...`

把 `TOKEN=` 后面的整串内容复制到测试页里。

## 9. 测试验证流程

### 9.1 验证 agent 自动进房

操作顺序：

1. 启动本机 LiveKit
2. 启动 agent
3. 打开 `test-client.html`
4. 填：
   - `Server URL = ws://127.0.0.1:7880`
   - `Token = 带 dispatch 的 token`
5. 点击 `Connect`

成功标志：

- 页面 `Participants` 从 `1` 变成 `2`
- agent 终端出现新的 job 日志
- 页面日志出现远端参与者和音频轨道相关日志

常见终端日志：

```text
no warmed process available for job
initializing job runner
job runner initialized
```

### 9.2 验证文本回复

连接成功后，在测试页输入：

```text
你好
```

点击 `Send Message`。

成功标志：

- 页面 `Chat / Data` 里出现 `text from you: 你好`
- 页面里出现 agent 的文本回复

### 9.3 验证语音播报

在测试页：

1. 点击 `Enable Mic`
2. 或者直接发送文本：

```text
你好，请语音回答我
```

成功标志：

- 页面日志出现音频轨道日志
- 页面能听到 agent 的语音
- agent 终端出现：

```text
[agent] starting tts playout
[agent] finished tts playout
```

## 10. 常见问题

### 10.1 `Participants` 一直是 1

说明 agent 没有进房。优先检查：

- 是否用了带 dispatch 的 token
- 房间名是不是新的
- agent 终端有没有新的 job 日志
- `LIVEKIT_AGENT_NAME` 是否是 `echuu-voice-agent`

### 10.2 页面能收到文本，但没有声音

优先检查：

- `ECHUU_AGENT_TTS_ENABLED=true`
- `CARTESIA_API_KEY` 是否有效
- 页面日志是否出现：
  - `track subscribed: ... (audio)`
  - `attached remote audio: ...`
  - `audio play started: ...`
- agent 终端是否出现：
  - `[agent] starting tts playout`
  - `[agent] finished tts playout`
  - `tts failed: ...`

### 10.3 agent 终端没有新 job 日志

最常见原因：

- 这次连接没有用 dispatch token
- 房间名复用了旧房间，dispatch 没重新触发

解决办法：

- 生成一张新的 dispatch token
- 使用一个全新的房间名再测

### 10.4 出现 `Usage: agent.py [OPTIONS] COMMAND [ARGS]...`

这是因为少写了子命令。  
正确启动方式是：

```powershell
uv run python src\agent.py dev
```

不是：

```powershell
uv run python src\agent.py
```

## 11. 一次完整联调的最短命令

### 11.1 安装依赖

```powershell
cd D:\python\echuu-agent\agent
uv sync
```

### 11.2 启动 agent

```powershell
cd D:\python\echuu-agent\agent
uv run python src\agent.py dev
```

### 11.3 启动测试页

```powershell
cd D:\python\echuu-agent\agent
python -m http.server 8010
```

### 11.4 打开浏览器

```text
http://127.0.0.1:8010/test-client.html
```

### 11.5 生成新 token

使用第 8.3 节的脚本，每次换一个新房间名。

### 11.6 测试

在页面中：

- `Server URL` 填 `ws://127.0.0.1:7880`
- `Token` 填刚生成的 dispatch token
- 点击 `Connect`
- 发一句 `你好，请语音回答我`

如果页面能听到 agent 说话，这条链路就算全部跑通。
