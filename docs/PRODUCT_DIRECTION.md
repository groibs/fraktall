# Product direction: Fraktall Remote

This records the direction decided for the web + worker product (see
`docs/WEB_WORKER_MVP.md` for the original local-worker setup and
`docs/DEPLOY_VPS.md` for the current cloud-worker deployment), so the
reasoning behind it survives outside chat history. Supersedes any earlier
assumption that this phase was heading toward a fully cloud-hosted SaaS.

## 1. Architecture: hybrid (worker on infrastructure the user owns), not multi-tenant SaaS — decided

Fraktall Remote is **not** a multi-tenant "paste a link, we run it on our
shared infrastructure" product. It is a personal tool with a public web
panel and a worker that runs continuously on a server the user owns and
pays for — originally the user's own PC, now a small VPS:

```
browser → Vercel (panel) → Supabase (queue) → worker on the user's own server
          ↑                                    ├─ LM Studio or OpenAI (LLM)
          └────────────── result ──────────────┼─ local Whisper or OpenAI (transcription)
                                                 └─ FFmpeg (Shorts cut + upload to Supabase Storage)
```

- The **panel** (submit form, job list, worker status) is public and always
  on, hosted on Vercel — reachable from any device, no install.
- **All AI/video compute** runs on a worker process (`worker/worker.py`)
  that polls Supabase for queued jobs — originally on the user's Windows
  PC, now on a Hostinger VPS running 24/7 as a Docker container (see
  `docs/DEPLOY_VPS.md`), with OpenAI doing transcription and analysis
  instead of local LM Studio/Whisper. Nothing the worker talks to is ever
  exposed to the public internet; it only makes outbound calls.
- Moving the worker from the PC to a VPS did not require a rewrite, exactly
  because of the provider abstraction and queue design below — it was a
  deployment change (Dockerfile + `docs/DEPLOY_VPS.md`) plus flipping the
  default provider env vars, not new architecture.
- The distinction that matters isn't "local vs. cloud" — it's **single
  worker the user owns and pays for** vs. **shared multi-tenant compute
  billed by the product to many users**. This is still the former. Don't
  read "the worker moved to a VPS" as "now it should become a SaaS" — that
  question stays closed until the product owner explicitly reopens it.
- `worker.py`'s LLM calls go through a small `LLM_PROVIDER=lmstudio|openai`
  abstraction (defaults to `openai`), and `fraktall_jobs`/`fraktall_workers`
  in Supabase don't assume where a worker runs — multiple workers, or a
  worker migrating between machines, both just work.

This is a considered decision, not a placeholder — don't revisit "should
this be a multi-tenant SaaS" without the product owner explicitly reopening
it.

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
- Even after fixing the context-window sizing and adding retries (see
  `docs/WEB_WORKER_MVP.md` troubleshooting), repeated local-model crashes
  on real long videos are why OpenAI was added as a selectable provider
  (`LLM_PROVIDER=openai`, `TRANSCRIPTION_PROVIDER=openai` — see §1 and
  `docs/WEB_WORKER_MVP.md`) instead of continuing to chase local GPU
  stability. This doesn't change the architecture decision in §1 — the
  worker still runs locally either way — it only changes which side of
  the outbound HTTPS calls the AI compute happens on, and is opt-in
  (local LM Studio/Whisper remain the free default).

## 5. Explicitly deferred to a later phase

- Face tracking, active-speaker 9:16 reframing, caption burn-in. Basic
  16:9-crop Shorts rendering (ffmpeg cut, no reframe) shipped — see
  `docs/WEB_WORKER_MVP.md` — but the desktop engine's (`app/`,
  ClipForge-derived) reframe/caption logic is still not wired into the
  worker; extracting and reusing it is the plan, not a rebuild.
- Long-form (horizontal) rendering — only Shorts are rendered today.
- Structured Qwen 1.7B vs 4B A/B benchmarking (timing, token counts,
  candidate quality) beyond what a human can eyeball from two runs. The
  transcript-source metadata pattern (record it in `result`, show it in
  the dashboard) is the template to extend for this if it's wanted later.

**Resolved, not deferred:** moving the worker off the user's PC. The
earlier note here said this needed "real queue-driven infrastructure" to
work around Vercel serverless execution-time limits (minutes, not hours) —
that was true for hosting the worker *as a Vercel function*, but doesn't
apply to a VPS, which is a persistent server with no execution-time limit
at all. `docs/DEPLOY_VPS.md` covers running `worker/worker.py` as a Docker
container on a VPS (Hostinger), polling the same Supabase queue the same
way the PC-based worker did — no Vercel-hosted job execution involved, so
no rewrite was needed.

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
