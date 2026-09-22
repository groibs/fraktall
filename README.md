# Fraktall

Local-first AI podcast/video clipper built on top of the MIT-licensed ClipForge project.

## V0 goal

Paste a YouTube/podcast URL or choose a local video and automatically generate ready-to-post vertical clips with:

- AI highlight selection
- curation modes: Viral, Podcast, Insight, News, Institutional and Custom
- virality + editorial + context-integrity scoring
- word-level captions
- speaker-aware reframing
- auto zoom
- silence/filler tightening
- 9:16 / 1:1 / 16:9 exports
- local faster-whisper transcription
- local Qwen analysis through Ollama

No Supabase, Vercel, login, billing or cloud storage are required for the personal desktop build.

## Remote mode (web panel + worker)

A separate, actively developed mode lets you submit videos from a
Vercel-hosted web panel (any device, no install) while a background worker
handles transcription, editorial analysis and clip rendering. It's a
personal tool on infrastructure you own, not a multi-tenant cloud SaaS —
see `docs/PRODUCT_DIRECTION.md` for the architecture decision and editorial
pipeline (long-form segmentation + Shorts per segment).

The worker runs as a Docker container on a small VPS (recommended — see
`docs/DEPLOY_VPS.md`, nothing depends on your PC being on) or, for local
development, directly on your PC against LM Studio/local Whisper (see
`docs/WEB_WORKER_MVP.md`). Either way it can use OpenAI instead of local
models for transcription/analysis, which is the default for the VPS setup.

## Windows — easiest path

Clone the repository:

```powershell
git clone https://github.com/groibs/fraktall.git
cd fraktall
```

Then either double-click:

1. `INSTALL_WINDOWS.bat` — first installation only;
2. `RUN_FRAKTALL.bat` — every time you want to use Fraktall.

Or use PowerShell directly:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\setup.ps1
.\run-local.ps1
```

`setup.ps1` checks/installs the required local tooling, downloads the pinned ClipForge source, applies the Fraktall product/editorial patch, creates the Python environment for faster-whisper, pulls `qwen3:4b-instruct` and creates the tuned local Ollama profile `fraktall-qwen`.

The first Whisper transcription downloads the selected speech model. The V0 default is multilingual `small`.

## Local AI defaults

- chat/curation: `fraktall-qwen` through Ollama
- base model: `qwen3:4b-instruct`
- context configured by Fraktall: 32K
- transcription: faster-whisper `small`
- language: Portuguese (`pt`)
- default curation: Podcast

The full source video is processed locally. Rendering, reframing, captions, transcription and LLM analysis do not need a cloud API in the supplied local launcher.

## Upstream

Fraktall V0 currently vendors at setup time:

- `JeremySNR/clip-forge`
- pinned commit: `35814e546db958c6d66d4f82697bf6c2136d62af`

ClipForge is MIT licensed. Its upstream `LICENSE` remains inside the generated `app/` directory.

## Architecture

```text
YouTube URL / local file
        ↓
      yt-dlp
        ↓
       FFmpeg
        ↓
faster-whisper local
        ↓
word-timestamp transcript
        ↓
Ollama + fraktall-qwen
        ↓
Fraktall editorial ranking
        ↓
clip candidates + scores
        ↓
active-speaker reframe
        ↓
captions + zoom + tightening
        ↓
FFmpeg / NVENC export
```

## Validation

Start with a 10–20 minute Portuguese podcast before throwing a three-hour show at V0. See `docs/FIRST_TEST.md`.

GitHub Actions definitions are included for patch/type/test validation and Windows packaging. The initial connector-authored commits do not automatically trigger GitHub Actions, so the first CI run still needs to occur before the current V0 can be called CI-validated.

## Status

V0 personal/local build. The next technical milestone after first-machine validation is windowed long-podcast analysis + global candidate ranking + a dedicated context-integrity pass.

The cloud/SaaS/live-clipping layer comes later, after the local workflow proves itself.
