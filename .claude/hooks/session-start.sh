#!/bin/bash
# SessionStart hook for Claude Code cloud sessions (claude.ai/code and the Claude mobile app).
#
# Cloud sessions start from a fresh clone, so nothing is installed. This installs the locked
# dependencies with uv so that `./scripts/check.sh`, `uv run pytest`, ruff, and mypy all work
# from the first message. It only runs in cloud sessions; locally it exits immediately.
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "${CLAUDE_PROJECT_DIR:-$(dirname "$0")/../..}"

# The cloud image ships uv; fall back to a user install if it ever doesn't.
if ! command -v uv >/dev/null 2>&1; then
  echo "uv not found; installing with pip" >&2
  python3 -m pip install --quiet --user uv
  export PATH="$HOME/.local/bin:$PATH"
  if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
    echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$CLAUDE_ENV_FILE"
  fi
fi

# Same install CI uses: exact versions from uv.lock, including the dev tools.
uv sync --locked --all-extras --dev

echo "Dependencies installed. Run ./scripts/check.sh for the full CI check." >&2
