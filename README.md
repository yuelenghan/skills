# AI Agent Skills

通用 AI agent 技能集合。

## 可用技能

| 技能 | 说明 |
|------|------|
| [audiobook-creator](./audiobook-creator/) | 将小说变成多集有声书视频（TTS + 字幕 + BGM），支持发布到 B站 |

## 安装

将 skill 文件夹复制到你的 agent 能读取的位置，然后在 agent 配置中指向 `SKILL.md` 即可。

各平台示例：

| 平台 | 安装路径 |
|------|---------|
| Claude Code | `.claude/skills/audiobook-creator/` |
| Cline / Cursor | 项目根目录或自定义 skill 目录 |
| OpenClaw | 在 task 配置中引用 `SKILL.md` |

安装后正常与 agent 对话即可触发 skill。

## 兼容性

已测试：

- Claude Opus 4.6
- GLM-5
- DeepSeek V4 Pro

## 许可

MIT
