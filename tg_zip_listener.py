#!/usr/bin/env python3
import os
import re
import sys
import asyncio
from pathlib import Path
from typing import Optional

from telethon import TelegramClient
from telethon.tl.types import Message, DocumentAttributeFilename

# =========================
# PLATFORM CHECK
# =========================
if not sys.platform.startswith("linux"):
    raise SystemExit("This prompt poller is Linux only")

# =========================
# PATHS
# =========================
BASE_DIR = Path(__file__).resolve().parent

# =========================
# CONFIG
# =========================
API_ID_RAW = (os.environ.get("TG_API_ID", "") or "").strip()
API_HASH = (os.environ.get("TG_API_HASH", "") or "").strip()

SESSION_PATH = BASE_DIR / "prompt_poller.session"
LAST_SEEN_FILE = BASE_DIR / ".prompt_poller_last_seen"

CHAT = (os.environ.get("TG_CHAT", "") or "").strip()

POLL_SEC = float((os.environ.get("POLL_SEC", "1.0") or "1.0").strip())
DELETE_AFTER_PICK = (os.environ.get("DELETE_AFTER_PICK", "1") or "1").strip().lower() in ("1", "true", "yes")
ACCEPT_OUTGOING = (os.environ.get("ACCEPT_OUTGOING", "1") or "1").strip().lower() in ("1", "true", "yes")

if not API_ID_RAW or not API_HASH:
    raise SystemExit("Missing TG_API_ID / TG_API_HASH")

if not CHAT:
    raise SystemExit("Missing TG_CHAT")

API_ID = int(API_ID_RAW)

TARGET_DIR = BASE_DIR / "tests_to_run"
TARGET_DIR.mkdir(parents=True, exist_ok=True)

TEXT_MIME_TYPES = {
    "text/plain",
    "text/markdown",
    "application/json",
}

ALLOWED_EXTENSIONS = {".txt", ".md", ".json"}


# =========================
# HELPERS
# =========================
def sanitize_name(name: str) -> str:
    name = (name or "").strip()
    if not name:
        return "prompt"
    name = re.sub(r'[<>:"/\\|?*\x00-\x1F]+', "_", name)
    name = re.sub(r"\s+", "_", name)
    name = name.strip("._")
    return name or "prompt"


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path

    i = 1
    while True:
        candidate = path.with_name(f"{path.stem}_{i}{path.suffix}")
        if not candidate.exists():
            return candidate
        i += 1


def get_filename_from_message(m: Message) -> str:
    doc = getattr(m, "document", None)
    if not doc:
        return f"prompt_{m.id}.txt"

    for attr in getattr(doc, "attributes", []) or []:
        if isinstance(attr, DocumentAttributeFilename):
            name = (attr.file_name or "").strip()
            if name:
                return name

    return f"prompt_{m.id}.txt"


def is_allowed_prompt_file(m: Message) -> bool:
    if not isinstance(m, Message):
        return False

    if not ACCEPT_OUTGOING and getattr(m, "out", False):
        return False

    doc = getattr(m, "document", None)
    if not doc:
        return False

    mime_type = (getattr(doc, "mime_type", "") or "").lower().strip()
    if mime_type in TEXT_MIME_TYPES:
        return True

    filename = get_filename_from_message(m).lower()
    return Path(filename).suffix in ALLOWED_EXTENSIONS


def has_text_prompt(m: Message) -> bool:
    if not isinstance(m, Message):
        return False

    if not ACCEPT_OUTGOING and getattr(m, "out", False):
        return False

    text = (getattr(m, "message", "") or "").strip()
    return bool(text)


def load_last_seen_id() -> Optional[int]:
    try:
        raw = LAST_SEEN_FILE.read_text(encoding="utf-8").strip()
        if not raw:
            return None
        return int(raw)
    except Exception:
        return None


def save_last_seen_id(msg_id: int):
    LAST_SEEN_FILE.write_text(str(msg_id), encoding="utf-8")


async def save_text_message_prompt(m: Message) -> Path:
    raw_text = (getattr(m, "message", "") or "").strip()

    first_line = raw_text.splitlines()[0] if raw_text else ""
    base_name = sanitize_name(first_line[:60]) if first_line else f"prompt_{m.id}"
    target = unique_path(TARGET_DIR / f"{base_name}.txt")

    target.write_text(raw_text + "\n", encoding="utf-8")
    return target


async def save_attached_prompt_file(client: TelegramClient, m: Message) -> Optional[Path]:
    filename = sanitize_name(get_filename_from_message(m))
    suffix = Path(filename).suffix.lower()

    if suffix not in ALLOWED_EXTENSIONS:
        filename = f"{Path(filename).stem}.txt"

    target = unique_path(TARGET_DIR / filename)
    saved = await client.download_media(m, file=str(target))
    if not saved:
        return None
    return Path(saved)


async def process_message(client: TelegramClient, entity, m: Message) -> bool:
    saved_path: Optional[Path] = None

    if is_allowed_prompt_file(m):
        filename = get_filename_from_message(m)
        print(f"[prompt-file] msg_id={m.id} filename={filename}", flush=True)
        saved_path = await save_attached_prompt_file(client, m)

        if not saved_path:
            print(f"[download-failed] msg_id={m.id}", flush=True)
            return False

        print(f"[saved-file] {saved_path}", flush=True)

    elif has_text_prompt(m):
        preview = (getattr(m, "message", "") or "").strip().splitlines()[0][:80]
        print(f"[prompt-text] msg_id={m.id} preview={preview!r}", flush=True)

        saved_path = await save_text_message_prompt(m)
        print(f"[saved-text] {saved_path}", flush=True)

    else:
        return False

    if DELETE_AFTER_PICK:
        try:
            await client.delete_messages(entity, m.id)
            print(f"[deleted] msg_id={m.id}", flush=True)
        except Exception as e:
            print(f"[delete-failed] msg_id={m.id} error={repr(e)}", flush=True)

    return True


# =========================
# MAIN
# =========================
async def main():
    print("[prompt-poller] starting...", flush=True)
    print("[prompt-poller] session path:", SESSION_PATH, flush=True)
    print("[prompt-poller] chat:", CHAT, flush=True)
    print("[prompt-poller] poll_sec:", POLL_SEC, flush=True)
    print("[prompt-poller] delete_after_pick:", DELETE_AFTER_PICK, flush=True)
    print("[prompt-poller] accept_outgoing:", ACCEPT_OUTGOING, flush=True)
    print("[prompt-poller] saving to:", TARGET_DIR, flush=True)

    SESSION_PATH.parent.mkdir(parents=True, exist_ok=True)

    client = TelegramClient(str(SESSION_PATH), API_ID, API_HASH)

    async with client:
        me = await client.get_me()
        print(
            "[prompt-poller] connected as:",
            getattr(me, "username", None) or getattr(me, "id", None),
            flush=True,
        )

        entity = await client.get_entity(CHAT)
        last_seen_id: Optional[int] = load_last_seen_id()

        while True:
            try:
                msgs = await client.get_messages(entity, limit=20)

                unseen = []
                for msg in reversed(msgs):
                    if not isinstance(msg, Message):
                        continue
                    if last_seen_id is not None and msg.id <= last_seen_id:
                        continue
                    unseen.append(msg)

                max_processed_id = last_seen_id

                for msg in unseen:
                    await process_message(client, entity, msg)
                    if max_processed_id is None or msg.id > max_processed_id:
                        max_processed_id = msg.id

                if max_processed_id is not None:
                    last_seen_id = max_processed_id
                    save_last_seen_id(last_seen_id)

                await asyncio.sleep(POLL_SEC)

            except Exception as e:
                print("[loop-error]", repr(e), flush=True)
                await asyncio.sleep(2.0)


if __name__ == "__main__":
    asyncio.run(main())
