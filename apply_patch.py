from __future__ import annotations

import argparse
import json
from pathlib import Path


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"Expected exactly one match in {path} but found {count}: {old[:120]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def clamp_ts_expr(raw: str) -> str:
    return f"Math.max(0, Math.min(99, Math.round({raw})))"


def patch_package(app: Path) -> None:
    for file_name in ("package.json", "package-lock.json"):
        path = app / file_name
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        data["name"] = "fraktall"
        data["version"] = "0.1.0"
        if file_name == "package.json":
            data["description"] = "Local-first AI podcast and video clipper with editorial intelligence"
            data["author"] = "Fraktall contributors; based on ClipForge"
            build = data.get("build", {})
            build["appId"] = "com.groibs.fraktall"
            build["productName"] = "Fraktall"
            build["publish"] = {
                "provider": "github",
                "owner": "groibs",
                "repo": "fraktall",
                "releaseType": "release",
            }
            data["build"] = build
        else:
            packages = data.get("packages")
            if isinstance(packages, dict) and isinstance(packages.get(""), dict):
                packages[""]["name"] = "fraktall"
                packages[""]["version"] = "0.1.0"
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def patch_defaults(app: Path) -> None:
    path = app / "src/main/settings.ts"
    replace_once(path, "  transcriptionModel: 'whisper-1',", "  transcriptionModel: 'small',")
    replace_once(
        path,
        "  // Default to English rather than Whisper's auto-detect: the app is\n"
        "  // English-first, and auto-detect occasionally mislabels English speech as a\n"
        "  // similar-sounding language (e.g. Welsh). Users of other languages can pick\n"
        "  // theirs — or 'auto' — in Settings.\n"
        "  transcriptionLanguage: 'en',\n"
        "  analysisModel: 'gpt-5.4-mini',",
        "  // Fraktall starts in PT-BR and uses local OpenAI-compatible endpoints from run-local.ps1.\n"
        "  transcriptionLanguage: 'pt',\n"
        "  analysisModel: 'qwen3:4b-instruct',",
    )


def patch_types(app: Path) -> None:
    path = app / "src/shared/types.ts"
    replace_once(
        path,
        "  viralityScore: number\n  viralityReason: string\n",
        "  viralityScore: number\n"
        "  viralityReason: string\n"
        "  /** Fraktall: informational/editorial value independent of pure virality. */\n"
        "  editorialScore?: number\n"
        "  /** Fraktall: whether the clip preserves the meaning of the surrounding conversation. */\n"
        "  contextIntegrityScore?: number\n"
        "  /** Fraktall: short explanation for the editorial score. */\n"
        "  editorialReason?: string\n"
        "  /** Fraktall: ranking score used by the selected curation mode. */\n"
        "  selectionScore?: number\n",
    )
    replace_once(
        path,
        "export interface AnalyzeOptions {\n"
        "  /** Optional user steering prompt (\"ClipAnything\" style). */\n"
        "  prompt: string\n"
        "  clipLength: ClipLengthPreference\n",
        "export type CurationMode = 'viral' | 'podcast' | 'insight' | 'news' | 'institutional' | 'custom'\n\n"
        "export interface AnalyzeOptions {\n"
        "  /** Optional user steering prompt (\"ClipAnything\" style). */\n"
        "  prompt: string\n"
        "  /** Fraktall editorial selection profile. Optional for compatibility with upstream tests. */\n"
        "  curationMode?: CurationMode\n"
        "  clipLength: ClipLengthPreference\n",
    )


def write_fraktall_shared(app: Path) -> None:
    path = app / "src/shared/fraktall.ts"
    path.write_text(
        """import type { CurationMode } from './types'\n\n"
        "export const CURATION_OPTIONS: Array<{ value: CurationMode; label: string; hint: string }> = [\n"
        "  { value: 'viral', label: 'Viral', hint: 'Hook, emoção e compartilhamento' },\n"
        "  { value: 'podcast', label: 'Podcast', hint: 'Histórias, opiniões e momentos fortes' },\n"
        "  { value: 'insight', label: 'Insight', hint: 'Ideias, explicações e aprendizados' },\n"
        "  { value: 'news', label: 'Notícia', hint: 'Novidade, anúncio, dado e consequência' },\n"
        "  { value: 'institutional', label: 'Institucional', hint: 'Interesse público e relevância editorial' },\n"
        "  { value: 'custom', label: 'Personalizado', hint: 'Seu prompt define a prioridade' }\n"
        "]\n\n"
        "export function curationGuidance(mode: CurationMode): string {\n"
        "  switch (mode) {\n"
        "    case 'viral':\n"
        "      return 'CURATION MODE: VIRAL. Prioritize hooks, emotion, surprise, controversy, humour, practical value and shareability. Editorial relevance still matters, but reach and retention lead the ranking.'\n"
        "    case 'podcast':\n"
        "      return 'CURATION MODE: PODCAST. Prioritize self-contained stories, surprising admissions, strong opinions, disagreements, personal experiences, useful explanations, memorable lines and moments with a satisfying payoff. Do not select generic chatter just because delivery is energetic.'\n"
        "    case 'insight':\n"
        "      return 'CURATION MODE: INSIGHT. Prioritize ideas that teach something, explain a mechanism, challenge a common assumption, provide an actionable lesson, reveal a useful mental model or make a complex subject clear. Virality is secondary to genuine value.'\n"
        "    case 'news':\n"
        "      return 'CURATION MODE: NEWS. Prioritize genuinely new information: announcements, decisions, numbers, dates, changes, commitments, consequences, corrections and quotable statements by relevant people. Penalize old context, vague opinion and statements without a concrete news value.'\n"
        "    case 'institutional':\n"
        "      return 'CURATION MODE: INSTITUTIONAL. Prioritize public-interest information, decisions, policies, deadlines, services, investments, official announcements, accountability, concrete data and statements whose speaker has institutional relevance. Context integrity is critical: heavily penalize any cut that can mislead when separated from what came before or after.'\n"
        "    case 'custom':\n"
        "      return 'CURATION MODE: CUSTOM. The creator instructions below are the main selection objective. Still require every clip to be self-contained, accurate and structurally complete.'\n"
        "  }\n"
        "}\n\n"
        "export function fraktallRankScore(\n"
        "  mode: CurationMode,\n"
        "  virality: number,\n"
        "  editorial: number,\n"
        "  contextIntegrity: number\n"
        "): number {\n"
        "  const weights: Record<CurationMode, [number, number, number]> = {\n"
        "    viral: [0.65, 0.20, 0.15],\n"
        "    podcast: [0.40, 0.40, 0.20],\n"
        "    insight: [0.25, 0.55, 0.20],\n"
        "    news: [0.20, 0.60, 0.20],\n"
        "    institutional: [0.10, 0.65, 0.25],\n"
        "    custom: [0.35, 0.45, 0.20]\n"
        "  }\n"
        "  const [v, e, c] = weights[mode]\n"
        "  const integrityPenalty = contextIntegrity < 60 ? (60 - contextIntegrity) * 0.65 : 0\n"
        "  return Math.max(0, Math.min(99, Math.round(virality * v + editorial * e + contextIntegrity * c - integrityPenalty)))\n"
        "}\n""",
        encoding="utf-8",
    )


def patch_highlights(app: Path) -> None:
    path = app / "src/main/pipeline/highlights.ts"
    replace_once(
        path,
        "import { chatJSON } from './openai'",
        "import { chatJSON } from './openai'\nimport { curationGuidance, fraktallRankScore } from '@shared/fraktall'",
    )
    replace_once(
        path,
        "  virality_score: number\n  virality_reason: string\n  hashtags: string[]",
        "  virality_score: number\n"
        "  virality_reason: string\n"
        "  editorial_score?: number\n"
        "  context_integrity_score?: number\n"
        "  editorial_reason?: string\n"
        "  hashtags: string[]",
    )
    replace_once(
        path,
        "          'virality_score',\n          'virality_reason',\n          'hashtags'",
        "          'virality_score',\n"
        "          'virality_reason',\n"
        "          'editorial_score',\n"
        "          'context_integrity_score',\n"
        "          'editorial_reason',\n"
        "          'hashtags'",
    )
    replace_once(
        path,
        "          virality_reason: {\n"
        "            type: 'string',\n"
        "            description: 'Short explanation of the score citing hook/emotion/value'\n"
        "          },\n"
        "          hashtags: {",
        "          virality_reason: {\n"
        "            type: 'string',\n"
        "            description: 'Short explanation of the score citing hook/emotion/value'\n"
        "          },\n"
        "          editorial_score: {\n"
        "            type: 'integer',\n"
        "            description: 'Editorial/informational value 0-99 independent of pure virality'\n"
        "          },\n"
        "          context_integrity_score: {\n"
        "            type: 'integer',\n"
        "            description: '0-99 confidence that this cut preserves meaning and is understandable without missing antecedents, conditions, negations or crucial surrounding context'\n"
        "          },\n"
        "          editorial_reason: {\n"
        "            type: 'string',\n"
        "            description: 'Short explanation of what makes the moment editorially relevant or irrelevant'\n"
        "          },\n"
        "          hashtags: {",
    )
    replace_once(
        path,
        "Sum the parts for the final score. Be honest and discriminating: most clips score 40-75, reserve 85+ for exceptional moments.`",
        "Sum the parts for the final score. Be honest and discriminating: most clips score 40-75, reserve 85+ for exceptional moments.\n\n"
        "Fraktall also requires two independent scores for every candidate:\n"
        "- editorial_score (0-99): how important, informative, newsworthy, insightful or useful this specific moment is, independent of whether it is emotionally viral.\n"
        "- context_integrity_score (0-99): whether a cold viewer gets the correct meaning from the cut alone. Penalize missing antecedents, hidden conditions, earlier negations, ambiguous pronouns, selective quoting, or an answer whose question is required to understand it. Scores below 70 mean the cut needs more context or should not be selected.\n"
        "- editorial_reason: one concise sentence explaining the editorial value.\n"
        "Write title, hook, summary, virality_reason and editorial_reason in the same language as the transcript.`",
    )
    replace_once(
        path,
        "    lengthGuidance(options.clipLength),\n    insist",
        "    lengthGuidance(options.clipLength),\n"
        "    curationGuidance(options.curationMode ?? 'podcast'),\n"
        "    insist",
    )
    old_push = """    const typeDefaults = initialClipEditForVideoType(options.videoType)\n    clips.push({\n      id: randomUUID(),\n      suggestedStart: start,\n      suggestedEnd: end,\n      title: raw.title,\n      hook: raw.hook,\n      summary: raw.summary,\n      viralityScore: Math.max(0, Math.min(99, Math.round(raw.virality_score))),\n      viralityReason: raw.virality_reason,\n      visualSummary: null,"""
    new_push = """    const typeDefaults = initialClipEditForVideoType(options.videoType)\n    const viralityScore = Math.max(0, Math.min(99, Math.round(raw.virality_score)))\n    const editorialScore = Math.max(0, Math.min(99, Math.round(raw.editorial_score ?? viralityScore)))\n    const contextIntegrityScore = Math.max(0, Math.min(99, Math.round(raw.context_integrity_score ?? 75)))\n    const selectionScore = fraktallRankScore(\n      options.curationMode ?? 'podcast',\n      viralityScore,\n      editorialScore,\n      contextIntegrityScore\n    )\n    clips.push({\n      id: randomUUID(),\n      suggestedStart: start,\n      suggestedEnd: end,\n      title: raw.title,\n      hook: raw.hook,\n      summary: raw.summary,\n      viralityScore,\n      viralityReason: raw.virality_reason,\n      editorialScore,\n      contextIntegrityScore,\n      editorialReason: raw.editorial_reason ?? '',\n      selectionScore,\n      visualSummary: null,"""
    replace_once(path, old_push, new_push)
    replace_once(
        path,
        "  clips.sort((a, b) => b.viralityScore - a.viralityScore)",
        "  clips.sort((a, b) => (b.selectionScore ?? b.viralityScore) - (a.selectionScore ?? a.viralityScore))",
    )


def patch_home(app: Path) -> None:
    path = app / "src/renderer/src/components/HomeScreen.tsx"
    replace_once(
        path,
        "  BrowserCookieSource,\n  ClipLengthPreference,\n  ProjectMode,",
        "  BrowserCookieSource,\n  ClipLengthPreference,\n  CurationMode,\n  ProjectMode,",
    )
    replace_once(
        path,
        "import { isVideoFile } from '@shared/video'",
        "import { isVideoFile } from '@shared/video'\nimport { CURATION_OPTIONS } from '@shared/fraktall'",
    )
    replace_once(
        path,
        "  const [clipLength, setClipLength] = useState<ClipLengthPreference>('auto')\n  const [videoType, setVideoType]",
        "  const [clipLength, setClipLength] = useState<ClipLengthPreference>('auto')\n"
        "  const [curationMode, setCurationMode] = useState<CurationMode>('podcast')\n"
        "  const [videoType, setVideoType]",
    )
    curation_card = """
            <div className=\"rounded-2xl border border-surface-700 bg-surface-900 p-5\">
              <label className=\"flex items-center gap-2 text-sm font-semibold\">
                <Sparkles size={15} className=\"text-accent-400\" />
                Curadoria Fraktall
              </label>
              <p className=\"mt-1 text-xs leading-relaxed text-zinc-500\">
                Define o que a IA considera um corte forte. Podcast é o padrão para entrevistas e conversas longas.
              </p>
              <div className=\"mt-3 grid grid-cols-2 gap-2\">
                {CURATION_OPTIONS.map((opt) => (
                  <button
                    key={opt.value}
                    type=\"button\"
                    onClick={() => setCurationMode(opt.value)}
                    className={`rounded-xl border px-3 py-2.5 text-left transition ${
                      curationMode === opt.value
                        ? 'border-white/30 bg-white/[0.07] text-zinc-100'
                        : 'border-surface-600 bg-surface-850 text-zinc-400 hover:border-surface-600 hover:bg-surface-800'
                    }`}
                  >
                    <div className=\"text-sm font-medium\">{opt.label}</div>
                    <div className=\"mt-0.5 text-[11px] leading-snug text-zinc-500\">{opt.hint}</div>
                  </button>
                ))}
              </div>
            </div>

"""
    marker = """            <div className=\"rounded-2xl border border-surface-700 bg-surface-900 p-5\">\n              <label className=\"flex items-center gap-2 text-sm font-semibold\">\n                <Wand2 size={15} className=\"text-accent-400\" />\n                AI instructions"""
    text = path.read_text(encoding="utf-8")
    if marker not in text:
        raise RuntimeError("Could not find HomeScreen AI instructions card")
    path.write_text(text.replace("            <div className=\"rounded-2xl border border-surface-700 bg-surface-900 p-5\">\n              <label className=\"flex items-center gap-2 text-sm font-semibold\">\n                <Wand2 size={15} className=\"text-accent-400\" />\n                AI instructions", curation_card + "            <div className=\"rounded-2xl border border-surface-700 bg-surface-900 p-5\">\n              <label className=\"flex items-center gap-2 text-sm font-semibold\">\n                <Wand2 size={15} className=\"text-accent-400\" />\n                AI instructions", 1), encoding="utf-8")
    replace_once(
        path,
        "? void analyze({ prompt, clipLength, broll, hookFirst, videoType })",
        "? void analyze({ prompt, curationMode, clipLength, broll, hookFirst, videoType })",
    )
    replace_once(path, "Drop in a podcast, webinar or stream. ClipForge transcribes it, finds the best moments", "Cole um podcast, entrevista ou vídeo longo. Fraktall transcreve, encontra os melhores momentos")
    replace_once(path, "with AI, scores them for virality and renders caption-burned vertical clips.", "com IA, avalia valor editorial e gera cortes verticais legendados.")


def patch_clips_screen(app: Path) -> None:
    path = app / "src/renderer/src/components/ClipsScreen.tsx"
    replace_once(
        path,
        "              Ranked by virality score. Open a clip to trim, reframe and style captions before\n              exporting.",
        "              Ranked by Fraktall score: virality, editorial value and context integrity. Open a clip\n              to trim, reframe and style captions before exporting.",
    )
    replace_once(
        path,
        "          <ScoreBadge score={clip.viralityScore} />",
        "          <ScoreBadge score={clip.selectionScore ?? clip.viralityScore} />",
    )
    replace_once(
        path,
        "        <div className=\"mt-2 line-clamp-1 text-[11px] text-zinc-500\">\n"
        "          {clip.hashtags.map((h) => `#${h}`).join(' ')}\n"
        "        </div>\n\n"
        "        <div className=\"mt-3.5 flex items-center gap-2\">",
        "        <div className=\"mt-2 flex flex-wrap gap-1.5 text-[10px] font-medium\">\n"
        "          <span className=\"rounded-md border border-surface-600 px-1.5 py-0.5 text-zinc-400\">Viral {clip.viralityScore}</span>\n"
        "          <span className=\"rounded-md border border-surface-600 px-1.5 py-0.5 text-zinc-400\">Editorial {clip.editorialScore ?? '—'}</span>\n"
        "          <span className=\"rounded-md border border-surface-600 px-1.5 py-0.5 text-zinc-400\">Contexto {clip.contextIntegrityScore ?? '—'}</span>\n"
        "        </div>\n"
        "        {clip.editorialReason && (\n"
        "          <p className=\"mt-2 line-clamp-2 text-[11px] leading-relaxed text-zinc-500\">{clip.editorialReason}</p>\n"
        "        )}\n"
        "        <div className=\"mt-2 line-clamp-1 text-[11px] text-zinc-500\">\n"
        "          {clip.hashtags.map((h) => `#${h}`).join(' ')}\n"
        "        </div>\n\n"
        "        <div className=\"mt-3.5 flex items-center gap-2\">",
    )


def patch_branding(app: Path) -> None:
    replace_once(app / "src/renderer/index.html", "<html lang=\"en\">", "<html lang=\"pt-BR\">")
    replace_once(app / "src/renderer/index.html", "<title>ClipForge</title>", "<title>Fraktall</title>")
    path = app / "src/renderer/src/components/TopBar.tsx"
    replace_once(path, ">ClipForge</span>", ">Fraktall</span>")
    replace_once(path, ">Open source</span>", ">Local AI</span>")


def patch_updates(app: Path) -> None:
    path = app / "src/main/updates.ts"
    replace_once(path, "const REPO = 'JeremySNR/clip-forge'", "const REPO = 'groibs/fraktall'")
    replace_once(
        path,
        "export function isSourceUpdateSupported(): boolean {\n  return !isAutoUpdateSupported()\n}",
        "export function isSourceUpdateSupported(): boolean {\n  // Fraktall applies a reproducible patch over a pinned upstream checkout; never git-pull the nested upstream repo in-app.\n  return false\n}",
    )


def patch_debug_prefix(app: Path) -> None:
    # Cosmetic only: keep upstream internals untouched elsewhere.
    path = app / "src/main/pipeline/openai.ts"
    text = path.read_text(encoding="utf-8")
    text = text.replace("[clipforge]", "[fraktall]")
    path.write_text(text, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--app", required=True)
    args = parser.parse_args()
    app = Path(args.app).resolve()
    if not (app / "package.json").exists():
        raise SystemExit(f"Invalid app directory: {app}")

    patch_package(app)
    patch_defaults(app)
    patch_types(app)
    write_fraktall_shared(app)
    patch_highlights(app)
    patch_home(app)
    patch_clips_screen(app)
    patch_branding(app)
    patch_updates(app)
    patch_debug_prefix(app)

    marker = app / ".fraktall-patched"
    marker.write_text("Fraktall V0 patch applied over ClipForge 0.8.0\n", encoding="utf-8")
    print(f"Fraktall patch applied: {app}")


if __name__ == "__main__":
    main()
