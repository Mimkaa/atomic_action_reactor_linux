#!/usr/bin/env python3
import os
import sys
import time
import shlex
import json
import subprocess
import urllib.request
from pathlib import Path

TESTS_DIR = Path("tests_to_run").resolve()
ATOMIC_KEY_TESTS_DIR = Path("atomic_key_tests").resolve()
WORK_DIR = Path("downloaded_test_runtime").resolve()

POLL_SEC = 2.0

GITHUB_OWNER = "Mimkaa"
GITHUB_TEST_REPO = "TestRepo"
GITHUB_ACTIONS_REPO = "actionsRepo"
GITHUB_REF = "main"

TEST_REPO_BASE = f"https://raw.githubusercontent.com/{GITHUB_OWNER}/{GITHUB_TEST_REPO}/{GITHUB_REF}/key_press_tests"
GITHUB_API_BASE = f"https://api.github.com/repos/{GITHUB_OWNER}"

COMMON_TEST_FILES = [
    "atomic_test.py",
    "hold_registry.py",
]


def ensure_linux():
    if not sys.platform.startswith("linux"):
        raise SystemExit("This runner is Linux only")


def log(*parts):
    print(*parts, flush=True)


def read_trigger_test_name(path: Path) -> str:
    raw_text = path.read_text(encoding="utf-8").strip()
    log(f"[debug] raw trigger content of {path.name}:\n{raw_text}")

    if not raw_text:
        raise ValueError(f"Empty trigger file: {path.name}")

    first_line = raw_text.splitlines()[0].strip()
    if not first_line:
        raise ValueError(f"Empty first line in trigger file: {path.name}")

    return first_line


def resolve_definition_file(test_name: str) -> Path:
    filename = test_name if test_name.endswith(".txt") else f"{test_name}.txt"
    path = ATOMIC_KEY_TESTS_DIR / filename

    if not path.exists():
        raise FileNotFoundError(f"Definition file not found: {path}")

    return path


def parse_definition_file(path: Path):
    raw_text = path.read_text(encoding="utf-8").strip()
    log(f"[debug] raw definition content of {path.name}:\n{raw_text}")

    if not raw_text:
        raise ValueError(f"Empty definition file: {path.name}")

    file_urls = []
    run_cmd = None

    for raw_line in raw_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        if line.startswith("FILE_URL="):
            url = line[len("FILE_URL="):].strip()
            if url:
                file_urls.append(url)

        elif line.startswith("RUN="):
            run_cmd = line[len("RUN="):].strip()

    if not run_cmd:
        raise ValueError(f"No RUN= line found in {path.name}")

    return file_urls, run_cmd


def parse_linux_env_run(run_cmd: str):
    """
    Parses:
      ACTION_NAME=program_that_holds_zero_key TEST_LOGIC_FILE=logic_hold_key.py HOLD_TIME_SEC=5 python3 atomic_test.py

    into:
      env_updates = {...}
      cmd = ["python3", "atomic_test.py"]
    """
    parts = shlex.split(run_cmd)
    env_updates = {}
    cmd = []

    for part in parts:
        if not cmd and "=" in part:
            key, value = part.split("=", 1)
            if key and all(c.isalnum() or c == "_" for c in key):
                env_updates[key] = value
                continue
        cmd.append(part)

    if not cmd:
        raise ValueError(f"RUN command has no executable part: {run_cmd}")

    return env_updates, cmd


def normalize_command_for_linux(cmd):
    if not cmd:
        raise ValueError("Empty command")

    exe = cmd[0].lower()

    if exe in ("python", "python3", "py"):
        rest = cmd[1:]

        if exe == "py" and rest[:1] == ["-3"]:
            rest = rest[1:]

        return [sys.executable] + rest

    return cmd


def download_binary(url: str, dest: Path):
    dest.parent.mkdir(parents=True, exist_ok=True)

    if dest.exists():
        log(f"[skip-download] already exists: {dest}")
        return

    log(f"[download] {url} -> {dest}")
    req = urllib.request.Request(url, headers={"User-Agent": "atomic-test-runner"})
    with urllib.request.urlopen(req, timeout=60) as resp, open(dest, "wb") as f:
        f.write(resp.read())


def github_raw_url_for_test_file(filename: str) -> str:
    return f"{TEST_REPO_BASE}/{filename}"


def github_folder_api_url(repo: str, subdir: str) -> str:
    return f"{GITHUB_API_BASE}/{repo}/contents/{subdir}?ref={GITHUB_REF}"


def download_github_folder(repo: str, subdir: str, dest_root: Path):
    """
    Recursively downloads repo/subdir into dest_root/subdir/...
    """
    api_url = github_folder_api_url(repo, subdir)
    req = urllib.request.Request(api_url, headers={"User-Agent": "atomic-test-runner"})

    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    if not isinstance(data, list):
        raise ValueError(f"Unexpected GitHub API response for {subdir}: {data}")

    for item in data:
        item_type = item.get("type")
        item_path = item.get("path")
        item_name = item.get("name")
        item_download_url = item.get("download_url")

        if item_type == "file":
            rel_path = Path(item_path)
            dest = dest_root / rel_path
            download_binary(item_download_url, dest)

        elif item_type == "dir":
            download_github_folder(repo, item_path, dest_root)


def derive_release_action_name(action_name: str) -> str | None:
    prefix = "program_that_holds_"
    suffix = "_key"

    if action_name.startswith(prefix) and action_name.endswith(suffix):
        middle = action_name[len(prefix):-len(suffix)]
        if middle:
            return f"program_that_releases_{middle}_key"

    return None


def ensure_runtime_files(env_updates: dict, work_dir: Path):
    work_dir.mkdir(parents=True, exist_ok=True)

    # Common files
    for filename in COMMON_TEST_FILES:
        url = github_raw_url_for_test_file(filename)
        dest = work_dir / filename
        download_binary(url, dest)

    # Requested logic file
    logic_file = (env_updates.get("TEST_LOGIC_FILE", "") or "").strip()
    if logic_file:
        url = github_raw_url_for_test_file(logic_file)
        dest = work_dir / logic_file
        download_binary(url, dest)

    # Hold action folder
    action_name = (env_updates.get("ACTION_NAME", "") or "").strip()
    if action_name:
        action_folder = work_dir / "keyActions" / action_name
        if not action_folder.exists():
            log(f"[github] downloading hold action folder: keyActions/{action_name}")
            download_github_folder(
                GITHUB_ACTIONS_REPO,
                f"keyActions/{action_name}",
                work_dir,
            )
        else:
            log(f"[skip-download] hold action folder already exists: {action_folder}")

        # Matching release action folder
        release_action_name = derive_release_action_name(action_name)
        if release_action_name:
            release_folder = work_dir / "keyActions" / release_action_name
            if not release_folder.exists():
                log(f"[github] downloading matching release folder: keyActions/{release_action_name}")
                download_github_folder(
                    GITHUB_ACTIONS_REPO,
                    f"keyActions/{release_action_name}",
                    work_dir,
                )
            else:
                log(f"[skip-download] release action folder already exists: {release_folder}")


def run_cmd_command(run_cmd: str, work_dir: Path):
    env_updates, cmd = parse_linux_env_run(run_cmd)
    cmd = normalize_command_for_linux(cmd)

    ensure_runtime_files(env_updates, work_dir)

    env = os.environ.copy()
    env.update(env_updates)

    log(f"[run] cwd={work_dir}")
    log(f"[run] env={env_updates}")
    log(f"[run] cmd={' '.join(cmd)}")

    completed = subprocess.run(
        cmd,
        cwd=str(work_dir),
        env=env,
        text=True,
    )
    return completed.returncode


def process_file(path: Path):
    log(f"\n[process] {path.name}")

    try:
        test_name = read_trigger_test_name(path)
        definition_file = resolve_definition_file(test_name)
        log(f"[lookup] using definition file: {definition_file}")

        file_urls, run_cmd = parse_definition_file(definition_file)
        log("[info] ignoring FILE_URL lines; runtime files/actions are derived from RUN")
        code = run_cmd_command(run_cmd, WORK_DIR)
        log(f"[done] exit_code={code}")

    except Exception as e:
        log(f"[error] {e}")

    finally:
        try:
            path.unlink()
            log(f"[cleanup] deleted trigger file {path.name}")
        except FileNotFoundError:
            pass
        except Exception as e:
            log(f"[cleanup-error] {e}")


def main():
    ensure_linux()

    TESTS_DIR.mkdir(parents=True, exist_ok=True)
    ATOMIC_KEY_TESTS_DIR.mkdir(parents=True, exist_ok=True)
    WORK_DIR.mkdir(parents=True, exist_ok=True)

    log(f"[watching] triggers: {TESTS_DIR}")
    log(f"[lookup-dir] definitions: {ATOMIC_KEY_TESTS_DIR}")
    log(f"[work-dir] runtime: {WORK_DIR}")

    while True:
        try:
            files = sorted(TESTS_DIR.glob("*.txt"))
            for f in files:
                process_file(f)
            time.sleep(POLL_SEC)

        except KeyboardInterrupt:
            log("Stopped.")
            break
        except Exception as e:
            log(f"[loop-error] {e}")
            time.sleep(POLL_SEC)


if __name__ == "__main__":
    main()
