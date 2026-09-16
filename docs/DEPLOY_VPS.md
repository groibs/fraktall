# Deploying the worker to a VPS (100% cloud, nothing local)

This replaces "keep your PC on with LM Studio running" with a small always-on
server you control. Once this is done, the only thing you ever touch is the
Vercel dashboard — no PowerShell, no LM Studio, no local Whisper.

```text
Browser
  ↓
Vercel / Fraktall Web  (dashboard, unchanged)
  ↓
Supabase job queue     (unchanged)
  ↓ outbound polling only
Fraktall Worker — Docker container on your VPS, running 24/7
  ├─ yt-dlp        (downloads the source video)
  ├─ OpenAI API    (transcription + editorial analysis)
  └─ FFmpeg        (cuts Shorts, uploads to Supabase Storage)
  ↓
Supabase result JSON
  ↓
Vercel dashboard
```

This is the same worker (`worker/worker.py`) and the same Supabase queue this
project has used from the start — only *where* the worker process runs
changes, from your Windows PC to a VPS. Nothing about the web dashboard or
the database changes. A VPS is a real, persistent server (unlike a Vercel
serverless function), so the execution-time limit that made "run the worker
in the cloud" impractical on Vercel doesn't apply here — see
`docs/PRODUCT_DIRECTION.md` §1/§5.

## Before you start

You should already have, from `docs/WEB_WORKER_MVP.md`:

1. A Supabase project with `infra/supabase.sql` applied, and a **private**
   `clips` Storage bucket created (Storage → New bucket → name `clips`).
2. The Vercel dashboard deployed and working (submitting jobs, even if
   nothing ever picks them up yet).
3. An OpenAI API key with billing enabled — the VPS worker uses OpenAI for
   both transcription and analysis by default now, so no GPU is needed on
   the VPS at all.

## 1. Provision the VPS (Hostinger)

In hPanel → VPS → **Configurar VPS**:

- **OS**: Ubuntu 24.04 LTS (plain OS image, not one of the app templates —
  the app catalog entries like "Docker manager"/"n8n" are for other
  products, you don't need them here; you'll install Docker yourself in one
  command below).
- **Plan**: KVM 2 (2 vCPU / 8 GB RAM) is a comfortable choice. All AI work
  happens on OpenAI's servers now, so the VPS itself only needs to handle
  video download and `ffmpeg` cutting — CPU/RAM bound, not GPU bound. KVM 1
  (1 vCPU / 4 GB) can work for light/occasional use but leaves little
  headroom if a long video is processing. Pricing and exact specs change,
  so check current numbers in hPanel before confirming.
- After creation, note the **VPS IP address** and **root password** Hostinger
  shows you (also emailed).

## 2. Connect to the VPS

Easiest option, no setup on your side: hPanel → VPS → your server →
**Browser terminal** — opens a terminal in the browser, already logged in as
root. Use that for every command below.

(Alternative: `ssh root@YOUR_VPS_IP` from your own PC if you'd rather use a
terminal you already have — same commands either way.)

## 3. Install Docker

```bash
curl -fsSL https://get.docker.com | sh
```

This is Docker's official install script; takes about a minute. Confirm it
worked:

```bash
docker --version
docker compose version
```

## 4. Get the code

```bash
git clone https://github.com/groibs/fraktall.git
cd fraktall/worker
```

## 5. Configure the worker

```bash
cp .env.example .env
nano .env
```

Fill in at minimum:

```text
SUPABASE_URL=https://YOUR_PROJECT.supabase.co
SUPABASE_SERVICE_ROLE_KEY=...
FRAKTALL_WORKER_ID=hostinger-vps
OPENAI_API_KEY=sk-...
```

`LLM_PROVIDER=openai` and `TRANSCRIPTION_PROVIDER=openai` are already the
defaults in `.env.example` — you don't need to add them, only the API key.
Save and exit nano with `Ctrl+O`, `Enter`, `Ctrl+X`.

## 6. Build and start it

```bash
docker compose up -d --build
```

This builds the worker image and starts it in the background with
`restart: unless-stopped` — it comes back automatically after a VPS reboot
or a crash, with no manual step.

Check it's alive:

```bash
docker compose logs -f
```

You should see something like:

```text
[fraktall-worker] id=hostinger-vps
[fraktall-worker] LLM provider=openai model=gpt-4o-mini
[fraktall-worker] Transcription provider=openai model=whisper-1
```

`Ctrl+C` only stops *watching* the logs — the container keeps running.
Confirm the same on the Vercel dashboard: the worker panel should switch to
"worker ativo" within about 10 seconds (the heartbeat interval).

## 7. Test end to end

From the Vercel dashboard, submit a short (5-10 min) YouTube URL. Watch the
job's stage/progress update — this now happens entirely from the VPS, your
PC can be off.

## Updating later

Whenever `worker/worker.py` changes on `main`:

```bash
cd fraktall
git pull origin main
cd worker
docker compose up -d --build
```

This rebuilds the image and replaces the running container; queued/claimed
jobs resume from Supabase state on the next poll, nothing is lost by a
worker restart.

## Costs

Two separate bills, both usage-based:

- **Hostinger VPS**: a fixed monthly cost regardless of how many videos you
  process (check current pricing in hPanel; KVM 2 promotional pricing has
  recently been in the ~$7-9/month range, ~$15/month at renewal — confirm
  the actual number shown at checkout).
- **OpenAI API**: billed per video processed — transcription (Whisper) and
  the editorial analysis calls (GPT-4o-mini by default, the cheaper end of
  OpenAI's chat models). This scales with usage; a quiet month costs very
  little, a month of processing many long videos costs more. Keep an eye on
  usage at platform.openai.com/usage, especially at first.

## Security model

Same as the local-worker setup, just relocated:

- the VPS makes outbound HTTPS calls only (Supabase, OpenAI, YouTube) — no
  inbound port needs to be opened for the worker itself;
- `SUPABASE_SERVICE_ROLE_KEY` and `OPENAI_API_KEY` live only in
  `worker/.env` on the VPS (never committed — it's gitignored) and in
  Vercel's server-side environment variables, never in the browser;
- the VPS's root password/SSH access is the new thing to keep safe — treat
  it like any other server credential (don't share the browser-terminal
  session, consider adding an SSH key and disabling password auth later if
  you want to harden it further, though that's optional for a
  single-worker personal setup).

## Troubleshooting

- **Container exits immediately after `docker compose up -d`** — run
  `docker compose logs` (no `-f`) to see why; almost always a missing
  required env var, reported clearly as `Missing environment variables:
  ...` (see `_require_env` in `worker/worker.py`) — recheck `.env`.
- **Dashboard never shows "worker ativo"** — confirm the container is
  actually running (`docker compose ps`), and that `SUPABASE_URL`/
  `SUPABASE_SERVICE_ROLE_KEY` in `worker/.env` match the same Supabase
  project Vercel is configured with (a copy-paste mismatch here is the most
  common cause).
- **A job fails immediately with an OpenAI error** — check
  `OPENAI_API_KEY` is valid and the OpenAI account has billing/credit
  enabled; `docker compose logs` prints the raw error from the call that
  failed.
