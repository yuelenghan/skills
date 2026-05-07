#!/usr/bin/env python3
"""Configure Feishu notification for audiobook-creator skill (OpenClaw users only)."""

import json
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = SKILL_DIR / "config.json"
OPENCLAW_CONFIG = Path.home() / ".openclaw/openclaw.json"


def configure_feishu():
    print("\n" + "=" * 50)
    print("飞书通知配置（仅 OpenClaw 用户需要）")
    print("=" * 50)
    print()
    print("配置完成后，有声书发布到 B站 后会收到飞书消息通知。")
    print()

    # Check OpenClaw credentials
    if not OPENCLAW_CONFIG.exists():
        print("⚠ 未检测到 OpenClaw 配置 (~/.openclaw/openclaw.json)")
        print("  如果你使用的是 Claude Code，无需配置飞书通知（agent 会直接在对话中报告结果）。")
        print("  如果你使用的是 OpenClaw，请先完成 OpenClaw 安装。")
        return

    oc = json.loads(OPENCLAW_CONFIG.read_text())
    acct = oc.get("channels", {}).get("feishu", {}).get("accounts", {}).get("default", {})
    has_creds = bool(acct.get("appId") and acct.get("appSecret"))

    if not has_creds:
        print("⚠ OpenClaw 中未配置飞书 bot 凭据。")
        print()
        print("请在 ~/.openclaw/openclaw.json 中添加：")
        print(json.dumps({
            "channels": {"feishu": {"accounts": {"default": {
                "appId": "cli_你的appId",
                "appSecret": "你的appSecret"
            }}}}
        }, indent=2, ensure_ascii=False))
        print()
        print("获取方式：飞书开放平台 → 创建自建应用 → 获取 App ID 和 App Secret")
        return

    print("✓ 已检测到飞书 bot 凭据")
    print()
    print("接下来需要你的飞书 open_id（用于接收消息）。")
    print()
    print("获取方式：")
    print("  1. 在飞书开放平台 → 你的应用 → 事件订阅")
    print("  2. 给 bot 发一条消息")
    print("  3. 在事件日志中找到 open_id（格式：ou_xxxxxxxxxxxx）")
    print()
    print("注意：open_id 是 per-app 的，不同应用下同一个人的 open_id 不同。")
    print()

    open_id = input("请输入你的 open_id (留空跳过): ").strip()
    if not open_id:
        print("已跳过，后续可手动编辑 config.json 中的 feishu.notifyUser 字段。")
        return

    if not open_id.startswith("ou_"):
        print(f"⚠ '{open_id}' 不像有效的 open_id（通常以 ou_ 开头）")
        resp = input("确认使用？(y/N): ").strip().lower()
        if resp != "y":
            print("已取消。")
            return

    config = json.loads(CONFIG_PATH.read_text())
    config.setdefault("feishu", {})["notifyUser"] = open_id
    CONFIG_PATH.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n")
    print(f"✓ 已保存 open_id 到 config.json")
    print("  有声书发布完成后，你将收到飞书通知。")


if __name__ == "__main__":
    configure_feishu()
