#!/usr/bin/env python3
"""Extract Bilibili cookies from user's browser — no QR codes, no login links.

Usage:
    python3 login-bilibili.py [--browser BROWSER] [--force]

Supported browsers: chrome, firefox, safari, edge, chromium, brave, opera
Default: auto-detect (tries chrome first)

Flow:
    1. User is already logged into bilibili.com in their browser
    2. This script extracts SESSDATA/bili_jct/DedeUserID via yt-dlp
    3. Saves to bilibili-cookies.json

Output protocol (stdout):
    STATUS=DONE         — cookies extracted and saved
    STATUS=EXISTS       — cookies already exist (skip)
    STATUS=NOT_LOGGED_IN — user not logged into bilibili in browser
    ERROR=<message>     — something went wrong
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
COOKIE_PATH = SKILL_DIR / "bilibili-cookies.json"

BROWSERS = ["chrome", "firefox", "safari", "edge", "chromium", "brave", "opera"]


def extract_cookies(browser=None):
    """Extract bilibili cookies from browser using yt-dlp."""
    browsers_to_try = [browser] if browser else BROWSERS
    cookie_file = Path(tempfile.gettempdir()) / "bili-extract-cookies.txt"

    for br in browsers_to_try:
        try:
            result = subprocess.run(
                ["yt-dlp", "--cookies-from-browser", br,
                 "--cookies", str(cookie_file),
                 "--skip-download", "--quiet",
                 "https://www.bilibili.com/"],
                capture_output=True, text=True, timeout=30
            )
            if cookie_file.exists() and cookie_file.stat().st_size > 0:
                cookies = parse_cookie_file(cookie_file)
                if cookies:
                    return cookies, br
        except (subprocess.TimeoutExpired, FileNotFoundError):
            continue
        finally:
            cookie_file.unlink(missing_ok=True)

    return None, None


def parse_cookie_file(path):
    """Parse Netscape cookie file for bilibili credentials."""
    sessdata = bili_jct = dedeuserid = ""

    for line in path.read_text().splitlines():
        if line.startswith("#") or not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < 7:
            continue
        domain, _, _, _, _, name, value = parts[:7]
        if "bilibili.com" not in domain:
            continue
        if name == "SESSDATA":
            sessdata = value
        elif name == "bili_jct":
            bili_jct = value
        elif name == "DedeUserID":
            dedeuserid = value

    if sessdata and bili_jct and dedeuserid:
        return {"sessdata": sessdata, "bili_jct": bili_jct, "dedeuserid": dedeuserid}
    return None


def main():
    force = "--force" in sys.argv
    browser = None
    if "--browser" in sys.argv:
        idx = sys.argv.index("--browser")
        if idx + 1 < len(sys.argv):
            browser = sys.argv[idx + 1]

    if COOKIE_PATH.exists() and not force:
        print("STATUS=EXISTS", flush=True)
        print(f"COOKIE_PATH={COOKIE_PATH}", flush=True)
        sys.exit(0)

    # Check yt-dlp exists
    try:
        subprocess.run(["yt-dlp", "--version"], capture_output=True, timeout=5)
    except FileNotFoundError:
        print("ERROR=yt-dlp 未安装。请运行: pip install yt-dlp", flush=True)
        sys.exit(1)

    print("EXTRACTING", flush=True)
    cookies, used_browser = extract_cookies(browser)

    if not cookies:
        print("STATUS=NOT_LOGGED_IN", flush=True)
        print("HINT=请先在浏览器登录 bilibili.com，然后重新运行此脚本", flush=True)
        sys.exit(1)

    # Save in expected format
    cookie_data = {
        "cookie_info": {
            "cookies": [
                {"name": "SESSDATA", "value": cookies["sessdata"]},
                {"name": "bili_jct", "value": cookies["bili_jct"]},
                {"name": "DedeUserID", "value": cookies["dedeuserid"]},
            ]
        }
    }
    COOKIE_PATH.write_text(json.dumps(cookie_data, indent=2, ensure_ascii=False))
    COOKIE_PATH.chmod(0o600)
    print("STATUS=DONE", flush=True)
    print(f"BROWSER={used_browser}", flush=True)
    print(f"COOKIE_PATH={COOKIE_PATH}", flush=True)


if __name__ == "__main__":
    main()
