"""Gate new ty diagnostics while keeping the inherited backlog explicit."""

import json
import subprocess
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "scripts/ty-baseline.json"


def normalize(diagnostics, root=ROOT):
    """Keep source context and duplicate counts, not unstable line numbers."""
    if not isinstance(diagnostics, list):
        raise ValueError("ty must return a JSON list")
    entries = []
    for item in diagnostics:
        location = item["location"]
        path = Path(location["path"])
        if path.is_absolute() or ".." in path.parts or path.parts[0] != "app":
            raise ValueError(f"Unexpected diagnostic path: {path}")
        line = location["positions"]["begin"]["line"]
        source = (root / path).read_text().splitlines()[line - 1].strip()
        entries.append(
            [
                str(path),
                item["check_name"],
                item["severity"],
                item["description"],
                source,
            ]
        )
    return sorted(entries)


def compare(actual, baseline):
    current = Counter(tuple(entry) for entry in actual)
    approved = Counter(tuple(entry) for entry in baseline)
    return list((current - approved).elements()), list((approved - current).elements())


def main():
    result = subprocess.run(
        ["ty", "check", "app", "--error-on-warning", "--output-format", "gitlab"],  # noqa: S607 — uv frozen toolchain.
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode not in (0, 1):
        raise RuntimeError(f"ty failed to run: {result.stderr}")
    diagnostics = json.loads(result.stdout)
    if bool(diagnostics) != bool(result.returncode):
        raise RuntimeError("ty exit status disagrees with its diagnostics")
    new, stale = compare(normalize(diagnostics), json.loads(BASELINE.read_text()))
    for entry in new:
        print("New diagnostic:", json.dumps(entry, ensure_ascii=False))
    for entry in stale:
        print("Remove resolved baseline entry:", json.dumps(entry, ensure_ascii=False))
    if new or stale:
        raise SystemExit(1)
    print(
        f"ty: {len(diagnostics)} explicit inherited diagnostics; zero additions. See scripts/ty-baseline.json."
    )


if __name__ == "__main__":
    main()
