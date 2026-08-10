"""Repository hygiene checks.

These guard the submission requirements that are easy to violate accidentally and
expensive to violate publicly: committed secrets, and a `.env.example` that has
drifted away from the configuration the code actually reads.

`Committed secrets` is listed as a red flag in the submission guidelines, so this
runs on every CI push rather than relying on review.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# Directories that are either not ours or are reproducible build output.
SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    "htmlcov",
    "dist",
    "build",
    ".chroma",
    "chroma-data",
}

# Patterns that indicate a live credential rather than a placeholder.
# `sk-ant-` is the Anthropic API key prefix; `ghp_`/`github_pat_` are GitHub tokens.
SECRET_PATTERNS = [
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{10,}"),
    re.compile(r"ghp_[A-Za-z0-9]{20,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
]

TEXT_SUFFIXES = {
    ".py", ".md", ".toml", ".yml", ".yaml", ".json", ".txt", ".sh", ".ps1",
    ".ts", ".tsx", ".js", ".jsx", ".env", ".example", ".cfg", ".ini", "",
}


def _tracked_text_files() -> list[Path]:
    files: list[Path] = []
    for path in REPO_ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        files.append(path)
    return files


def test_env_example_exists() -> None:
    """The submission guidelines require a committed .env.example."""
    assert (REPO_ROOT / ".env.example").is_file()


def test_real_env_file_is_not_committed() -> None:
    """.env holds real values and must never be tracked."""
    gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "\n.env\n" in f"\n{gitignore}\n", ".gitignore must ignore .env"


def test_no_live_credentials_anywhere_in_the_tree() -> None:
    """No file may contain something shaped like a real API key or token."""
    offenders: list[str] = []
    for path in _tracked_text_files():
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for pattern in SECRET_PATTERNS:
            if pattern.search(content):
                offenders.append(f"{path.relative_to(REPO_ROOT)} matched {pattern.pattern}")
    assert not offenders, "Possible committed credentials:\n" + "\n".join(offenders)


def test_env_example_uses_placeholder_values_for_secrets() -> None:
    """Secret-bearing keys in .env.example must be placeholders, not real values."""
    lines = (REPO_ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
    secret_keys = {"ANTHROPIC_API_KEY", "GITHUB_TOKEN"}
    seen: dict[str, str] = {}
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        if key in secret_keys:
            seen[key] = value

    missing = secret_keys - seen.keys()
    assert not missing, f".env.example is missing keys: {sorted(missing)}"

    for key, value in seen.items():
        assert value == "replace-me", (
            f"{key} in .env.example must be the literal placeholder 'replace-me', got {value!r}"
        )
