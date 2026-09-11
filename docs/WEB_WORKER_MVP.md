# Fraktall Web + Local Worker MVP

This phase moves the control surface to the web without moving AI/video compute off the user's PC.

```text
Browser
  ↓
Vercel / Fraktall Web
  ↓
Supabase job queue
  ↓ outbound polling only
Fraktall Worker on Windows
  ├─ yt-dlp
  ├─ faster-whisper @ 127.0.0.1:8178
  └─ LM Studio / Qwen @ 127.0.0.1:1234
  ↓
Supabase result JSON
  ↓
Vercel dashboard
```

LM Studio is never exposed to the public internet. The PC initiates outbound HTTPS requests to Supabase, claims queued jobs, downloads the source, transcribes locally and analyzes transcript chunks locally.

## What this MVP does

- submit a YouTube/video URL from a Vercel-hosted dashboard;
- select curation mode and requested Shorts-per-segment count;
- let a Windows worker claim the job;
- get a transcript the cheap way first — YouTube manual captions, then
  auto-generated captions, then `youtube-transcript-api`, only downloading
  audio and running local Whisper if all of those fail (see
  `docs/PRODUCT_DIRECTION.md` §3);
- map the video into long-form segments (10-30+min, semantic
  start/development/conclusion, not fixed-length chopping);
- for each selected long-form segment, find the Shorts within it;
- return the long-form → Shorts hierarchy with virality/editorial/context/
  potential scores to the web dashboard.

The worker intentionally keeps first-pass output compact (compact
start/end/topic/scores, not full titles/hooks/descriptions for every
candidate). It does not ask the model for large summaries for every
candidate, avoiding the 8192-token overflow observed in the desktop
prototype. See `docs/PRODUCT_DIRECTION.md` for the full editorial pipeline
rationale.

## Rendering: basic downloadable Shorts (no reframe/captions yet)

When `RENDER_CLIPS=1` (the default), the worker downloads the full source
video once per job (only if at least one Short was selected), cuts each
selected Short with `ffmpeg` (via the bundled `imageio-ffmpeg`, no system
install needed), and uploads it to a `clips` bucket in Supabase Storage. Each
Short gets a 7-day signed download URL shown in the dashboard as "Baixar
corte". This is a straight center crop at the source aspect ratio — no
active-speaker reframing, no burned-in captions yet.

## Not migrated yet

- remote video preview;
- face/speaker tracking in the worker;
- 9:16 reframing and caption burn-in;
- long-form (horizontal) rendering — only Shorts are rendered today.

Those remain in the desktop engine until the next phase, which is to move
the existing render/reframe modules behind the worker.

## 1. Create the queue

Create a dedicated Supabase project. Open SQL Editor and run `infra/supabase.sql`.

Keep the **service-role key private**. It belongs only in Vercel server-side environment variables and on the local worker. It must never be exposed as `NEXT_PUBLIC_*`.

To enable downloadable clips, also create a Storage bucket (Supabase dashboard → **Storage → New bucket**): name it `clips`, leave it **private** (not public — the worker hands out signed, expiring URLs instead). No bucket policies are needed; the worker uses the service-role key, which bypasses Storage RLS.

## 2. Configure Vercel

Import the `groibs/fraktall` repository into Vercel and set **Root Directory** to `web`.

Add these environment variables:

```text
SUPABASE_URL=https://YOUR_PROJECT.supabase.co
SUPABASE_SERVICE_ROLE_KEY=...
FRAKTALL_ACCESS_TOKEN=choose-a-long-random-personal-token
```

Deploy. The access token is the password entered in the Fraktall web dashboard; it prevents arbitrary visitors from creating or reading jobs.

**Common pitfalls:**

- If the deployed site doesn't load at all, double-check **Root Directory** in
  Project Settings → General: it must be `web`, not the repo root or another
  subfolder.
- If the dashboard loads but every request returns "Não autorizado" (401),
  the `FRAKTALL_ACCESS_TOKEN` (and `SUPABASE_*`) variables are usually missing
  the **Production** environment checkbox — Vercel scopes each variable to
  Production/Preview/Development independently, so a variable added while
  testing a Preview deployment may not exist once you promote to Production.
  Edit each variable, enable Production, then trigger a new deployment
  (env var changes only take effect on deployments created after the change;
  redeploying an existing deployment reuses its original snapshot).

## 3. Configure the Windows worker

From `C:\dev\fraktall` after pulling this branch/change:

```powershell
Copy-Item worker\.env.example worker\.env.local
notepad worker\.env.local
```

Fill at least:

```text
SUPABASE_URL=...
SUPABASE_SERVICE_ROLE_KEY=...
FRAKTALL_WORKER_ID=lucas-pc
LMSTUDIO_BASE_URL=http://127.0.0.1:1234/v1
LMSTUDIO_MODEL=qwen/qwen3-1.7b
WHISPER_BASE_URL=http://127.0.0.1:8178/v1
WHISPER_MODEL=small
WHISPER_LANGUAGE=pt
```

Start LM Studio, load Qwen3 1.7B and start Local Server on port 1234. Then run:

## Using OpenAI instead of local LM Studio/Whisper

Every local AI step is behind a provider switch, independently:

```text
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini

TRANSCRIPTION_PROVIDER=openai
OPENAI_TRANSCRIBE_MODEL=whisper-1
```

With both set, the worker no longer touches LM Studio or local Whisper at
all — it still runs locally (it downloads the source and drives the
pipeline), but every AI call goes to OpenAI's API. This removes every local
GPU/VRAM/CUDA failure mode this project has hit so far, at the cost of
paying OpenAI per video processed. `TRANSCRIPTION_PROVIDER` only matters
when no YouTube caption track is found — most videos never reach it.

OpenAI's transcription endpoint rejects uploads over 25MB; the worker
automatically splits long audio into 15-minute chunks with `ffmpeg` before
uploading and stitches the timestamps back together, so long videos work
the same as short ones from the caller's side.

A cloud-hosted worker (so nothing runs on your PC at all) is a much bigger
step than switching providers — Vercel serverless functions have hard
execution-time limits (minutes, not hours), so a multi-hour video wouldn't
fit in one invocation regardless of which AI provider does the work. The
worker staying local (even when every AI call is remote) is the practical
choice until that's solved with its own infrastructure (a real queue-driven
cloud worker, not a Vercel function).

```powershell
.\run-worker.ps1
```

The launcher starts local Whisper if needed and waits for jobs. It does not open Electron.

## 4. Test

1. Open the Vercel URL from any device.
2. Enter the same `FRAKTALL_ACCESS_TOKEN` configured in Vercel.
3. Paste a short YouTube URL.
4. Choose `Podcast`, request 3-5 clips, and submit.
5. Keep the PC and LM Studio on.
6. Watch the job stage/progress update in the dashboard.

For the first remote test use a video around 5-10 minutes. Long podcasts are supported by chunking but should only be tested after the short path is validated. Use a video **over 12 minutes** to exercise the long-form segmentation pass itself (shorter videos are treated as one implicit long-form block).

## Troubleshooting

- **"Local Whisper failed to start" / `[Errno 10048]` address already in
  use on port 8178** — a previous worker run's Whisper subprocess is still
  alive (usually from closing the PowerShell window instead of Ctrl+C).
  Kill it and retry:
  ```powershell
  Get-NetTCPConnection -LocalPort 8178 -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess | ForEach-Object { Stop-Process -Id $_ -Force }
  ```
  Always stop `run-worker.ps1` with **Ctrl+C**, not by closing the window,
  so it can clean up the Whisper subprocess itself.

- **Whisper error `Library cublas64_12.dll is not found or cannot be
  loaded`** — CUDA is being attempted but the cuBLAS/cuDNN runtime isn't
  installed. Either run with `-WhisperDevice cpu`, or install the CUDA
  wheels (no full CUDA Toolkit needed) and retry with
  `-WhisperDevice cuda`:
  ```powershell
  .venv\Scripts\python.exe -m pip install nvidia-cublas-cu12 nvidia-cudnn-cu12
  ```
  `local-whisper/server.py` auto-discovers these wheels' DLL directories on
  Windows via `os.add_dll_directory`; no PATH edits needed.

- **LM Studio model not found / `RemoteDisconnected` mid-job** — see
  `docs/PRODUCT_DIRECTION.md` §4. `LMSTUDIO_MODEL` tolerates a near-match
  to LM Studio's actual model id, but a crash mid-job on a small GPU
  (4GB VRAM) usually means the loaded model is too large for the card; try
  a smaller model (Qwen3 1.7B is the known-good default) before assuming
  it's a bug.

- **Editing `worker/.env.local` didn't change anything** — `run-worker.ps1`
  now respects `WHISPER_MODEL` from the env file unless you pass
  `-WhisperModel` explicitly on the command line, which always wins. Model
  and device changes take effect on the **next** `run-worker.ps1` run, not
  live.

## Security model

- no inbound port on the home PC;
- no public LM Studio endpoint;
- no public Whisper endpoint;
- Vercel talks to Supabase, not to `localhost`;
- the worker uses outbound HTTPS only;
- source processing remains on the local PC;
- service-role secrets remain server-side/local only.
