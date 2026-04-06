#!/usr/bin/env python3
import re
from pathlib import Path

TESTS_DIR = Path("atomic_key_tests").resolve()

RUN_SET_RE = re.compile(r"set\s+([A-Z0-9_]+)=([^&]+)", re.IGNORECASE)


def fix_run_line(line: str) -> str:
    """
    Convert Windows RUN line to Linux format
    """
    line = line.strip()

    if not line.startswith("RUN="):
        return line

    raw = line[len("RUN="):].strip()

    # extract all "set VAR=value"
    matches = RUN_SET_RE.findall(raw)

    env_parts = []
    for key, value in matches:
        env_parts.append(f"{key.strip()}={value.strip()}")

    # detect command
    if "py -3 atomic_test.py" in raw:
        cmd = "python3 atomic_test.py"
    elif "atomic_test.py" in raw:
        cmd = "python3 atomic_test.py"
    else:
        cmd = raw  # fallback (unlikely)

    return "RUN=" + " ".join(env_parts + [cmd])


def fix_file_urls(line: str) -> str:
    """
    Fix .pyo → .py if needed
    """
    if ".pyo" in line:
        return line.replace(".pyo", ".py")
    return line


def process_file(path: Path):
    print(f"[process] {path.name}")

    lines = path.read_text(encoding="utf-8").splitlines()
    new_lines = []

    for line in lines:
        line = fix_file_urls(line)
        line = fix_run_line(line)
        new_lines.append(line)

    new_text = "\n".join(new_lines) + "\n"
    path.write_text(new_text, encoding="utf-8")

    print(f"[fixed] {path.name}")


def main():
    if not TESTS_DIR.exists():
        print(f"[error] folder not found: {TESTS_DIR}")
        return

    files = sorted(TESTS_DIR.glob("*.txt"))

    if not files:
        print("[info] no .txt files found")
        return

    for f in files:
        process_file(f)

    print("\n[done] all files converted to Linux format")


if __name__ == "__main__":
    main()
