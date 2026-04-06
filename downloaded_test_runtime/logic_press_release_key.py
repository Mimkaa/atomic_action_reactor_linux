#!/usr/bin/env python3
import os
import sys
import time
import subprocess
from pathlib import Path


def derive_expected_key() -> str:
    expected_key = (os.environ.get("EXPECTED_KEY", "") or "").strip().lower()
    if expected_key:
        return expected_key

    action_name = (os.environ.get("ACTION_NAME", "") or "").strip().lower()
    prefix = "program_that_press_release_"
    suffix = "_key"

    if action_name.startswith(prefix) and action_name.endswith(suffix):
        middle = action_name[len(prefix):-len(suffix)]
        if middle:
            return middle

    return ""


def find_runner_file(ctx) -> tuple[Path | None, Path | None]:
    action_name = (os.environ.get("ACTION_NAME", "") or "").strip()
    candidates: list[tuple[Path, Path]] = []

    try:
        runner = Path(ctx.runner_file).resolve()
        action_dir = Path(ctx.action_dir).resolve()
        candidates.append((runner, action_dir))
    except Exception:
        pass

    try:
        base = Path(ctx.runner_file).resolve().parent
        candidates.append((base / "run_RunClass.py", base))
    except Exception:
        pass

    if action_name:
        candidates.append(
            (Path.cwd() / action_name / "run_RunClass.py", Path.cwd() / action_name)
        )
        candidates.append(
            (Path.cwd() / "keyActions" / action_name / "run_RunClass.py", Path.cwd() / "keyActions" / action_name)
        )

    here = Path(__file__).resolve().parent
    if action_name:
        candidates.append(
            (here / action_name / "run_RunClass.py", here / action_name)
        )
        candidates.append(
            (here / "keyActions" / action_name / "run_RunClass.py", here / "keyActions" / action_name)
        )

    if action_name:
        candidates.append(
            (Path.cwd() / "downloaded_test_runtime" / action_name / "run_RunClass.py",
             Path.cwd() / "downloaded_test_runtime" / action_name)
        )
        candidates.append(
            (Path.cwd() / "downloaded_test_runtime" / "keyActions" / action_name / "run_RunClass.py",
             Path.cwd() / "downloaded_test_runtime" / "keyActions" / action_name)
        )
        candidates.append(
            (here / "downloaded_test_runtime" / action_name / "run_RunClass.py",
             here / "downloaded_test_runtime" / action_name)
        )
        candidates.append(
            (here / "downloaded_test_runtime" / "keyActions" / action_name / "run_RunClass.py",
             here / "downloaded_test_runtime" / "keyActions" / action_name)
        )

    seen = set()
    for runner, action_dir in candidates:
        key = (str(runner), str(action_dir))
        if key in seen:
            continue
        seen.add(key)
        if runner.exists():
            return runner.resolve(), action_dir.resolve()

    return None, None


def run_test_logic(ctx):
    AtomicResult = sys.modules["__main__"].AtomicResult

    expected_key = derive_expected_key()
    timeout_sec = float(os.environ.get("TEST_DURATION_SEC", "10.0"))
    poll_sec = float(os.environ.get("MONITOR_POLL_SEC", "0.01"))
    launch_settle_sec = float(os.environ.get("LAUNCH_SETTLE_SEC", "0.10"))
    min_runtime_sec = float(os.environ.get("MIN_RUNTIME_SEC", "0.02"))
    python_exe = (os.environ.get("PYTHON_EXE", "") or "").strip() or sys.executable
    capture_limit = int(os.environ.get("PROCESS_OUTPUT_LIMIT", "4000"))

    if os.name == "nt":
        return AtomicResult("FAIL", "This logic file is Unix/Linux only", 1)

    if not expected_key:
        return AtomicResult("FAIL", "EXPECTED_KEY missing and could not infer it from ACTION_NAME", 1)

    runner, action_dir = find_runner_file(ctx)
    if runner is None or action_dir is None:
        return AtomicResult(
            "FAIL",
            "Could not locate run_RunClass.py for press-release action",
            1,
            extra={
                "ctx_runner_file": str(getattr(ctx, "runner_file", "")),
                "ctx_action_dir": str(getattr(ctx, "action_dir", "")),
                "cwd": str(Path.cwd()),
                "action_name": (os.environ.get("ACTION_NAME", "") or "").strip(),
            },
        )

    start_time = time.time()

    proc = subprocess.Popen(
        [python_exe, str(runner)],
        cwd=str(action_dir),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    ctx.process = proc

    print(f"[test] started pid={proc.pid}", flush=True)
    print(f"[test] runner={runner}", flush=True)
    print(f"[test] action_dir={action_dir}", flush=True)
    print(f"[test] waiting for process to perform press+release behavior for '{expected_key}'", flush=True)

    if launch_settle_sec > 0:
        time.sleep(launch_settle_sec)

    rc = proc.poll()
    if rc is not None:
        runtime = time.time() - start_time
        stdout, stderr = proc.communicate()
        stdout = (stdout or "")[:capture_limit]
        stderr = (stderr or "")[:capture_limit]

        if runtime < min_runtime_sec:
            return AtomicResult(
                "FAIL",
                f"Action process exited too quickly for '{expected_key}'",
                1,
                extra={
                    "pid": proc.pid,
                    "returncode": rc,
                    "runtime_sec": runtime,
                    "min_runtime_sec": min_runtime_sec,
                    "runner": str(runner),
                    "action_dir": str(action_dir),
                    "stdout": stdout,
                    "stderr": stderr,
                },
            )

        if rc != 0:
            return AtomicResult(
                "FAIL",
                f"Process for key '{expected_key}' exited with non-zero code {rc} after {runtime:.3f}s",
                1,
                extra={
                    "pid": proc.pid,
                    "returncode": rc,
                    "runtime_sec": runtime,
                    "runner": str(runner),
                    "action_dir": str(action_dir),
                    "stdout": stdout,
                    "stderr": stderr,
                },
            )

        return AtomicResult(
            "PASS",
            f"Process for key '{expected_key}' started and exited normally in {runtime:.3f}s",
            0,
            extra={
                "pid": proc.pid,
                "returncode": rc,
                "runtime_sec": runtime,
                "runner": str(runner),
                "action_dir": str(action_dir),
                "stdout": stdout,
                "stderr": stderr,
            },
        )

    deadline = time.time() + timeout_sec

    while time.time() < deadline:
        rc = proc.poll()
        if rc is not None:
            runtime = time.time() - start_time
            stdout, stderr = proc.communicate()
            stdout = (stdout or "")[:capture_limit]
            stderr = (stderr or "")[:capture_limit]

            if runtime < min_runtime_sec:
                return AtomicResult(
                    "FAIL",
                    f"Action process exited too quickly for '{expected_key}'",
                    1,
                    extra={
                        "pid": proc.pid,
                        "returncode": rc,
                        "runtime_sec": runtime,
                        "min_runtime_sec": min_runtime_sec,
                        "runner": str(runner),
                        "action_dir": str(action_dir),
                        "stdout": stdout,
                        "stderr": stderr,
                    },
                )

            if rc != 0:
                return AtomicResult(
                    "FAIL",
                    f"Process for key '{expected_key}' exited with non-zero code {rc} after {runtime:.3f}s",
                    1,
                    extra={
                        "pid": proc.pid,
                        "returncode": rc,
                        "runtime_sec": runtime,
                        "runner": str(runner),
                        "action_dir": str(action_dir),
                        "stdout": stdout,
                        "stderr": stderr,
                    },
                )

            return AtomicResult(
                "PASS",
                f"Process for key '{expected_key}' started and exited normally in {runtime:.3f}s",
                0,
                extra={
                    "pid": proc.pid,
                    "returncode": rc,
                    "runtime_sec": runtime,
                    "runner": str(runner),
                    "action_dir": str(action_dir),
                    "stdout": stdout,
                    "stderr": stderr,
                },
            )

        time.sleep(poll_sec)

    try:
        proc.terminate()
    except Exception:
        pass

    return AtomicResult(
        "FAIL",
        f"Timeout after {timeout_sec}s: press-release action for '{expected_key}' did not finish",
        1,
        extra={
            "pid": proc.pid,
            "returncode": proc.poll(),
            "timeout_sec": timeout_sec,
            "runner": str(runner),
            "action_dir": str(action_dir),
       },
    )
