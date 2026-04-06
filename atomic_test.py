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
