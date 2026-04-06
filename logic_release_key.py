#!/usr/bin/env python3
import os
import sys
import time
import signal
import subprocess
from pathlib import Path


def process_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except Exception:
        return False


def read_proc_name(pid: int) -> str:
    try:
        return Path(f"/proc/{pid}/comm").read_text(encoding="utf-8").strip()
    except Exception:
        return ""


def get_all_pids() -> list[int]:
    out = []
    proc = Path("/proc")
    for entry in proc.iterdir():
        if entry.is_dir() and entry.name.isdigit():
            try:
                out.append(int(entry.name))
            except Exception:
                pass
    return out


def get_ppid(pid: int) -> int | None:
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
        parts = stat.split()
        if len(parts) >= 4:
            return int(parts[3])
    except Exception:
        pass
    return None


def build_ppid_map() -> dict[int, list[int]]:
    children: dict[int, list[int]] = {}
    for pid in get_all_pids():
        ppid = get_ppid(pid)
        if ppid is None:
            continue
        children.setdefault(ppid, []).append(pid)
    return children


def collect_descendants(root_pid: int) -> list[int]:
    children_map = build_ppid_map()
    result = []
    stack = [root_pid]
    seen = set()

    while stack:
        current = stack.pop()
        for child in children_map.get(current, []):
            if child not in seen:
                seen.add(child)
                result.append(child)
                stack.append(child)

    return result


def sort_deepest_first(root_pid: int, pids: list[int]) -> list[int]:
    children_map = build_ppid_map()
    depth: dict[int, int] = {}

    stack = [(root_pid, 0)]
    seen = set()
    while stack:
        current, d = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        depth[current] = d
        for child in children_map.get(current, []):
            stack.append((child, d + 1))

    return sorted(pids, key=lambda p: depth.get(p, 0), reverse=True)


def filter_java_pids(pids: list[int]) -> list[int]:
    return [pid for pid in pids if read_proc_name(pid).lower() == "java"]


def unique_keep_order(items: list[int]) -> list[int]:
    out = []
    seen = set()
    for x in items:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def kill_many(pids: list[int], sig: int):
    for pid in pids:
        try:
            os.kill(pid, sig)
        except ProcessLookupError:
            pass
        except PermissionError:
            pass
        except Exception:
            pass


def signal_process_group(pid: int, sig: int) -> bool:
    try:
        pgid = os.getpgid(pid)
        if pgid <= 1:
            return False
        os.killpg(pgid, sig)
        return True
    except Exception:
        return False


def wait_until_all_gone(pids: list[int], timeout_sec: float, poll_sec: float = 0.05) -> bool:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        alive = [pid for pid in pids if process_exists(pid)]
        if not alive:
            return True
        time.sleep(poll_sec)
    return not any(process_exists(pid) for pid in pids)


def derive_expected_key() -> str:
    expected_key = (os.environ.get("EXPECTED_KEY", "") or "").strip().lower()
    if expected_key:
        return expected_key

    action_name = (os.environ.get("ACTION_NAME", "") or "").strip().lower()
    prefix = "program_that_holds_"
    suffix = "_key"

    if action_name.startswith(prefix) and action_name.endswith(suffix):
        middle = action_name[len(prefix):-len(suffix)]
        if middle:
            return middle

    return ""


def find_release_action_dir(expected_key: str) -> Path | None:
    folder_name = f"program_that_releases_{expected_key}_key"

    candidates = [
        Path.cwd() / folder_name,
        Path.cwd() / "keyActions" / folder_name,
        Path(__file__).resolve().parent / folder_name,
        Path(__file__).resolve().parent / "keyActions" / folder_name,
        Path.cwd() / "downloaded_test_runtime" / folder_name,
        Path.cwd() / "downloaded_test_runtime" / "keyActions" / folder_name,
        Path(__file__).resolve().parent / "downloaded_test_runtime" / folder_name,
        Path(__file__).resolve().parent / "downloaded_test_runtime" / "keyActions" / folder_name,
    ]

    for candidate in candidates:
        runner = candidate / "run_RunClass.py"
        if runner.exists():
            return candidate.resolve()

    return None


def try_release_action(expected_key: str) -> tuple[bool, str, str | None]:
    action_dir = find_release_action_dir(expected_key)
    if action_dir is None:
        return False, f"Release action folder not found for key '{expected_key}'", None

    runner = action_dir / "run_RunClass.py"
    if not runner.exists():
        return False, f"run_RunClass.py not found in {action_dir}", str(action_dir)

    try:
        result = subprocess.run(
            [sys.executable, str(runner)],
            cwd=str(action_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=float(os.environ.get("RELEASE_ACTION_TIMEOUT_SEC", "3.0")),
        )

        stdout = (result.stdout or "").strip()
        stderr = (result.stderr or "").strip()

        if result.returncode == 0:
            detail = "Release action executed successfully"
            if stdout:
                detail += f"; stdout={stdout!r}"
            return True, detail, str(action_dir)

        detail = f"Release action failed with code {result.returncode}"
        if stdout:
            detail += f"; stdout={stdout!r}"
        if stderr:
            detail += f"; stderr={stderr!r}"
        return False, detail, str(action_dir)

    except subprocess.TimeoutExpired:
        return False, "Release action timed out", str(action_dir)
    except Exception as e:
        return False, f"Release action crashed: {e}", str(action_dir)


def kill_holder_tree(root_pid: int, term_wait_sec: float, kill_wait_sec: float):
    initial_descendants = collect_descendants(root_pid)
    java_descendants = filter_java_pids(initial_descendants)
    ordered_descendants = sort_deepest_first(root_pid, initial_descendants)
    all_targets = unique_keep_order(ordered_descendants + [root_pid])

    term_group_sent = signal_process_group(root_pid, signal.SIGTERM)
    kill_many(java_descendants, signal.SIGTERM)
    kill_many(ordered_descendants, signal.SIGTERM)
    kill_many([root_pid], signal.SIGTERM)

    exited_after_term = wait_until_all_gone(all_targets, term_wait_sec)
    kill_sent = False
    kill_group_sent = False

    if not exited_after_term:
        kill_sent = True

        refreshed_descendants = collect_descendants(root_pid) if process_exists(root_pid) else []
        refreshed_java_descendants = filter_java_pids(refreshed_descendants)
        refreshed_ordered_descendants = sort_deepest_first(root_pid, refreshed_descendants)
        refreshed_targets = unique_keep_order(
            refreshed_ordered_descendants + ([root_pid] if process_exists(root_pid) else [])
        )

        kill_group_sent = signal_process_group(root_pid, signal.SIGKILL)
        kill_many(refreshed_java_descendants, signal.SIGKILL)
        kill_many(refreshed_ordered_descendants, signal.SIGKILL)
        if process_exists(root_pid):
            kill_many([root_pid], signal.SIGKILL)

        exited_after_kill = wait_until_all_gone(refreshed_targets, kill_wait_sec)
        if not exited_after_kill:
            still_alive = [pid for pid in refreshed_targets if process_exists(pid)]
            return False, {
                "still_alive": still_alive,
                "java_descendants": java_descendants,
                "term_group_sent": term_group_sent,
                "kill_group_sent": kill_group_sent,
                "kill_sent": kill_sent,
            }

    return True, {
        "java_descendants": java_descendants,
        "term_group_sent": term_group_sent,
        "kill_group_sent": kill_group_sent,
        "kill_sent": kill_sent,
    }


def run_test_logic(ctx):
    AtomicResult = sys.modules["__main__"].AtomicResult

    expected_key = derive_expected_key()
    term_wait_sec = float(os.environ.get("TERMINATE_WAIT_SEC", "2.0"))
    kill_wait_sec = float(os.environ.get("KILL_WAIT_SEC", "2.0"))
    after_release_sleep_sec = float(os.environ.get("POST_RELEASE_ACTION_SLEEP_SEC", "0.30"))
    pid_dir_raw = (os.environ.get("HOLD_PID_DIR", "") or "").strip() or "/tmp/hold_system"
    pid_dir = Path(pid_dir_raw)

    if not sys.platform.startswith("linux"):
        return AtomicResult("FAIL", "This logic file is Linux only", 1)

    if not expected_key:
        return AtomicResult(
            "FAIL",
            "EXPECTED_KEY missing and could not infer key from ACTION_NAME",
            1,
        )

    pid_file = pid_dir / f"hold_{expected_key}.pid"

    if not pid_file.exists():
        return AtomicResult(
            "PASS",
            f"Key '{expected_key}' already released (pid file not found: {pid_file})",
            0,
            extra={"pid_file": str(pid_file), "already_released": True},
        )

    try:
        root_pid = int(pid_file.read_text(encoding="utf-8").strip())
    except Exception as e:
        try:
            pid_file.unlink(missing_ok=True)
        except Exception:
            pass
        return AtomicResult(
            "FAIL",
            f"Could not read PID from {pid_file}: {e}",
            1,
            extra={"pid_file": str(pid_file)},
        )

    release_action_ok = False
    release_action_msg = "not attempted"
    release_action_dir = None

    release_action_ok, release_action_msg, release_action_dir = try_release_action(expected_key)

    if release_action_ok:
        time.sleep(after_release_sleep_sec)

    if process_exists(root_pid):
        kill_ok, kill_info = kill_holder_tree(root_pid, term_wait_sec, kill_wait_sec)
        if not kill_ok:
            return AtomicResult(
                "FAIL",
                f"Release action result: {release_action_msg}; process tree for key '{expected_key}' did not fully exit",
                1,
                extra={
                    "root_pid": root_pid,
                    "pid_file": str(pid_file),
                    "release_action_ok": release_action_ok,
                    "release_action_msg": release_action_msg,
                    "release_action_dir": release_action_dir,
                    "terminate_wait_sec": term_wait_sec,
                    "kill_wait_sec": kill_wait_sec,
                    **kill_info,
                },
            )
        kill_info_final = kill_info
    else:
        kill_info_final = {
            "java_descendants": [],
            "term_group_sent": False,
            "kill_group_sent": False,
            "kill_sent": False,
            "holder_already_dead_before_kill": True,
        }

    try:
        pid_file.unlink(missing_ok=True)
    except Exception as e:
        return AtomicResult(
            "FAIL",
            f"Released key '{expected_key}' but failed to remove pid file: {e}",
            1,
            extra={
                "root_pid": root_pid,
                "pid_file": str(pid_file),
                "release_action_ok": release_action_ok,
                "release_action_msg": release_action_msg,
                "release_action_dir": release_action_dir,
            },
        )

    detail = f"Released key '{expected_key}'"

    if release_action_ok:
        detail += " using release action first"
    else:
        detail += f" with release action fallback failure: {release_action_msg}"

    detail += f"; killed PID {root_pid}"
    if kill_info_final.get("java_descendants"):
        detail += f" and targeted java descendants {kill_info_final['java_descendants']}"

    if kill_info_final.get("kill_sent"):
        detail += " (required SIGKILL)"
    else:
        detail += " (SIGTERM was enough)"

    return AtomicResult(
        "PASS",
        detail,
        0,
        extra={
            "root_pid": root_pid,
            "pid_file": str(pid_file),
            "release_action_ok": release_action_ok,
            "release_action_msg": release_action_msg,
            "release_action_dir": release_action_dir,
            **kill_info_final,
        },
    )
