"""The README's Cloud Run blocks are code people paste into a terminal, so test them as code.

Each block is pulled out of README.md and run under bash against stand-in ``gcloud``, ``git``
and ``curl`` commands that record what they were asked to do. Nothing here touches the network
or a real Google Cloud project. The properties pinned are the ones a mistake would hurt:
secrets never appear on a command line, the update block is complete on its own and leaves
the service's settings alone, and a failed step stops the block before anything is deployed.
"""

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

README = Path(__file__).resolve().parent.parent / "README.md"
pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")

SECRETS = ["espn-mcp-token", "espn-s2", "espn-swid", "espn-league-id", "espn-team-id"]

GCLOUD_STUB = r"""#!/bin/bash
# Stand-in for gcloud: records argv (one call per line) and anything piped to --data-file=-.
echo "$*" >> "$STUB_DIR/gcloud.argv"
name="$3"; [ "$2" = versions ] && name="$4"   # secrets create NAME | secrets versions add NAME
case "$*" in *"--data-file=-"*) { printf '%s=' "$name"; cat; echo; } >> "$STUB_DIR/gcloud.stdin";; esac
case "$*" in
  "projects describe"*) echo 123456789012;;
  "run deploy"*) exit "${STUB_DEPLOY_EXIT:-0}";;
  "secrets versions list"*"--limit=1"*) echo 3;;
  "secrets versions list"*) printf '3\n2\n';;
esac
exit 0
"""

GIT_STUB = r"""#!/bin/bash
# Stand-in for git: records argv; "clone" creates a checkout so the block can cd into it.
echo "$*" >> "$STUB_DIR/git.argv"
case "$1" in
  clone) mkdir -p "$3/.git"; [ -n "${STUB_NO_DOCKERFILE:-}" ] || touch "$3/Dockerfile";;
  log) echo "abc1234 Example commit";;
  merge) exit "${STUB_MERGE_EXIT:-0}";;
esac
exit 0
"""

CURL_STUB = r"""#!/bin/bash
# Stand-in for curl: answers the three verification requests the way a healthy server does.
url="${@: -1}"
case "$url" in
  */health) printf '%s' "${STUB_HEALTH_STATUS:-200}";;
  */.well-known/oauth-protected-resource) printf '{"resource": "%s/mcp"}' "${url%%/.well-known*}";;
  */mcp) printf '401';;
esac
"""


def bash_block_after(marker: str) -> str:
    """Return the first ```bash block that follows ``marker`` in the README."""
    text = README.read_text()
    assert text.count(marker) == 1, f"expected exactly one {marker!r} in README.md"
    match = re.search(r"```bash\n(.*?)```", text[text.index(marker) :], re.S)
    assert match, f"no bash block after {marker!r}"
    return match.group(1)


def hosting_blocks() -> list[str]:
    text = README.read_text()
    section = text[text.index("### 2. Host it with HTTPS") : text.index("#### What it costs")]
    return re.findall(r"```bash\n(.*?)```", section, re.S)


@pytest.fixture
def run_block(tmp_path):
    """Run a README block under bash with stand-in commands; return (result, read_log)."""
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    for name, body in (("gcloud", GCLOUD_STUB), ("git", GIT_STUB), ("curl", CURL_STUB)):
        (stubs / name).write_text(body)
        (stubs / name).chmod(0o755)
    (stubs / "python3").symlink_to(sys.executable)
    home = tmp_path / "home"
    home.mkdir()

    def read_log(name: str) -> str:
        path = stubs / name
        return path.read_text() if path.exists() else ""

    def run(block: str, stdin: str = "", **extra_env: str) -> subprocess.CompletedProcess:
        # A deliberately bare environment: the block gets nothing from "an earlier step".
        env = {
            "PATH": f"{stubs}{os.pathsep}/usr/bin{os.pathsep}/bin",
            "HOME": str(home),
            "STUB_DIR": str(stubs),
            **extra_env,
        }
        return subprocess.run(
            ["bash", "-c", block],
            input=stdin,
            env=env,
            cwd=tmp_path,
            capture_output=True,
            text=True,
            timeout=60,
        )

    run.home = home  # type: ignore[attr-defined]
    return run, read_log


# --------------------------------------------------------------------------- static checks


def test_every_hosting_block_is_valid_bash():
    blocks = hosting_blocks()
    assert len(blocks) >= 8
    for block in blocks:
        result = subprocess.run(["bash", "-n"], input=block, capture_output=True, text=True)
        assert result.returncode == 0, f"{result.stderr}\n--- block ---\n{block}"


def test_first_deploy_reads_league_settings_from_secrets_not_plain_variables():
    block = bash_block_after("**d. Deploy.**")
    set_secrets = re.search(r'--set-secrets "([^"]+)"', block).group(1)
    assert set_secrets.split(",") == [
        "MCP_AUTH_TOKEN=espn-mcp-token:latest",
        "ESPN_S2=espn-s2:latest",
        "ESPN_SWID=espn-swid:latest",
        "ESPN_LEAGUE_ID=espn-league-id:latest",
        "ESPN_TEAM_ID=espn-team-id:latest",
    ]
    set_env = re.search(r'--set-env-vars "([^"]+)"', block).group(1)
    assert "ESPN_" not in set_env  # nothing league-specific is typed into the deploy command
    assert "--max-instances 1" in block  # the cost ceiling


def test_service_account_is_granted_exactly_the_secrets_the_deploy_mounts():
    block = bash_block_after("**c. A service account")
    granted = re.search(r"for s in ([^;]+); do", block).group(1).split()
    assert granted == SECRETS


# --------------------------------------------------------------------------- block b: secrets


def test_secrets_block_stores_each_value_without_exposing_it(run_block):
    run, read_log = run_block
    block = bash_block_after("**b. Secrets and league settings.**")
    answers = ["S2-COOKIE-VALUE", "{SWID-VALUE}", "424242", "7"]
    result = run(block, stdin="\n".join(answers) + "\n")
    assert result.returncode == 0, result.stderr

    stored = dict(line.split("=", 1) for line in read_log("gcloud.stdin").splitlines())
    assert list(stored) == SECRETS
    assert len(stored["espn-mcp-token"]) >= 32
    assert [stored[name] for name in SECRETS[1:]] == answers  # exact, no stray newline

    argv = read_log("gcloud.argv")
    for value in [*answers[:2], stored["espn-mcp-token"]]:
        assert value not in argv  # never on a command line
        assert value not in result.stdout + result.stderr  # never echoed back


def test_secrets_block_stops_at_the_first_failure(run_block):
    run, read_log = run_block
    block = bash_block_after("**b. Secrets and league settings.**")
    result = run(block, stdin="only-one-answer\n")  # input runs out at the second prompt
    assert result.returncode != 0
    assert "espn-team-id" not in read_log("gcloud.argv")


# --------------------------------------------------------------------------- the update block

UPDATE_MARKER = "**From Cloud Shell: one block.**"


def _checkout(home: Path, dockerfile: bool = True) -> None:
    repo = home / "espn-fantasy-basketball-mcp"
    (repo / ".git").mkdir(parents=True)
    if dockerfile:
        (repo / "Dockerfile").touch()


def test_update_block_is_self_contained_and_redeploys(run_block):
    run, read_log = run_block
    _checkout(run.home)
    result = run(bash_block_after(UPDATE_MARKER))
    assert result.returncode == 0, result.stderr + result.stdout
    assert result.stdout.count("PASS") == 3

    assert read_log("git.argv").splitlines() == [
        "fetch origin",
        "checkout main",
        "merge --ff-only origin/main",
        "log --oneline -1",
    ]
    deploys = [c for c in read_log("gcloud.argv").splitlines() if c.startswith("run deploy")]
    assert deploys == [
        "run deploy espn-fantasy-mcp --source . --region us-central1 "
        "--project espn-mcp-YOURNAME --quiet"
    ]
    assert "https://espn-fantasy-mcp-123456789012.us-central1.run.app/mcp" in result.stdout


def test_update_block_never_touches_service_settings():
    """Settings carry over only if the redeploy does not restate them."""
    block = bash_block_after(UPDATE_MARKER)
    for flag in ("--set-", "--update-", "--remove-", "--clear-", "--service-account", "--allow-"):
        assert flag not in block, flag


def test_update_block_clones_when_there_is_no_checkout(run_block):
    run, read_log = run_block
    result = run(bash_block_after(UPDATE_MARKER))
    assert result.returncode == 0, result.stderr + result.stdout
    assert read_log("git.argv").splitlines()[0].startswith("clone https://github.com/")


@pytest.mark.parametrize(
    ("env", "expected_output"),
    [
        ({"STUB_MERGE_EXIT": "1"}, ""),  # local branch has diverged: refuse to guess
        ({"STUB_NO_DOCKERFILE": "1"}, "STOP: no Dockerfile"),  # e.g. a branch without hosting
    ],
    ids=["cannot-fast-forward", "no-dockerfile"],
)
def test_update_block_deploys_nothing_when_the_code_is_not_ready(run_block, env, expected_output):
    run, read_log = run_block
    _checkout(run.home, dockerfile="STUB_NO_DOCKERFILE" not in env)
    result = run(bash_block_after(UPDATE_MARKER), **env)
    assert result.returncode != 0
    assert expected_output in result.stdout
    assert "run deploy" not in read_log("gcloud.argv")


def test_update_block_reports_a_failed_deploy(run_block):
    run, _ = run_block
    _checkout(run.home)
    result = run(bash_block_after(UPDATE_MARKER), STUB_DEPLOY_EXIT="1")
    assert result.returncode != 0
    assert "PASS" not in result.stdout and "Updated." not in result.stdout


def test_update_block_fails_loudly_when_the_new_revision_is_unhealthy(run_block):
    run, _ = run_block
    _checkout(run.home)
    result = run(bash_block_after(UPDATE_MARKER), STUB_HEALTH_STATUS="404")
    assert result.returncode != 0
    assert "FAIL  health check answers: expected 200, got 404" in result.stdout
    assert "Updated." not in result.stdout


# --------------------------------------------------------------------------- cookie refresh


def test_cookie_refresh_adds_a_version_retires_old_ones_and_restarts(run_block):
    run, read_log = run_block
    result = run(bash_block_after("**Refreshing an expired ESPN cookie.**"), stdin="NEW-S2\n")
    assert result.returncode == 0, result.stderr

    assert read_log("gcloud.stdin") == "espn-s2=NEW-S2\n"
    calls = read_log("gcloud.argv").splitlines()
    assert "NEW-S2" not in "\n".join(calls) + result.stdout + result.stderr
    disables = [c for c in calls if c.startswith("secrets versions disable")]
    # The stand-in reports versions 3 and 2 as enabled, 3 being the newest: only 2 is retired.
    assert disables == ["secrets versions disable 2 --secret espn-s2 --project espn-mcp-YOURNAME"]
    assert calls[-1].startswith("run services update espn-fantasy-mcp ")
    assert "--update-env-vars SECRETS_REFRESHED_AT=" in calls[-1]


# --------------------------------------------------------------------------- one-time migration


def test_migration_moves_both_ids_to_secrets_in_one_revision(run_block):
    run, read_log = run_block
    block = bash_block_after("**Moving league and team ID into secrets on an existing service.**")
    result = run(block, stdin="424242\n7\n")
    assert result.returncode == 0, result.stderr

    assert read_log("gcloud.stdin") == "espn-league-id=424242\nespn-team-id=7\n"
    calls = read_log("gcloud.argv").splitlines()
    updates = [c for c in calls if c.startswith("run services update")]
    # One command, so one revision: gcloud rejects --update-secrets for a name that is still a
    # plain variable, and removing first in a separate step would leave a revision without IDs.
    assert len(updates) == 1
    assert "--remove-env-vars ESPN_LEAGUE_ID,ESPN_TEAM_ID" in updates[0]
    assert (
        "--update-secrets ESPN_LEAGUE_ID=espn-league-id:latest,ESPN_TEAM_ID=espn-team-id:latest"
        in updates[0]
    )
    bindings = [c for c in calls if c.startswith("secrets add-iam-policy-binding")]
    assert [c.split()[2] for c in bindings] == ["espn-league-id", "espn-team-id"]
    assert calls.index(bindings[-1]) < calls.index(updates[0])  # access granted before use
