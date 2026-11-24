"""Connecting Jarvis to Claude: sign in with a Claude account (Pro/Max) or use an Anthropic API key.

- Account sign-in uses the Claude CLI that ships with claude-agent-sdk (`claude auth login`).
- An API key is stored in the macOS Keychain, never in settings.json or the logs.
"""
import json
import os
import subprocess

import config

KEYCHAIN_SERVICE = "Real Jarvis - Anthropic API key"
KEYCHAIN_ACCOUNT = "real-jarvis"


def cli_path() -> str:
    import claude_agent_sdk
    return os.path.join(os.path.dirname(claude_agent_sdk.__file__), "_bundled", "claude")


# -- API key (Keychain) -------------------------------------------------------------
def get_api_key() -> str | None:
    try:
        r = subprocess.run(["security", "find-generic-password", "-a", KEYCHAIN_ACCOUNT,
                            "-s", KEYCHAIN_SERVICE, "-w"], capture_output=True, text=True)
    except FileNotFoundError:          # not on macOS
        return None
    key = r.stdout.strip()
    return key if r.returncode == 0 and key else None


def save_api_key(key: str) -> str:
    key = key.strip()
    if not key.startswith("sk-ant-") or len(key) < 30:
        raise ValueError("That doesn't look like an Anthropic API key (it starts with sk-ant-).")
    r = subprocess.run(["security", "add-generic-password", "-U", "-a", KEYCHAIN_ACCOUNT,
                        "-s", KEYCHAIN_SERVICE, "-w", key], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("Couldn't save the key to the Keychain.")
    return mask(key)


def remove_api_key() -> None:
    subprocess.run(["security", "delete-generic-password", "-a", KEYCHAIN_ACCOUNT,
                    "-s", KEYCHAIN_SERVICE], capture_output=True)


def mask(key: str | None) -> str:
    return f"{key[:10]}…{key[-4:]}" if key else ""


def brain_env() -> dict[str, str]:
    """Environment for the Claude process: the API key in API-key mode, nothing extra otherwise."""
    if config.AUTH_MODE == "api_key":
        key = get_api_key()
        if key:
            return {"ANTHROPIC_API_KEY": key}
    return {"ANTHROPIC_API_KEY": ""}      # account mode: don't pick up a stray key from the shell


# -- account sign-in ----------------------------------------------------------------
def status() -> dict:
    """What Jarvis is connected with right now."""
    out = {"mode": config.AUTH_MODE, "api_key": mask(get_api_key()), "account": None, "error": ""}
    try:
        r = subprocess.run([cli_path(), "auth", "status", "--json"], capture_output=True, text=True,
                           timeout=20, env=os.environ | {"ANTHROPIC_API_KEY": ""})
        out["account"] = json.loads(r.stdout)
    except Exception as e:
        out["error"] = f"Couldn't read the Claude sign-in status: {e}"
    return out


def sign_in(console: bool = False) -> None:
    """Start the browser sign-in. The CLI opens the browser and finishes by itself."""
    config.LOG_DIR.mkdir(exist_ok=True)
    log = open(config.LOG_DIR / "claude-login.log", "w")
    subprocess.Popen([cli_path(), "auth", "login", "--console" if console else "--claudeai"],
                     stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
                     env=os.environ | {"ANTHROPIC_API_KEY": ""})


def sign_in_in_terminal() -> None:
    """Fallback: run the sign-in in a Terminal window."""
    subprocess.Popen(["open", "-a", "Terminal", str(config.BASE_DIR / "login.sh")])


def sign_out() -> None:
    subprocess.run([cli_path(), "auth", "logout"], capture_output=True, timeout=30,
                   env=os.environ | {"ANTHROPIC_API_KEY": ""})


def test_connection() -> dict:
    """Ask Claude for one word with the current settings. Returns {ok, message}."""
    model = config.CLAUDE_MODEL or "haiku"
    try:
        r = subprocess.run([cli_path(), "-p", "Reply with exactly: OK", "--model", model,
                            "--output-format", "json", "--max-turns", "1"],
                           capture_output=True, text=True, timeout=90, env=os.environ | brain_env(),
                           cwd=str(config.SAFE_DIR) if config.SAFE_DIR.exists() else None)
        data = json.loads(r.stdout or "{}")
        if r.returncode == 0 and not data.get("is_error"):
            return {"ok": True, "message": f"Connected — Claude answered with {model}."}
        msg = data.get("result") or r.stderr.strip() or "No answer."
        return {"ok": False, "message": msg[:300]}
    except subprocess.TimeoutExpired:
        return {"ok": False, "message": "Claude didn't answer within 90 seconds."}
    except Exception as e:
        return {"ok": False, "message": str(e)[:300]}
