from __future__ import annotations

import argparse
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--app", required=True)
    args = parser.parse_args()

    app = Path(args.app).resolve()
    settings = app / "src/main/settings.ts"
    text = settings.read_text(encoding="utf-8")
    old = "  analysisModel: 'qwen3:4b-instruct',"
    new = "  analysisModel: 'fraktall-qwen',"

    if new in text:
        print("Local Fraktall model already configured")
        return
    if text.count(old) != 1:
        raise RuntimeError("Could not find the patched analysis model default")

    settings.write_text(text.replace(old, new, 1), encoding="utf-8")
    print("Configured analysisModel=fraktall-qwen")


if __name__ == "__main__":
    main()
