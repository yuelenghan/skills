# audiobook-creator skill 安装说明

## 系统依赖

- Python 3.10+
- ffmpeg（含 libass 字幕支持）
  - macOS: `brew tap homebrew-ffmpeg/ffmpeg && brew install homebrew-ffmpeg/ffmpeg/ffmpeg`
  - Linux: `apt install ffmpeg libass-dev`

## Python 依赖

```bash
pip install -r requirements.txt
```

## 安装方式

解压 zip 到以下任一位置：

- **Claude Code / Cline / Cursor 等**: `.claude/skills/audiobook-creator/`
- **其他 agent**: 任意目录，在 agent 配置中指向 SKILL.md

## 配置

### B站发布（可选）

Agent 首次使用时会自动从你的浏览器提取 B站 cookies（前提：你已在浏览器登录 bilibili.com）：

```bash
python3 scripts/login-bilibili.py
```

原理：通过 yt-dlp 读取浏览器已保存的登录状态，提取 SESSDATA/bili_jct/DedeUserID，保存到 `bilibili-cookies.json`。

- 无需扫码、无需输入密码
- 支持 Chrome/Firefox/Safari/Edge 等主流浏览器
- Cookies 有效期约 1 个月，过期后重新运行即可

**不想发布到 B站？** 直接跳过此步骤，skill 会只生成视频文件不发布。

### 飞书通知（可选，仅 OpenClaw 用户）

交互式 agent 用户无需配置（agent 在对话中直接报告结果）。

OpenClaw 用户如需发布后飞书通知：

```bash
python3 scripts/setup-feishu.py
```

脚本会引导你配置 open_id。前提：

1. `~/.openclaw/openclaw.json` 中已配置飞书 bot 凭据：

```json
{
  "channels": {
    "feishu": {
      "accounts": {
        "default": {
          "appId": "cli_xxxxxxxxxx",
          "appSecret": "xxxxxxxxxx"
        }
      }
    }
  }
}
```

2. 你的飞书 open_id（通过向 bot 发消息后在事件日志中获取）

不配置时 pipeline 正常运行，只是不发通知。

## 使用

通过 agent 对话触发：

```
帮我把《三体》做成有声书
```

Agent 会自动调用 `scripts/pipeline.sh` 执行完整流程。

## 平台限制

- Apple Books epub 自动提取仅 macOS 支持
- 其他平台：将小说导出为 txt，用 `--source` 参数指定路径
