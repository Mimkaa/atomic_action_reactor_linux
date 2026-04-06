# run_RunClass.py
#
# OFFLINE-SAFE runner:
# - assumes RunClass.class is already present in this folder
# - reads "created_outputs.json" to obtain "dynamic_class_creator_class"
# - runs:
#     java -cp <THIS_DIR and all jars> RunClass --class <target>
#
# Usage:
#   python run_RunClass.py
#
# Optional env:
#   JAVA_BIN=java

import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CREATED_JSON = HERE / "created_outputs.json"
RUNCLASS_CLASS = HERE / "RunClass.class"


def read_payload():
    if not CREATED_JSON.exists():
        raise SystemExit(f"[ERR] missing {CREATED_JSON}")
    try:
        obj = json.loads(CREATED_JSON.read_text(encoding="utf-8"))
    except Exception as e:
        raise SystemExit(f"[ERR] invalid JSON in {CREATED_JSON}: {e}")
    if not isinstance(obj, dict):
        raise SystemExit(f"[ERR] expected dict JSON in {CREATED_JSON}")
    return obj


def normalize_class_arg(s: str) -> str:
    s = s.strip()
    if s.lower().endswith(".class"):
        s = s[:-6]
    return s


def build_classpath() -> str:
    sep = ";" if os.name == "nt" else ":"
    return sep.join([".", "./*"])


def main():
    if not RUNCLASS_CLASS.exists():
        raise SystemExit("[ERR] RunClass.class missing in this folder; it must be copied into executorOutput during packaging.")

    payload = read_payload()
    dyn = payload.get("dynamic_class_creator_class")
    if not isinstance(dyn, str) or not dyn.strip():
        raise SystemExit("[ERR] dynamic_class_creator_class missing/null in created_outputs.json")

    target = normalize_class_arg(dyn)

    java_bin = os.getenv("JAVA_BIN", "java")
    cp = build_classpath()
    cmd = [java_bin, "-cp", cp, "RunClass", "--class", target]

    print("[RUN]", " ".join(cmd), flush=True)

    res = subprocess.run(
        cmd,
        cwd=str(HERE),
    )
    raise SystemExit(res.returncode)


if __name__ == "__main__":
    main()
