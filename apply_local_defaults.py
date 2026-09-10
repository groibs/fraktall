from __future__ import annotations

import argparse
from pathlib import Path


def replace_if_present(path: Path, old: str, new: str, label: str) -> bool:
    text = path.read_text(encoding="utf-8")
    if new in text:
        print(f"{label} already configured")
        return False
    if text.count(old) != 1:
        raise RuntimeError(f"Could not find expected source for {label} in {path}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    print(f"Configured {label}")
    return True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--app", required=True)
    args = parser.parse_args()

    app = Path(args.app).resolve()

    settings = app / "src/main/settings.ts"
    replace_if_present(
        settings,
        "  analysisModel: 'qwen3:4b-instruct',",
        "  analysisModel: 'fraktall-qwen',",
        "analysisModel=fraktall-qwen",
    )

    # Fraktall's first use-case is long-form podcasts/interviews. ClipForge already
    # runs UltraFace + LR-ASD active-speaker analysis for this video type and
    # switches to automatic 9:16 focus tracking when a reliable face track exists.
    home = app / "src/renderer/src/components/HomeScreen.tsx"
    replace_if_present(
        home,
        "  const [videoType, setVideoType] = useState<VideoType>(project.videoType ?? 'auto')",
        "  const [videoType, setVideoType] = useState<VideoType>(\n"
        "    project.videoType === 'auto' ? 'podcast' : (project.videoType ?? 'podcast')\n"
        "  )",
        "podcast video preset",
    )


if __name__ == "__main__":
    main()
