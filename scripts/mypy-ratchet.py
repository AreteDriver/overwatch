#!/usr/bin/env python3
"""Mypy error ratchet — fails if any module exceeds its error ceiling.

Run this in CI after mypy. Update CEILINGS as you drive errors down.
Usage:
    python scripts/mypy-ratchet.py
"""

from __future__ import annotations

import subprocess
import sys

# Per-module error ceilings. Increment the module name when adding new files.
# Format: "module.dotted.name": max_allowed_errors
CEILINGS: dict[str, int] = {
    "overwatch.analysis.alerts": 5,
    "overwatch.analysis.briefing": 7,
    "overwatch.analysis.entities": 14,
    "overwatch.analysis.geofence": 5,
    "overwatch.analysis.mesh_health": 7,
    "overwatch.analysis.ollama_briefing": 2,
    "overwatch.analysis.replay": 2,
    "overwatch.analysis.rules": 2,
    "overwatch.api.routes": 32,
    "overwatch.app": 1,
    "overwatch.crypto": 0,
    "overwatch.database": 2,
    "overwatch.models": 3,
    "overwatch.security": 7,
}


def main() -> int:
    proc = subprocess.run(
        [
            sys.executable, "-m", "mypy", "overwatch",
            "--ignore-missing-imports",
            "--show-error-codes",
            "--no-error-summary",
        ],
        capture_output=True,
        text=True,
    )
    errors = proc.stdout.splitlines()

    # Group errors by module
    counts: dict[str, int] = {}
    for line in errors:
        if ":" not in line:
            continue
        module = line.split(":")[0].replace("/", ".").removesuffix(".py")
        counts[module] = counts.get(module, 0) + 1

    # Check ceilings
    exceeded = []
    for module, ceiling in CEILINGS.items():
        actual = counts.get(module, 0)
        if actual > ceiling:
            exceeded.append(f"  {module}: {actual} > {ceiling}")

    # Report modules with counts but no ceiling (new modules)
    unlisted = []
    for module, actual in sorted(counts.items()):
        if module not in CEILINGS and actual > 0:
            unlisted.append(f"  {module}: {actual}")

    if exceeded:
        print("MYPY RATCHET FAILED — error ceilings exceeded:")
        for e in exceeded:
            print(e)
        print()

    if unlisted:
        print("MYPY RATCHET: unlisted modules with errors (add to CEILINGS):")
        for u in unlisted:
            print(u)
        print()

    # Always print summary
    total = sum(counts.values())
    print(f"Total mypy errors: {total}")
    for module, actual in sorted(counts.items()):
        ceiling = CEILINGS.get(module, 0)
        status = "✓" if actual <= ceiling else "✗"
        print(f"  {status} {module}: {actual} / {ceiling}")

    return 1 if exceeded or unlisted else 0


if __name__ == "__main__":
    sys.exit(main())
