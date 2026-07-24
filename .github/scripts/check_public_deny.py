#!/usr/bin/env python3
"""Fail CI/pre-commit if private monorepo internals leak into this public repo."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NAMES_FILE = ROOT / ".github" / "public-deny" / "forbidden-names.txt"
CONTENT_FILE = ROOT / ".github" / "public-deny" / "forbidden-content.txt"


def load_lines(path: Path) -> list[str]:
    if not path.is_file():
        print(f"error: missing {path}", file=sys.stderr)
        sys.exit(2)
    out: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        out.append(line)
    return out


def tracked_files() -> list[str]:
    proc = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return [p for p in proc.stdout.decode("utf-8", errors="replace").split("\0") if p]


def main() -> int:
    forbidden_names = set(load_lines(NAMES_FILE))
    content_patterns = [
        (pat, re.compile(pat, re.IGNORECASE | re.MULTILINE))
        for pat in load_lines(CONTENT_FILE)
    ]
    files = tracked_files()
    failed = False

    print("== basename denylist ==")
    for path in files:
        base = Path(path).name
        if base in forbidden_names:
            print(f"FORBIDDEN FILE: {path} (basename '{base}')")
            failed = True

    print("== content denylist ==")
    # Skip the deny-list definitions themselves (they contain the patterns).
    skip_prefixes = (
        ".github/public-deny/",
        ".github/scripts/check_public_deny.py",
    )
    for path in files:
        if path.startswith(skip_prefixes) or path.endswith(
            ("forbidden-names.txt", "forbidden-content.txt")
        ):
            continue
        full = ROOT / path
        try:
            text = full.read_text(encoding="utf-8")
        except (UnicodeDecodeError, IsADirectoryError, OSError):
            continue
        for pat, cre in content_patterns:
            for m in cre.finditer(text):
                # 1-based line number
                line_no = text.count("\n", 0, m.start()) + 1
                print(f"FORBIDDEN PATTERN /{pat}/ in {path}:{line_no}")
                failed = True
                break  # one hit per pattern per file is enough

    if failed:
        print()
        print("Public deny-list check FAILED.")
        print(
            "Remove private monorepo docs/secrets, or update "
            ".github/public-deny/ for a justified false positive."
        )
        return 1

    print("Public deny-list check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
