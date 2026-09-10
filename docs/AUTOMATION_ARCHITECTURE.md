# Fraktall autonomous content loop

## Goal

Keep Fraktall's media engine independent from the automation/orchestration layer.

The autonomous system is split into five concerns:

1. **Discovery** — detect new eligible source videos/lives from approved channels.
2. **Processing** — submit a Fraktall job and generate ranked clips.
3. **Publishing** — publish or stage selected clips for YouTube Shorts, TikTok and Instagram Reels.
4. **Measurement** — collect performance metrics at defined checkpoints.
5. **Learning** — update ranking priors and editorial preferences from actual outcomes.

## Recommended architecture

```text
Approved source registry
        ↓
YouTube push notification / polling / RSS / webhook
        ↓
Orchestrator (n8n initially or small custom service)
        ↓
Fraktall Job API / queue
        ↓
Fraktall GPU/CPU worker
        ↓
clips + transcript + metadata + scores
        ↓
Policy gate
  ├── reject
  ├── review queue
  └── publish
        ↓
Platform adapters
  ├── YouTube Shorts
  ├── TikTok
  └── Instagram Reels
        ↓
Metrics collector
        ↓
Performance store
        ↓
Learning/ranking update
        ↺
```

## n8n's role

n8n is useful for the first version because discovery, schedules, webhooks, HTTP APIs, OAuth flows, notifications and branching are orchestration work.

Do **not** make n8n responsible for video processing, model execution or large binary storage. Fraktall owns media processing; n8n only submits jobs and reacts to states.

A future custom orchestrator can replace n8n without changing Fraktall because the boundary is the job contract in `automation/job.schema.json`.

## Source registry

Never crawl the entire internet blindly. Maintain an explicit allow-list of sources that can legally and operationally be clipped.

Suggested fields:

- platform
- channel ID
- channel name
- source URL
- rights/permission profile
- allowed destinations
- content categories
- preferred curation mode
- default clip count
- minimum context-integrity threshold
- auto-publish allowed? yes/no
- notes / evidence of authorization

## Discovery

### YouTube

Prefer YouTube push notifications (PubSubHubbub) for channel uploads when possible. Polling the channel uploads playlist is the fallback.

Live workflows can create a source event when a live starts or after the VOD becomes available. Live clipping itself is a separate later subsystem.

### Other platforms

Use official webhooks/APIs when available. If no reliable event interface exists, scheduled polling belongs in the orchestrator, not in Fraktall.

## Processing contract

The orchestrator submits a job matching `automation/job.schema.json`.

Example behavior:

- source URL: podcast episode
- curation mode: podcast
- target clips: 12
- context integrity >= 75
- speaker framing: dynamic
- captions: on
- aspect: 9:16
- publishing: draft

The Fraktall worker should produce:

- original source metadata
- transcript with word timestamps
- candidate clips
- selected clips
- virality/editorial/context scores
- title/hook/summary/hashtags
- render files
- SRT/VTT
- machine-readable manifest
- provenance timestamps for every cut

## Policy gate

Do not let the ranking model directly publish everything.

Recommended modes:

- `none`: export only
- `draft`: prepare platform drafts / review queue
- `auto`: publish only when source and score policy explicitly permit it

Possible auto-publish policy:

```text
rightsProfile allows destination
AND selectionScore >= 82
AND contextIntegrity >= 90
AND no duplicate topic in last 48h
AND no safety/editorial flag
```

For personal experimentation, start in `draft`. Move individual approved source profiles to `auto` only after observing failures.

## Metrics checkpoints

Store metrics as time series, not only final totals.

Suggested checkpoints:

- +1h
- +6h
- +24h
- +72h
- +7d

Per post store, when available:

- impressions
- views / engaged views
- average view duration
- average view percentage
- likes
- comments
- shares
- subscribers/followers gained
- estimated revenue when the platform exposes it to the authenticated owner

Also derive normalized metrics:

- views per impression
- completion / retention score
- likes per 1,000 views
- comments per 1,000 views
- shares per 1,000 views
- subscribers per 1,000 views
- revenue per 1,000 views
- performance relative to channel baseline

## Learning loop

Do not immediately fine-tune a model. Start with a cheap ranking layer.

For every published clip persist features such as:

- source channel
- source duration
- topic/category
- speaker(s)
- clip duration
- hook type
- curation mode
- virality score
- editorial score
- context score
- vocal energy
- visual framing mode
- caption style
- posting hour/day
- title pattern
- presence of question / number / controversy / story / reveal

Then calculate an outcome score normalized by channel and age of post.

V1 learning can be simple weighted statistics / regression:

```text
predictedPerformance =
  modelScore
  + learnedTopicPrior
  + learnedDurationPrior
  + learnedHookPrior
  + learnedSourcePrior
  + learnedPostingTimePrior
```

Only after enough examples should we consider a learned ranker or fine-tuning.

## Avoid the bad feedback-loop trap

Raw views are a bad single objective. A system trained only on views will increasingly select sensational or repetitive clips.

Keep separate objectives:

- reach
- retention
- engagement
- editorial value
- context integrity
- source diversity

Use hard floors for context integrity rather than allowing high views to compensate for misleading cuts.

## Storage

Personal V0:

- SQLite or JSONL for jobs/metrics
- local filesystem for video

Automation V1:

- Postgres for jobs, sources, posts and metrics
- object storage for rendered media if workers are remote
- Redis/BullMQ only when multiple processing workers are needed

Supabase is reasonable later for Postgres/Auth/dashboard, but it is not needed for the first local autonomous loop.

## Suggested implementation phases

### Phase A — now

- stable job schema
- source provenance fields
- metadata manifest
- explicit publishing modes
- performance metric schema

### Phase B — first automation

- n8n or small Node/Python service
- approved YouTube source list
- upload notification/polling
- submit Fraktall job
- draft outputs

### Phase C — publishing

- YouTube OAuth adapter
- TikTok Content Posting adapter
- Instagram adapter
- review queue and per-source auto-publish policy

### Phase D — feedback

- scheduled metric collection
- baseline normalization
- outcome score
- ranking priors

### Phase E — autonomous operation

- automatic source discovery within approved policies
- automatic processing
- selective auto-publishing
- continuous ranking adaptation
- alert only on failures/anomalies
