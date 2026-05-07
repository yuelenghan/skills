# audiobook-creator

一句话把小说变成有声书视频，发布到 B 站。

## 效果

告诉 AI agent「帮我把《三体》做成有声书」，它会自动完成：

1. 从 Apple Books 提取 epub 全文和封面
2. 按章节拆分成若干集（每集 40-50 分钟）
3. 逐集生成语音（edge-tts）+ 字幕时间轴
4. 合成视频（封面背景 + 字幕 + BGM）
5. 上传到 B 站（标题、简介、标签全自动）

整个流程你只需要做两个决定：做哪本书，发不发。

## 安装

### 1. 放置 skill

```bash
cp -r audiobook-creator /path/to/your/project/.claude/skills/
```

### 2. 系统依赖

- Python 3.10+
- ffmpeg（含 libass 字幕支持）

```bash
# macOS
brew tap homebrew-ffmpeg/ffmpeg && brew install homebrew-ffmpeg/ffmpeg/ffmpeg

# Linux
apt install ffmpeg libass-dev
```

### 3. Python 依赖

```bash
pip install -r audiobook-creator/requirements.txt
```

### 4. 配置

`config.json` 已包含默认配置，开箱即用。输出目录为 `~/Videos/audiobook`，可按需修改。

### 5. B 站发布（可选）

首次使用时 agent 会自动提取浏览器中的 B 站登录状态，前提是你已在浏览器登录 bilibili.com。不想发布也行，跳过即可。

## 使用

在 agent 对话中直接说：

```
帮我把《书名》做成有声书
```

Agent 会自动识别 skill 并执行 pipeline。

### 更多用法

```
帮我把《书名》做成有声书，用女声
帮我把 ~/Downloads/novel.txt 做成有声书
继续上次没做完的《书名》
把《书名》第3集重做，换个背景音乐
```

## 支持的模型

不依赖外部 AI API。Agent 本身就是模型，所有智能决策（体裁判断、配音选择、标题生成等）由运行 skill 的 agent 完成。

已测试：
- Claude Opus 4.6
- GLM-5
- DeepSeek V4 Pro

## 目录结构

```
audiobook-creator/
├── SKILL.md              # Skill 定义（agent 读取的入口）
├── INSTALL.md            # 安装说明
├── config.json           # 默认配置
├── requirements.txt      # Python 依赖
├── scripts/
│   ├── pipeline.sh       # 主流程脚本
│   ├── extract-book.py   # Apple Books epub 提取
│   ├── init-novel.py     # 项目初始化
│   ├── split-novel.py    # 章节拆分
│   ├── generate-narration.py  # 旁白文本生成
│   ├── render-tts.py     # TTS 语音合成
│   ├── compose-video.py  # 视频合成
│   ├── publish-novel.py  # B站上传
│   ├── login-bilibili.py # B站登录提取
│   ├── setup-feishu.py   # 飞书通知配置
│   └── lib/ytai/         # 工具库
└── assets/
    └── bgm/              # 背景音乐（按体裁分类）
```

## 输出结构

```
~/Videos/audiobook/
├── sources/
│   ├── 书名.txt
│   └── 书名-cover.jpg
├── drafts/
│   ├── 书名-EP01/
│   │   ├── outline.json
│   │   ├── narration.md
│   │   ├── narration.mp3
│   │   ├── narration.srt
│   │   └── final.mp4
│   └── 书名-EP02/
│       └── ...
└── published.txt
```

## 断点续跑

Pipeline 是幂等的——检测到已完成的步骤会自动跳过：

- `outline.json` 存在 → 跳过拆分
- `narration.mp3` 存在 → 跳过 TTS
- `final.mp4` 存在且 >10MB → 跳过合成
- `published.txt` 有记录 → 跳过上传

要重做某步：删掉对应输出文件，重新运行。

## License

MIT
