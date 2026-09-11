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
- select curation mode and requested clip count;
- let a Windows worker claim the job;
- download audio locally with yt-dlp;
- transcribe with the existing local faster-whisper server;
- analyze in bounded transcript chunks with LM Studio/Qwen3 1.7B using `/no_think`;
- return ranked timestamps and virality/editorial/context scores to the web dashboard.

The worker intentionally keeps first-pass output compact. It does not ask the model for large summaries/hashtags for every candidate, avoiding the 8192-token overflow observed in the desktop prototype.

## Not migrated yet

- remote video preview;
- face/speaker tracking in the worker;
- final vertical rendering;
- caption burn-in;
- storage/delivery of rendered MP4 files.

Those remain in the desktop engine until the next phase. The next migration step is to move the existing render/reframe modules behind the worker and upload only final clips/previews to object storage.

## 1. Create the queue

Create a dedicated Supabase project. Open SQL Editor and run `infra/supabase.sql`.

Keep the **service-role key private**. It belongs only in Vercel server-side environment variables and on the local worker. It must never be exposed as `NEXT_PUBLIC_*`.

## 2. Configure Vercel

Import the `groibs/fraktall` repository into Vercel and set **Root Directory** to `web`.

Add these environment variables:

```text
SUPABASE_URL=https://YOUR_PROJECT.supabase.co
SUPABASE_SERVICE_ROLE_KEY=...
FRAKTALL_ACCESS_TOKEN=choose-a-long-random-personal-token
```

Deploy. The access token is the password entered in the Fraktall web dashboard; it prevents arbitrary visitors from creating or reading jobs.

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

For the first remote test use a video around 5-10 minutes. Long podcasts are supported by chunking but should only be tested after the short path is validated.

## Security model

- no inbound port on the home PC;
- no public LM Studio endpoint;
- no public Whisper endpoint;
- Vercel talks to Supabase, not to `localhost`;
- the worker uses outbound HTTPS only;
- source processing remains on the local PC;
- service-role secrets remain server-side/local only.
