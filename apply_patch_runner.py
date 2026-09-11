from __future__ import annotations

import re
import sys
from pathlib import Path

import apply_patch as base


def _replace_required(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise RuntimeError(f"Could not find expected text in {path}: {old!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def tolerant_patch_branding(app: Path) -> None:
    index_path = app / "src/renderer/index.html"
    _replace_required(index_path, '<html lang="en">', '<html lang="pt-BR">')
    _replace_required(index_path, "<title>ClipForge</title>", "<title>Fraktall</title>")

    topbar = app / "src/renderer/src/components/TopBar.tsx"
    text = topbar.read_text(encoding="utf-8")

    if ">Fraktall</span>" not in text:
        if ">ClipForge</span>" not in text:
            raise RuntimeError("Could not find ClipForge brand label in TopBar.tsx")
        text = text.replace(">ClipForge</span>", ">Fraktall</span>", 1)

    if "Local AI" not in text:
        # Upstream formats this badge over multiple lines, so do not depend on
        # an exact inline '>Open source</span>' match.
        replaced, count = re.subn(
            r"(?P<prefix>>)[\r\n\t ]*Open source[\r\n\t ]*(?P<suffix></span>)",
            r"\g<prefix>Local AI\g<suffix>",
            text,
            count=1,
        )
        if count != 1:
            raise RuntimeError("Could not find the Open source badge in TopBar.tsx")
        text = replaced

    topbar.write_text(text, encoding="utf-8")


def main() -> None:
    # Keep the main patcher unchanged, but override the brittle branding step
    # with a whitespace-tolerant implementation.
    base.patch_branding = tolerant_patch_branding
    base.main()


if __name__ == "__main__":
    main()
