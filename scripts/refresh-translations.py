"""Refresh gettext catalogs only when extraction changes meaningful content."""

import re
import subprocess
from pathlib import Path


def refresh(root):
    template = root / "messages.pot"
    previous = template.read_bytes() if template.exists() else None
    subprocess.run(
        [
            "pybabel",
            "extract",
            "-F",
            "babel.cfg",
            "-k",
            "_l",
            "-o",
            "messages.pot",
            ".",
        ],  # noqa: S607 — frozen uv environment.
        cwd=root,
        check=True,
    )
    generated = template.read_bytes()
    timestamp = rb'^"POT-Creation-Date:.*\n'
    if previous is not None and re.sub(
        timestamp, b"", previous, flags=re.MULTILINE
    ) == re.sub(timestamp, b"", generated, flags=re.MULTILINE):
        template.write_bytes(previous)
        print(
            "Translation extraction is unchanged; preserving catalogs and timestamps."
        )
        return False
    subprocess.run(
        ["pybabel", "update", "-d", "app/translations", "-i", "messages.pot"],  # noqa: S607 — frozen uv environment.
        cwd=root,
        check=True,
    )
    return True


if __name__ == "__main__":
    refresh(Path.cwd())
