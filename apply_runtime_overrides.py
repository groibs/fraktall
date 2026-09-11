from __future__ import annotations

import argparse
from pathlib import Path


def patch_settings(app: Path) -> None:
    path = app / "src/main/settings.ts"
    text = path.read_text(encoding="utf-8")

    old_get_settings = "    analysisModel: s.analysisModel,\n    openaiBaseUrl: s.openaiBaseUrl,"
    new_get_settings = (
        "    analysisModel: process.env.FRAKTALL_ANALYSIS_MODEL?.trim() || s.analysisModel,\n"
        "    openaiBaseUrl: s.openaiBaseUrl,"
    )
    if new_get_settings not in text:
        if old_get_settings not in text:
            raise RuntimeError("Could not patch getSettings() analysis model override")
        text = text.replace(old_get_settings, new_get_settings, 1)

    old_model_prefs = (
        "    transcriptionLanguage: s.transcriptionLanguage,\n"
        "    analysisModel: s.analysisModel\n"
        "  }\n"
        "}"
    )
    new_model_prefs = (
        "    transcriptionLanguage: s.transcriptionLanguage,\n"
        "    analysisModel: process.env.FRAKTALL_ANALYSIS_MODEL?.trim() || s.analysisModel\n"
        "  }\n"
        "}"
    )
    if new_model_prefs not in text:
        if old_model_prefs not in text:
            raise RuntimeError("Could not patch getModelPreferences() analysis model override")
        text = text.replace(old_model_prefs, new_model_prefs, 1)

    path.write_text(text, encoding="utf-8")


def patch_no_think(app: Path) -> None:
    path = app / "src/main/pipeline/openai.ts"
    text = path.read_text(encoding="utf-8")

    marker = "const effectiveMessages =\n    process.env.FRAKTALL_NO_THINK === '1'"
    if marker not in text:
        old = (
            "): Promise<string> {\n"
            "  const formats: Array<{ label: string; body: Record<string, unknown> }> = ["
        )
        new = (
            "): Promise<string> {\n"
            "  // Qwen3 local models reason by default. For Fraktall's structured editorial\n"
            "  // extraction we prefer direct JSON; /no_think is understood by Qwen3's chat template.\n"
            "  const effectiveMessages =\n"
            "    process.env.FRAKTALL_NO_THINK === '1'\n"
            "      ? [...messages, { role: 'user' as const, content: '/no_think' }]\n"
            "      : messages\n\n"
            "  const formats: Array<{ label: string; body: Record<string, unknown> }> = ["
        )
        if old not in text:
            raise RuntimeError("Could not insert FRAKTALL_NO_THINK support")
        text = text.replace(old, new, 1)

        # Two structured-format bodies pass `messages` directly.
        text = text.replace("        messages,\n        response_format:", "        messages: effectiveMessages,\n        response_format:", 1)
        text = text.replace("        messages,\n        response_format: { type: 'json_object' }", "        messages: effectiveMessages,\n        response_format: { type: 'json_object' }", 1)
        # Plain fallback spreads the original array.
        text = text.replace("          ...messages,", "          ...effectiveMessages,", 1)

    path.write_text(text, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--app", required=True)
    args = parser.parse_args()

    app = Path(args.app).resolve()
    if not (app / "package.json").exists():
        raise SystemExit(f"Invalid app directory: {app}")

    patch_settings(app)
    patch_no_think(app)
    print("Applied Fraktall runtime provider overrides")


if __name__ == "__main__":
    main()
