"""Pre-commit black check without invoking black's sandbox-hostile CLI path."""

from __future__ import annotations

import sys
from pathlib import Path

import black

MODE = black.FileMode(
    line_length=88,
    target_versions={black.TargetVersion.PY312},
)


def main(argv: list[str]) -> int:
    """Exit non-zero when any provided file differs from canonical black formatting."""
    needs_reformat = False
    for raw_path in argv:
        path = Path(raw_path)
        if not path.is_file():
            continue
        source = path.read_text(encoding="utf-8")
        try:
            formatted = black.format_file_contents(source, fast=False, mode=MODE)
        except black.NothingChanged:
            continue
        except black.InvalidInput as exc:
            print(f"error: cannot format {path}: {exc}", file=sys.stderr)
            return 123
        if formatted != source:
            print(f"would reformat {path}")
            needs_reformat = True
    return 1 if needs_reformat else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
