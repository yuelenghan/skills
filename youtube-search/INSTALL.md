# youtube-search skill 安装说明

## 系统依赖

- yt-dlp
  - macOS: `brew install yt-dlp`
  - Linux: `pip install yt-dlp`
- ffmpeg（需要 libass 支持，用于字幕烧录）
  - macOS: `brew tap homebrew-ffmpeg/ffmpeg && brew install homebrew-ffmpeg/ffmpeg/ffmpeg`
  - Linux: `apt install ffmpeg`
- jq
  - macOS: `brew install jq`
  - Linux: `apt install jq`
- Python 3 + 依赖包
  - `pip install -r requirements.txt`
  - 包含：edge-tts, bilibili-api-python, Pillow, numpy

## 安装方式

将 `youtube-search/` 文件夹复制到以下任一位置：

- **Claude Code / Cline / Cursor 等**: `.claude/skills/youtube-search/`
- **其他 agent**: 任意目录，在 agent 配置中指向 SKILL.md

## 配置

**开箱即用**：脚本自动使用 `config.example.json` 中的默认配置，无需额外操作。

**自定义**：在 skill 目录下创建 `config.json`，脚本会优先读取它。只需覆盖你想修改的字段：

```json
{
  "outputDir": "~/Videos/my-downloads",
  "daysBack": 7,
  "browser": "firefox"
}
```

## 使用

通过 agent 对话触发即可，agent 会自动执行完整的 7 步流水线：

```
搜索 YouTube 上关于 machine learning 的视频
```

完整流水线：搜索 → 下载 → 字幕翻译 → TTS 配音 → 视频合成 → B站发布 → 归档。

详见 `SKILL.md` 中的 Workflow 章节，配置详情见 `references/config.md`。

## 浏览器 Cookies

yt-dlp 需要从浏览器获取 YouTube 登录态来提升搜索质量。默认使用 Chrome，可通过配置或 `--browser` 参数切换：

支持：Chrome / Firefox / Safari / Edge / Chromium / Brave / Opera

## Bilibili 发布（可选）

如需发布到 B 站，还需配置 cookie 文件。详见 `SKILL.md` 中的 Bilibili Cookie Format 章节。
