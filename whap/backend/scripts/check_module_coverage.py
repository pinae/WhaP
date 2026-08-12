#!/usr/bin/env python3
"""Enforce per-module coverage floors for security-critical modules.

coverage.py only supports a single global ``fail_under``. This script adds
per-file floors for the modules hardened during the test-quality work, so a
regression in one of them can't hide behind a healthy overall number.

Usage (run after generating coverage JSON):

    uv run pytest --cov --cov-report=json
    uv run python scripts/check_module_coverage.py

Exits non-zero if any listed module is below its floor. Floors are set a couple
of points under the achieved values; raise them as coverage improves, never
lower them.
"""
import json
import sys
from pathlib import Path

# module path (as it appears in coverage json "files" keys) -> minimum percent
FLOORS = {
    "app/services/permissions_service.py": 90,
    "app/user_management.py": 95,
    "app/services/volume_service.py": 55,
    "app/services/local_file_service.py": 95,
    "app/routes/stats.py": 55,
    "app/services/ansible_service.py": 88,
    "app/routes/projects.py": 82,
}

COVERAGE_JSON = Path("coverage.json")


def _pct(file_entry):
    return file_entry["summary"]["percent_covered"]


def main():
    if not COVERAGE_JSON.exists():
        print(
            "coverage.json not found. Run: uv run pytest --cov --cov-report=json",
            file=sys.stderr,
        )
        return 2

    data = json.loads(COVERAGE_JSON.read_text())
    files = data.get("files", {})

    # coverage may key files by absolute or relative path; match by suffix.
    def find(module):
        for key, entry in files.items():
            if key.replace("\\", "/").endswith(module):
                return entry
        return None

    failures = []
    for module, floor in sorted(FLOORS.items()):
        entry = find(module)
        if entry is None:
            failures.append(f"{module}: not found in coverage report")
            continue
        pct = _pct(entry)
        status = "OK " if pct >= floor else "LOW"
        print(f"  [{status}] {module}: {pct:.1f}% (floor {floor}%)")
        if pct < floor:
            failures.append(f"{module}: {pct:.1f}% < {floor}%")

    if failures:
        print("\nPer-module coverage floor NOT met:", file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        return 1

    print("\nAll per-module coverage floors met.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
