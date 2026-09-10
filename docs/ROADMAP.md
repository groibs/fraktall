# Fraktall roadmap

## V0 — personal podcast clipper

Goal: replace the useful part of an OpusClip subscription for one local user.

Implemented in the repository/bootstrap layer:

- pinned ClipForge 0.8.0 base
- reproducible Fraktall patcher
- PT-BR defaults
- local Ollama endpoint
- `qwen3:4b-instruct` default
- local faster-whisper OpenAI-compatible server
- Windows setup and launcher
- double-click `.bat` entrypoints
- cloud CI definition
- cloud Windows packaging definition
- curation modes: Viral, Podcast, Insight, News, Institutional, Custom
- separate virality, editorial and context-integrity scores
- weighted Fraktall ranking by curation mode

## V0.1 — first real-video validation

Run 3-5 real Portuguese podcasts through the pipeline and fix concrete failures before adding features.

Focus:

- transcription quality in PT-BR
- Qwen structured JSON reliability
- cut boundaries
- active-speaker crop quality
- caption timing/style
- export speed on GTX 1650
- VRAM/RAM behaviour
- YouTube import reliability

## V0.2 — long podcast intelligence

Do not send arbitrarily long transcripts as one prompt.

Planned pipeline:

1. split transcript into semantic/time windows with overlap
2. generate candidates per window
3. normalize scores across windows
4. merge and deduplicate candidates
5. perform a global second-pass ranking on candidate summaries
6. run context-integrity verification around each finalist using surrounding transcript

This is preferable for local models because large KV caches consume memory even when the model weights fit in VRAM.

## V0.3 — editorial intelligence

- dedicated context-integrity second pass using before/after transcript
- detect announcements, numbers, dates, promises, decisions and corrections
- identify speaker/entity importance
- configurable editorial brief for each video
- custom topics to prioritize/avoid
- stronger PT-BR title/caption generation
- rejection/approval feedback stored locally to learn user preference

## V0.4 — creator output pack

For every selected clip generate:

- 9:16 MP4 master
- optional 1:1 and 16:9 variants
- post title
- Reels/TikTok/Shorts caption
- hashtags
- suggested thumbnail frame
- transcript/SRT
- metadata JSON

## V0.5 — automation

- batch queue for multiple source videos
- watch folder
- export-all presets
- automatic file naming
- optional direct YouTube/TikTok/Instagram publishing where APIs allow it

## Later — Fraktall Cloud / Live

Only after the local pipeline proves useful:

- organizations/workspaces
- Supabase/Postgres
- object storage
- queue/workers
- authentication/RBAC
- billing
- browser editor
- live RTMP/SRT ingest and DVR
- real-time transcription
- live clip recommendations
- approval workflow
- audit logs
- government/agency deployment and private cloud options

Supabase and Vercel are intentionally not dependencies of V0.
