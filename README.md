# Fraktall

Local-first AI podcast/video clipper built on top of the MIT-licensed ClipForge project.

## V0 goal

Paste a YouTube/podcast URL or choose a local video and automatically generate ready-to-post vertical clips with:

- AI highlight selection
- podcast/editorial curation modes
- virality + editorial + context-integrity scoring
- word-level captions
- speaker-aware reframing
- auto zoom
- silence/filler tightening
- 9:16 / 1:1 / 16:9 exports
- local Whisper transcription
- local Qwen analysis through Ollama

No Supabase, Vercel, login, billing or cloud storage are required for the personal desktop build.

## Quick start on Windows

When you are on the PC that will process videos:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\setup.ps1
.\run-local.ps1
```

The setup script is designed to install/check the dependencies, download a pinned ClipForge source, apply the Fraktall patch, create the local Whisper environment and pull `qwen3:4b` in Ollama.

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
Ollama + Qwen3 4B
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

## Status

V0 personal/local build. The cloud/SaaS/live-clipping layer will come later, after the local podcast workflow is stable.
