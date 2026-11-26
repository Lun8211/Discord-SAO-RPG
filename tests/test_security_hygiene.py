"""Pre-push security, secret-leak, .gitignore hygiene, and repository purity verification tests."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("discord_bot_token", re.compile(r"\b[MN][A-Za-z0-9_-]{23,27}\.[A-Za-z0-9_-]{6}\.[A-Za-z0-9_-]{27,}\b")),
    ("github_pat", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}\b")),
    ("github_fine_pat", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b")),
    ("private_key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("discord_webhook", re.compile(r"https://discord(?:app)?\.com/api/webhooks/\d+/[A-Za-z0-9_-]+")),
    ("openai_key", re.compile(r"\bsk-[A-Za-z0-9]{24,}\b")),
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
)

SCAN_EXTENSIONS = {".py", ".json", ".yml", ".yaml", ".md", ".bat", ".vbs", ".ini", ".txt", ".example"}
SKIP_DIRS = {".git", ".venv", ".agents", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", "data"}


def _iter_repo_text_files() -> list[Path]:
    out: list[Path] = []
    for p in REPO_ROOT.rglob("*"):
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        if p.is_file() and (p.suffix.lower() in SCAN_EXTENSIONS or p.name in (".gitignore", ".gitattributes", ".env.example")):
            out.append(p)
    return out


def test_zero_secrets_or_tokens_in_repository_files() -> None:
    findings: list[str] = []
    for fpath in _iter_repo_text_files():
        text = fpath.read_text(encoding="utf-8", errors="ignore")
        for label, pat in SECRET_PATTERNS:
            for m in pat.finditer(text):
                findings.append(f"{fpath.relative_to(REPO_ROOT)}: matched {label}")
    assert not findings, f"Potential secret leaks found: {findings}"


def test_gitignore_protects_secrets_runtime_db_and_agent_artifacts() -> None:
    must_ignore = [
        ".env",
        ".env.local",
        ".env.production",
        "data/rpg.db",
        ".agents/teamwork/secret.md",
        ".venv/bin/python",
        ".mypy_cache/cache",
        ".ruff_cache/cache",
        "test.sqlite",
        "test.sqlite3",
    ]
    for path in must_ignore:
        proc = subprocess.run(
            ["git", "check-ignore", "--no-index", "-q", path],
            cwd=REPO_ROOT,
            check=False,
        )
        assert proc.returncode == 0, f"Expected {path} to be gitignored"

    must_not_ignore = [
        ".env.example",
        "src/rpg/content/biomes.json",
        "src/rpg/content/bosses.json",
    ]
    for path in must_not_ignore:
        proc = subprocess.run(
            ["git", "check-ignore", "--no-index", "-q", path],
            cwd=REPO_ROOT,
            check=False,
        )
        assert proc.returncode != 0, f"Expected {path} NOT to be gitignored"


def test_no_hardcoded_eval_or_exec_in_src_rpg() -> None:
    bad: list[str] = []
    pat = re.compile(r"\b(?:eval|exec)\s*\(")
    for fpath in (REPO_ROOT / "src" / "rpg").rglob("*.py"):
        text = fpath.read_text(encoding="utf-8")
        if pat.search(text):
            bad.append(str(fpath.relative_to(REPO_ROOT)))
    assert not bad, f"Forbidden eval/exec found in: {bad}"
