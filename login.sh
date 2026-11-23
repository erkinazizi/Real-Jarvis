#!/bin/zsh
# Log Jarvis's brain into your Claude account (one time). Type /login, finish in the browser, then /exit.
cd "$(dirname "$0")"
CLI="$(.venv/bin/python -c 'import claude_agent_sdk,os;print(os.path.join(os.path.dirname(claude_agent_sdk.__file__),"_bundled","claude"))')"
exec "$CLI"
