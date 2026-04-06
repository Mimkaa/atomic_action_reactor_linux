#!/usr/bin/env python3
import os
import sys
import time
import json
import asyncio
import subprocess
import importlib.util
import traceback
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from hold_registry import HOLD_ACTIONS, PRESS_RELEASE_ACTIONS, RELEASE_ACTIONS, ALL_ACTIONS


DEFAULT_ENV = {
    "TG_API_ID": "32181757",
    "TG_API_HASH": "24b6d6b108548ff41bb4d303dc768136",
    "TG_CHAT": "@input_agent_bot",
    "TG_SESSION_PATH": str(Path.home() / ".telethon_sessions" / "my_session.session"),
    "GITHUB_OWNER": "Mimkaa",
    "GITHUB_REPO": "actionsRepo",
    "GITHUB_REF": "main",
    "GITHUB_ACTIONS_SUBDIR": "keyActions",
}


def log(*parts):
    print(*parts, flush=True)


def ensure_linux():
    if not sys.platform.startswith("linux"):
        raise SystemExit("This runner is Linux only")


def normalize_session_path(raw: str) -> Path:
    raw = (raw or "").strip()
    if not raw:
        raise ValueError("TG_SESSION_PATH is empty")

    p = Path(raw).expanduser()
    if p.suffix.lower() != ".session":
        p = p.with_suffix(".session")
    return p


def ensure_telegram_session_ready():
    raw = (os.environ.get("TG_SESSION_PATH", "") or "").strip()
    if not raw:
        raw = DEFAULT_ENV["TG_SESSION_PATH"]

    session_path = normalize_session_path(raw)
    os.environ["TG_SESSION_PATH"] = str(session_path)

    session_path.parent.mkdir(parents=True, exist_ok=True)
    log(f"[telegram] ensured session folder: {session_path.parent}")

    if not session_path.exists():
        session_path.touch()
        log(f"[telegram] created empty session file: {session_path}")
    else:
        log(f"[telegram] session file already exists: {session_path}")

    return session_path


def ensure_env_vars():
    for key, value in DEFAULT_ENV.items():
        current = (os.environ.get(key, "") or "").strip()
        if current:
            continue
        os.environ[key] = value


def set_system_env_var(name: str, value: str):
    value = (value or "").strip()
    if not value:
        raise ValueError(f"Cannot set empty env var: {name}")

    os.environ[name] = value
    log(f"[env] {name}={value}")


def load_module(path: Path, name: str):
    if not path.exists():
        raise FileNotFoundError(f"Module file does not exist: {path}")

    spec = importlib.util.spec_from_file_location(name, str(path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load module spec from {path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def safe_json(x):
    return json.dumps(x, ensure_ascii=False)


def github_api_get_json(url: str):
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "atomic-test-runner",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def download_file(url: str, out_path: Path):
    out_path.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "atomic-test-runner"})
    with urllib.request.urlopen(req, timeout=60) as resp, open(out_path, "wb") as f:
        f.write(resp.read())


def download_github_folder(owner: str, repo: str, ref: str, repo_path: str, local_dir: Path):
    api_url = f"https://api.github.com/repos/{owner}/{repo}/contents/{repo_path}?ref={ref}"
    items = github_api_get_json(api_url)

    if isinstance(items, dict) and items.get("type") == "file":
        raise RuntimeError(f"Expected folder but got file at repo path: {repo_path}")

    if not isinstance(items, list):
        raise RuntimeError(f"Unexpected GitHub API response for path: {repo_path}")

    local_dir.mkdir(parents=True, exist_ok=True)

    for item in items:
        item_type = item.get("type")
        item_name = item.get("name")
        if not item_name:
            continue

        if item_type == "file":
            download_url = item.get("download_url")
            if not download_url:
                raise RuntimeError(f"No download_url for file: {item}")
            download_file(download_url, local_dir / item_name)

        elif item_type == "dir":
            child_repo_path = f"{repo_path}/{item_name}"
            child_local_dir = local_dir / item_name
            download_github_folder(owner, repo, ref, child_repo_path, child_local_dir)

        else:
            log(f"[github] skipping unsupported item type: {item_type} name={item_name}")


@dataclass
class AtomicResult:
    status: str
    detail: str
    exit_code: int = 0
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class AtomicContext:
    base_dir: Path
    action_name: str
    action_dir: Path
    runner_file: Path
    process: Optional[subprocess.Popen] = None
    artifacts: dict[str, Any] = field(default_factory=dict)


def send_telegram(text: str):
    try:
        from telethon import TelegramClient
    except Exception:
        return

    api_id_raw = (os.environ.get("TG_API_ID", "0") or "0").strip()
    api_hash = (os.environ.get("TG_API_HASH", "") or "").strip()
    chat = (os.environ.get("TG_CHAT", "") or "").strip()

    try:
        api_id = int(api_id_raw)
    except ValueError:
        return

    try:
        session_file = ensure_telegram_session_ready()
    except Exception:
        return

    if not (api_id and api_hash and chat):
        return

    async def send():
        client = TelegramClient(str(session_file), api_id, api_hash)
        await client.connect()
        try:
            if not await client.is_user_authorized():
                log("[telegram] session exists but is not authorized yet")
                return
            entity = await client.get_entity(chat)
            await client.send_message(entity, text)
        finally:
            await client.disconnect()

    asyncio.run(send())


def write_test_finished(path: Path, result: AtomicResult, ctx: AtomicContext):
    data = {
        "status": result.status,
        "detail": result.detail,
        "action": ctx.action_name,
        "expected_key": os.environ.get("EXPECTED_KEY"),
        "pid": "" if not ctx.process else ctx.process.pid,
        "time": time.time(),
        "extra": result.extra,
        "artifacts": ctx.artifacts,
    }

    text = "\n".join(f"{k}={safe_json(v)}" for k, v in data.items())
    path.write_text(text, encoding="utf-8")


def format_output(result: AtomicResult, ctx: AtomicContext):
    return (
        "[ATOMIC TEST]\n"
        f"Status: {result.status}\n"
        f"Detail: {result.detail}\n"
        f"Action: {ctx.action_name}\n"
        f"Key: {os.environ.get('EXPECTED_KEY', '')}\n"
        f"PID: {'' if not ctx.process else ctx.process.pid}"
    )


def ensure_action_available(base: Path, action: str):
    candidates = [
        base / action,
        base / "keyActions" / action,
    ]

    for action_dir in candidates:
        if action_dir.exists():
            log(f"[action] using local folder: {action_dir}")
            return action_dir, False

    owner = (os.environ.get("GITHUB_OWNER", "") or "").strip()
    repo = (os.environ.get("GITHUB_REPO", "") or "").strip()
    ref = (os.environ.get("GITHUB_REF", "main") or "main").strip()
    subdir = (os.environ.get("GITHUB_ACTIONS_SUBDIR", "keyActions") or "keyActions").strip().strip("/")

    if not owner or not repo:
        raise RuntimeError("Missing GITHUB_OWNER or GITHUB_REPO")

    repo_path = f"{subdir}/{action}"

    # download into base/keyActions/action to match the runner layout
    action_dir = base / subdir / action

    log(f"[github] downloading {owner}/{repo}@{ref}:{repo_path}")
    download_github_folder(owner, repo, ref, repo_path, action_dir)

    if not action_dir.exists():
        raise RuntimeError(f"Downloaded action folder not found after download: {action_dir}")

    return action_dir, True


def stop_process_if_needed(proc: Optional[subprocess.Popen]):
    if proc is None:
        return

    try:
        if proc.poll() is not None:
            return
    except Exception:
        return

    try:
        proc.terminate()
    except Exception:
        pass

    try:
        proc.wait(timeout=2)
        return
    except Exception:
        pass

    try:
        proc.kill()
    except Exception:
        pass

    try:
        proc.wait(timeout=2)
    except Exception:
        pass


def main():
    ensure_linux()
    ensure_env_vars()
    ensure_telegram_session_ready()

    action = (os.environ.get("ACTION_NAME", "") or "").strip()
    logic_file = (os.environ.get("TEST_LOGIC_FILE", "") or "").strip()
    fmt_file = (os.environ.get("OUTPUT_FORMAT_FILE", "") or "").strip()

    if not action:
        raise SystemExit("Missing ACTION_NAME")
    if not logic_file:
        raise SystemExit("Missing TEST_LOGIC_FILE")

    log(f"[debug] ACTION_NAME={action}")
    log(f"[debug] in HOLD_ACTIONS={action in HOLD_ACTIONS}")
    log(f"[debug] in PRESS_RELEASE_ACTIONS={action in PRESS_RELEASE_ACTIONS}")
    log(f"[debug] in RELEASE_ACTIONS={action in RELEASE_ACTIONS}")
    log(f"[debug] in ALL_ACTIONS={action in ALL_ACTIONS}")

    key = ALL_ACTIONS.get(action)
    if not key:
        raise SystemExit(f"Unknown action (not in registry): {action}")

    set_system_env_var("EXPECTED_KEY", key)
    log(f"[registry] action='{action}' -> key='{key}'")

    base = Path(__file__).resolve().parent
    finished = base / ".test_finished"

    logic_path = Path(logic_file).expanduser()
    if not logic_path.is_absolute():
        logic_path = base / logic_path

    downloaded_now = False
    ctx = None
    exit_code = 1
    should_cleanup_process = True

    try:
        action_dir, downloaded_now = ensure_action_available(base, action)

        runner = action_dir / "run_RunClass.py"
        if not runner.exists():
            raise FileNotFoundError(f"run_RunClass.py not found in action folder: {runner}")

        ctx = AtomicContext(
            base_dir=base,
            action_name=action,
            action_dir=action_dir,
            runner_file=runner,
        )

        logic = load_module(logic_path, "logic")

        if not hasattr(logic, "run_test_logic"):
            raise AttributeError(f"{logic_path} must define run_test_logic(ctx)")

        result = logic.run_test_logic(ctx)

        if not isinstance(result, AtomicResult):
            raise RuntimeError("Invalid result")

        if ctx.process:
            ctx.artifacts["pid"] = ctx.process.pid

        ctx.artifacts["downloaded_now"] = downloaded_now
        ctx.artifacts["action_dir"] = str(action_dir)

        text = format_output(result, ctx)

        if fmt_file:
            fmt_path = Path(fmt_file).expanduser()
            if not fmt_path.is_absolute():
                fmt_path = base / fmt_path

            fmt = load_module(fmt_path, "fmt")
            if not hasattr(fmt, "format_output"):
                raise AttributeError(f"{fmt_path} must define format_output(result, ctx)")
            text = fmt.format_output(result, ctx)

        send_telegram(text)
        write_test_finished(finished, result, ctx)

        exit_code = result.exit_code

        is_hold_action = action in HOLD_ACTIONS
        should_cleanup_process = not (exit_code == 0 and is_hold_action)

    except Exception as e:
        err_text = "".join(traceback.format_exception_only(type(e), e)).strip()

        if ctx is None:
            fallback_action_dir = (base / "keyActions" / action) if action else base
            ctx = AtomicContext(
                base_dir=base,
                action_name=action,
                action_dir=fallback_action_dir,
                runner_file=fallback_action_dir / "run_RunClass.py",
            )

        err = AtomicResult("FAIL", err_text, 1)
        ctx.artifacts["downloaded_now"] = downloaded_now

        try:
            send_telegram(format_output(err, ctx))
        except Exception:
            pass

        try:
            write_test_finished(finished, err, ctx)
        except Exception:
            pass

        exit_code = 1
        should_cleanup_process = True

    finally:
        if ctx is not None and should_cleanup_process:
            stop_process_if_needed(ctx.process)

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
