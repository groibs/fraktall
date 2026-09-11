# Product direction: Fraktall Remote

This records the direction decided for the web + local worker product (see
`docs/WEB_WORKER_MVP.md` for the technical setup), so the reasoning behind it
survives outside chat history. Supersedes any earlier assumption that this
phase was heading toward a fully cloud-hosted SaaS.

## 1. Architecture: hybrid, not SaaS — decided

Fraktall Remote is **not** "paste a link, everything happens in the cloud."
It is:

```
browser → Vercel (panel) → Supabase (queue) → local worker on the user's PC
          ↑                                    ├─ LM Studio (LLM)
          └────────────── result ──────────────┼─ local Whisper (fallback)
                                                 └─ FFmpeg (future: render)
```

- The **panel** (submit form, job list, worker status) is public and always
  on, hosted on Vercel — reachable from any device, no install.
- **All AI/video compute** (transcription, editorial analysis, and
  eventually rendering) runs on the user's own PC, driven by a worker
  process (`worker/worker.py`) that polls Supabase for queued jobs. LM
  Studio and Whisper are never exposed to the internet; the worker only
  makes outbound calls.
- This keeps per-video compute cost at zero (no cloud GPU/transcription/LLM
  billing) at the cost of requiring the user's PC to be on and the worker
  running whenever a job needs to process.
- A cloud provider can be swapped in later without a rewrite: `worker.py`'s
  LLM calls already go through a small `LLM_PROVIDER=lmstudio|openai`
  abstraction, and `fraktall_jobs`/`fraktall_workers` in Supabase don't
  assume where a worker runs. Moving compute to cloud workers later is an
  additive change, not a rebuild.

This is a considered decision, not a placeholder — don't revisit "should
this be a SaaS" without the product owner explicitly reopening it.

## 2. It's not a Shorts generator — it's an editorial tree

The pipeline turns one long recording into a navigable hierarchy, not a
flat pile of vertical clips:

```
original recording (55min, 2h, 3h, ...)
        ↓
transcript (see acquisition strategy below)
        ↓
long-form segmentation — semantic topic map
        ↓
long-form segments (10-30+min each, natural start/development/conclusion;
        │            NOT fixed-length chopping; a video may yield 3 segments
        │            or 8, whatever the content actually supports)
        ↓
for each selected long-form segment
        ↓
Shorts derived from THAT segment's own transcript slice only
        (~3 per segment when the material supports it; never invented
         to hit a quota)
```

Implemented in `worker/worker.py` as two LLM passes: `build_long_form_segments`
(chunk the whole transcript into large windows, ask for semantically
complete blocks, merge candidates split across a chunk boundary, then
rank/deduplicate by overlap) and `shorts_for_longform` (reuses the
short-form scoring, scoped to one long-form's time range and given that
segment's topic as context). Videos under `LONGFORM_MIN_VIDEO_SECONDS`
(12 minutes) skip segmentation — the whole video is treated as one implicit
long-form block, since splitting a short video into "topics" is busywork,
not editorial value.

## 3. Transcript acquisition: cascade, cheapest first

Whisper is a **fallback**, not the default. Order, implemented in
`fetch_transcript`:

1. YouTube manual captions (via `yt-dlp`)
2. YouTube auto-generated captions (via `yt-dlp`)
3. `youtube-transcript-api` (independent library/maintainer — real
   redundancy if `yt-dlp` breaks on a YouTube change, not a rename of the
   same code path)
4. Local Whisper — only reached if 1-3 all fail; only tier that downloads
   audio

Audio/video is never downloaded unless every faster tier fails. Each job's
result records which tier won and how long it took
(`result.transcript.source` / `.fetch_seconds`), shown in the dashboard, so
this can be measured over real usage rather than assumed.

Internal source keys: `youtube_manual`, `youtube_auto`,
`youtube_transcript_api`, `whisper_local`.

## 4. Local model notes (LM Studio)

- `LMSTUDIO_MODEL` doesn't need to match a loaded model's reported id
  exactly — `resolve_llm_model()` falls back to a substring match and logs
  which id it actually used. Still set it as close to correct as you can;
  the fallback is a safety net, not a substitute for checking LM Studio's
  own "API Model Identifier" field.
- **VRAM matters more than the spec sheet suggests.** On a 4GB card (GTX
  1650), Qwen3 **1.7B** has run a full job successfully. Qwen3 **4B
  Q4_K_M** failed mid-job with `RemoteDisconnected` — almost certainly LM
  Studio's backend crashing/restarting under memory pressure from the
  larger model plus the long-form pass's bigger prompts (~35min transcript
  windows). Treat 4B on a 4GB card as unproven until it completes a
  long-form job end to end; 1.7B is the known-good default for now.
- `/no_think`, temperature 0.1, and strict JSON-schema `response_format`
  are used for every LLM call (both long-form and Shorts passes) to avoid
  the earlier failure mode where an unbounded prompt made the model
  reason at length, overflow context, and get truncated/retried.

## 5. Explicitly deferred to a later phase

- Rendering (FFmpeg horizontal/vertical export), face tracking,
  active-speaker reframing, caption burn-in. The desktop engine
  (`app/`, ClipForge-derived) already has working versions of these; the
  plan is to extract and reuse that logic behind the worker, not rebuild
  it. Until then, `long_form[].shorts[]` gives timestamps only — no
  rendered files.
- Structured Qwen 1.7B vs 4B A/B benchmarking (timing, token counts,
  candidate quality) beyond what a human can eyeball from two runs. The
  transcript-source metadata pattern (record it in `result`, show it in
  the dashboard) is the template to extend for this if it's wanted later.
- Any cloud-compute/SaaS pivot (see §1) — not happening this phase.

## 6. Where this came from

Implemented across:
- [#2](https://github.com/groibs/fraktall/pull/2) — fixed the Vercel deploy
  (wrong Root Directory), local Whisper CUDA fallback, YouTube-captions
  fast path (first version), model/config fixes.
- [#3](https://github.com/groibs/fraktall/pull/3) — the long-form/Shorts
  hierarchy, transcript cascade (added `youtube-transcript-api` and the
  manual/auto split), provider abstraction, worker status API.

See `docs/WEB_WORKER_MVP.md` for setup/troubleshooting and
`docs/ROADMAP.md` for how this phase (originally scoped there as "V0.2 —
long podcast intelligence") relates to the desktop-app roadmap.
