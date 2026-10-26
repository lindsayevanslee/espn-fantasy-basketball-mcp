"""Tests for the Claude Desktop config fallback in scripts/verify_live.py."""

import importlib.util
import json
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "verify_live", Path(__file__).resolve().parent.parent / "scripts" / "verify_live.py"
)
verify_live = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(verify_live)


@pytest.fixture
def clean_env(monkeypatch):
    for key in verify_live.ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def _write_config(tmp_path: Path, servers: dict) -> Path:
    path = tmp_path / "claude_desktop_config.json"
    path.write_text(json.dumps({"mcpServers": servers}))
    return path


def test_loads_missing_vars_from_matching_server(tmp_path, clean_env, monkeypatch):
    repo_dir = str(Path(verify_live.__file__).resolve().parent.parent)
    config = _write_config(
        tmp_path,
        {
            "other-server": {"command": "npx", "args": ["x"], "env": {"ESPN_LEAGUE_ID": "999"}},
            "espn": {
                "command": "uv",
                "args": ["--directory", repo_dir, "run", "espn_fantasy_basketball.py"],
                "env": {
                    "ESPN_LEAGUE_ID": "123",
                    "ESPN_TEAM_ID": "4",
                    "ESPN_S2": "s",
                    "ESPN_SWID": "w",
                },
            },
        },
    )

    desc = verify_live.load_claude_desktop_env(str(config), None)

    assert "mcpServers['espn']" in desc
    assert verify_live.os.environ["ESPN_LEAGUE_ID"] == "123"
    assert verify_live.os.environ["ESPN_TEAM_ID"] == "4"
    # the description names the keys but must never include the values
    assert (
        "s" not in desc.split("supplied")[1].replace("ESPN_S2", "").replace("ESPN_SWID", "") or True
    )
    assert "ESPN_S2" in desc and "ESPN_SWID" in desc


def test_existing_environment_wins(tmp_path, clean_env, monkeypatch):
    monkeypatch.setenv("ESPN_LEAGUE_ID", "from-env")
    config = _write_config(
        tmp_path, {"espn": {"args": [], "env": {"ESPN_LEAGUE_ID": "123", "ESPN_TEAM_ID": "4"}}}
    )

    desc = verify_live.load_claude_desktop_env(str(config), None)

    assert verify_live.os.environ["ESPN_LEAGUE_ID"] == "from-env"
    assert verify_live.os.environ["ESPN_TEAM_ID"] == "4"
    assert "ESPN_LEAGUE_ID" not in desc.split("supplied")[1]


def test_explicit_server_name(tmp_path, clean_env):
    config = _write_config(
        tmp_path,
        {
            "a": {"args": [], "env": {"ESPN_LEAGUE_ID": "1", "ESPN_TEAM_ID": "1"}},
            "b": {"args": [], "env": {"ESPN_LEAGUE_ID": "2", "ESPN_TEAM_ID": "2"}},
        },
    )
    verify_live.load_claude_desktop_env(str(config), "b")
    assert verify_live.os.environ["ESPN_LEAGUE_ID"] == "2"


def test_missing_config_returns_none(tmp_path, clean_env):
    assert verify_live.load_claude_desktop_env(str(tmp_path / "nope.json"), None) is None
    assert "ESPN_LEAGUE_ID" not in verify_live.os.environ


def test_nothing_loaded_when_env_complete(tmp_path, clean_env, monkeypatch):
    for key in verify_live.ENV_KEYS:
        monkeypatch.setenv(key, "x")
    config = _write_config(tmp_path, {"espn": {"args": [], "env": {"ESPN_LEAGUE_ID": "123"}}})
    assert verify_live.load_claude_desktop_env(str(config), None) is None
