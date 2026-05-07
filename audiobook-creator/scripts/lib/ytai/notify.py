"""Send Feishu notifications via REST API."""

import json
import urllib.request
import urllib.error
from pathlib import Path

FEISHU_API = "https://open.feishu.cn/open-apis"


def _load_feishu_credentials(openclaw_config_path=None, skill_config_path=None):
    """Load Feishu app credentials and target user ID.

    Credentials come from openclaw.json (if OpenClaw is installed),
    notifyUser from the skill's own config.json.
    """
    # Try openclaw.json for app credentials
    oc_path = Path(openclaw_config_path or "~/.openclaw/openclaw.json").expanduser()
    app_id, app_secret = "", ""
    if oc_path.exists():
        with open(oc_path) as f:
            oc = json.load(f)
        acct = oc.get("channels", {}).get("feishu", {}).get("accounts", {}).get("default", {})
        app_id = acct.get("appId", "")
        app_secret = acct.get("appSecret", "")

    # Read notifyUser from skill config
    if skill_config_path:
        sc_path = Path(skill_config_path)
    else:
        sc_path = Path(__file__).resolve().parent.parent.parent.parent / "config.json"
    user_id = ""
    if sc_path.exists():
        with open(sc_path) as f:
            sc = json.load(f)
        user_id = sc.get("feishu", {}).get("notifyUser", "")

    return app_id, app_secret, user_id


def _get_tenant_token(app_id, app_secret):
    url = f"{FEISHU_API}/auth/v3/tenant_access_token/internal"
    data = json.dumps({"app_id": app_id, "app_secret": app_secret}).encode()
    req = urllib.request.Request(url, data=data,
                                  headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        result = json.loads(resp.read())
    if result.get("code") != 0:
        raise RuntimeError(f"Feishu token error: {result}")
    return result["tenant_access_token"]


def _send_message(token, user_id, text):
    url = f"{FEISHU_API}/im/v1/messages?receive_id_type=open_id"
    body = {
        "receive_id": user_id,
        "msg_type": "text",
        "content": json.dumps({"text": text}),
    }
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers={
        "Content-Type": "application/json; charset=utf-8",
        "Authorization": f"Bearer {token}",
    })
    with urllib.request.urlopen(req, timeout=15) as resp:
        result = json.loads(resp.read())
    if result.get("code") != 0:
        raise RuntimeError(f"Feishu send error: {result}")


def send_feishu_message(message, openclaw_config_path=None, skill_config_path=None):
    """Send a text message via Feishu REST API.

    Returns True on success, False on failure.
    """
    try:
        app_id, app_secret, user_id = _load_feishu_credentials(
            openclaw_config_path, skill_config_path)
        if not all([app_id, app_secret, user_id]):
            print("FEISHU_ERROR: missing credentials or notifyUser", flush=True)
            return False
        token = _get_tenant_token(app_id, app_secret)
        _send_message(token, user_id, message)
        print("FEISHU_OK: message sent", flush=True)
        return True
    except Exception as e:
        print(f"FEISHU_FAILED: {e}", flush=True)
        return False
