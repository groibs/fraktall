# Open-source bases considered

Fraktall should reuse mature infrastructure rather than reimplementing commodity video plumbing.

## Primary base

### JeremySNR/clip-forge

Role: desktop application and main V0 pipeline.

Already provides most of the product shell we need: Electron/React UI, yt-dlp URL import, project persistence, transcript-driven clip selection, editor, captions, FFmpeg export, NVENC fallback, active-speaker reframing, auto zoom, filler/silence tightening, branding and packaging.

License: MIT in the upstream repository. Preserve its LICENSE and notices.

Pinned V0 commit: `35814e546db958c6d66d4f82697bf6c2136d62af`.

## User-discovered projects to study later

These are not copied into V0. Treat them as architecture/implementation references until each repository's current license and code quality are reviewed.

- `Anil-matcha/AI-Youtube-Shorts-Generator` — URL/local input, faster-whisper, LLM highlight selection, vertical crop.
- `metaleey/AI-auto-segment-edit-video-pipeline` — semantic segmentation/value scoring concepts.
- `windstudio/recut-cli` — scene/motion analysis and CLI processing ideas.
- `jamesbaughnd/twitch-clip-miner` — multimodal highlight scoring for live/streaming use cases.
- `alperensumeroglu/ai-clips-maker` — WhisperX/Pyannote/speaker-oriented cropping ideas.
- `retroconsultantsieve/local-ai-video-maker-for-youtube-shorts-and-reels` — local generation pipeline; less relevant to clipping existing footage.
- `Trianglezichopper/submagic-core` — not used as a base; previously inspected repository did not expose a useful full editing pipeline for our V0.

## Rule for adding code

Before copying code from any secondary repository:

1. verify the exact license in the commit being used;
2. record source repository + commit;
3. preserve notices required by that license;
4. prefer isolated modules/adapters over mixing source indiscriminately;
5. add a test that proves the imported module improves Fraktall's current pipeline.

The goal is not to combine seven repositories blindly. The goal is to keep one coherent product and replace individual modules only when another implementation is objectively better.
