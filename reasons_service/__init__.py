__version__ = "0.5.9"

# Git commit hash — set at build time by hatch hook, or resolved at runtime.
__git_hash__ = ""


def _resolve_git_hash() -> str:
    """Get the git commit hash, trying build-time value first, then runtime."""
    if __git_hash__:
        return __git_hash__
    import subprocess
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=__file__.rsplit("/", 1)[0],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except Exception:
        return "unknown"
