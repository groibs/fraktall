'use client'

import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react'

type Short = {
  start: number
  end: number
  title?: string
  reason?: string
  selection_score?: number
  virality_score?: number
  editorial_score?: number
  context_integrity_score?: number
  download_url?: string
}

type LongForm = {
  start: number
  end: number
  topic?: string
  reason?: string
  selection_score?: number
  editorial_score?: number
  context_integrity_score?: number
  potential_score?: number
  shorts?: Short[]
}

type Transcript = {
  source?: string
  language?: string
  fetch_seconds?: number
}

type JobResult = {
  title?: string
  transcript?: Transcript
  long_form?: LongForm[]
  clips?: Short[] // legacy flat shape, kept for jobs processed before the long-form pipeline
}

type Job = {
  id: string
  source_url: string
  status: string
  stage: string | null
  progress: number
  curation_mode: string
  clip_count: number
  worker_id: string | null
  created_at: string
  result: JobResult | null
  error: string | null
}

type Worker = {
  id: string
  status: string
  current_job: string | null
  last_seen: string
  metadata?: {
    llm_provider?: string
    lmstudio_model?: string
    lmstudio_base?: string
    whisper_model?: string
  }
}

const modes = [
  ['podcast', 'Podcast'],
  ['viral', 'Viral'],
  ['insight', 'Insight'],
  ['news', 'Notícia'],
  ['institutional', 'Institucional']
]

const TRANSCRIPT_SOURCE_LABELS: Record<string, string> = {
  youtube_manual: 'Legenda manual do YouTube',
  youtube_auto: 'Legenda automática do YouTube',
  youtube_transcript_api: 'Transcript alternativo do YouTube',
  whisper_local: 'Whisper local'
}

function formatTimestamp(seconds: number): string {
  const total = Math.max(0, Math.round(seconds))
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = total % 60
  const mm = h > 0 ? String(m).padStart(2, '0') : String(m)
  const ss = String(s).padStart(2, '0')
  return h > 0 ? `${h}:${mm}:${ss}` : `${mm}:${ss}`
}

function secondsAgo(iso: string): number {
  return Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000))
}

function ShortCard({ short, index }: { short: Short; index: number }) {
  return (
    <div className="clip">
      <strong>{index + 1}. {short.title || 'Corte sugerido'}</strong>
      <div className="muted">{formatTimestamp(short.start)} – {formatTimestamp(short.end)}</div>
      <div className="scores">
        <span className="score">Total {short.selection_score ?? '—'}</span>
        <span className="score">Viral {short.virality_score ?? '—'}</span>
        <span className="score">Editorial {short.editorial_score ?? '—'}</span>
        <span className="score">Contexto {short.context_integrity_score ?? '—'}</span>
      </div>
      {short.download_url && (
        <a className="download" href={short.download_url} target="_blank" rel="noreferrer">Baixar corte</a>
      )}
    </div>
  )
}

export default function Home() {
  const [token, setToken] = useState('')
  const [url, setUrl] = useState('')
  const [mode, setMode] = useState('podcast')
  const [clipCount, setClipCount] = useState(3)
  const [jobs, setJobs] = useState<Job[]>([])
  const [workers, setWorkers] = useState<Worker[]>([])
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')

  useEffect(() => {
    setToken(localStorage.getItem('fraktall-token') ?? '')
  }, [])

  const authHeaders = useMemo(() => ({ 'x-fraktall-token': token }), [token])

  const refresh = useCallback(async () => {
    if (!token) return
    try {
      const [jobsRes, workersRes] = await Promise.all([
        fetch('/api/jobs', { headers: authHeaders, cache: 'no-store' }),
        fetch('/api/workers', { headers: authHeaders, cache: 'no-store' })
      ])
      if (jobsRes.ok) setJobs(await jobsRes.json())
      if (workersRes.ok) setWorkers(await workersRes.json())
    } catch {
      // Keep the last known state during transient network failures.
    }
  }, [authHeaders, token])

  useEffect(() => {
    refresh()
    const timer = setInterval(refresh, 3000)
    return () => clearInterval(timer)
  }, [refresh])

  async function submit(e: FormEvent) {
    e.preventDefault()
    if (!token || !url) return
    setBusy(true)
    setMessage('')
    localStorage.setItem('fraktall-token', token)
    try {
      const res = await fetch('/api/jobs', {
        method: 'POST',
        headers: { ...authHeaders, 'Content-Type': 'application/json' },
        body: JSON.stringify({ sourceUrl: url, curationMode: mode, clipCount })
      })
      const body = await res.json()
      if (!res.ok) throw new Error(body.error || 'Não foi possível criar o job.')
      setUrl('')
      setMessage('Job enviado para o worker local.')
      await refresh()
    } catch (err) {
      setMessage(err instanceof Error ? err.message : 'Erro ao criar job.')
    } finally {
      setBusy(false)
    }
  }

  const worker = workers[0]
  const workerOnline = Boolean(worker && worker.status !== 'offline' && secondsAgo(worker.last_seen) < 30)
  const lmStudioModel = worker?.metadata?.lmstudio_model

  return (
    <main className="shell">
      <div className="topbar">
        <div className="brand"><span className="mark">F</span> Fraktall <span className="pill">Remote</span></div>
        <span className="muted">Vercel → fila → seu PC → LM Studio</span>
      </div>

      <div className="grid">
        <section className="card">
          <h1>Envie um vídeo. Seu PC faz o trabalho pesado.</h1>
          <p>O painel fica na web, mas LM Studio e Whisper continuam locais. O vídeo-fonte não precisa ser processado pela Vercel.</p>

          <form className="form" onSubmit={submit}>
            <div className="field">
              <label>Chave pessoal do painel</label>
              <input className="input" type="password" value={token} onChange={(e) => setToken(e.target.value)} placeholder="FRAKTALL_ACCESS_TOKEN" />
            </div>
            <div className="field">
              <label>URL do YouTube / vídeo</label>
              <input className="input" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://www.youtube.com/watch?v=..." />
            </div>
            <div className="row">
              <div className="field">
                <label>Curadoria</label>
                <select className="select" value={mode} onChange={(e) => setMode(e.target.value)}>
                  {modes.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                </select>
              </div>
              <div className="field">
                <label>Shorts por bloco longo</label>
                <input className="input" type="number" min={1} max={10} value={clipCount} onChange={(e) => setClipCount(Number(e.target.value))} />
              </div>
            </div>
            <button className="btn" disabled={busy || !url || !token}>{busy ? 'Enviando…' : 'Processar no meu PC'}</button>
            {message && <div className={message.toLowerCase().includes('erro') ? 'error' : 'muted'}>{message}</div>}
          </form>

          <div className="notice">
            O Fraktall primeiro mapeia o vídeo original em blocos longos (horizontais) com começo, meio e fim, e depois busca
            os melhores Shorts dentro de cada bloco. Render final, face tracking e previews remotos entram na próxima etapa;
            o motor desktop atual continua disponível enquanto migramos essas partes.
          </div>
        </section>

        <aside className="card">
          <div className="statusline">
            <h2>Jobs recentes</h2>
            <span className="muted"><span className={`dot ${workerOnline ? 'online' : ''}`} style={{display:'inline-block',marginRight:6}} />{workerOnline ? 'worker ativo' : 'aguardando worker'}</span>
          </div>
          {worker && (
            <div className="workerpanel">
              <span>{worker.id}</span>
              <span>{workerOnline ? `último heartbeat ${secondsAgo(worker.last_seen)}s atrás` : 'offline'}</span>
              {lmStudioModel && <span>LM Studio: {lmStudioModel}</span>}
            </div>
          )}
          <div className="jobs">
            {jobs.length === 0 && <p className="muted">Nenhum job ainda.</p>}
            {jobs.map((job) => {
              const transcript = job.result?.transcript
              const longForm = job.result?.long_form
              const legacyClips = job.result?.clips

              return (
                <div className="job" key={job.id}>
                  <div className="jobhead">
                    <div className="jobtitle">{job.result?.title || job.source_url}</div>
                    <span className="badge">{job.status}</span>
                  </div>
                  <div className="progress"><span style={{width:`${Math.max(0, Math.min(100, job.progress || 0))}%`}} /></div>
                  <div className="meta"><span>{job.stage || 'na fila'}</span><span>{job.progress || 0}%</span></div>
                  {job.error && <div className="error">{job.error}</div>}

                  {transcript?.source && (
                    <div className="muted" style={{marginTop:8}}>
                      Transcrição: {TRANSCRIPT_SOURCE_LABELS[transcript.source] || transcript.source}
                      {typeof transcript.fetch_seconds === 'number' && ` · obtida em ${transcript.fetch_seconds.toFixed(1)}s`}
                    </div>
                  )}

                  {longForm && longForm.length > 0 && (
                    <div className="clips">
                      {longForm.map((lf, i) => (
                        <div className="longform" key={`${job.id}-lf-${i}`}>
                          <div className="longformhead">
                            <strong>{String(i + 1).padStart(2, '0')} — {lf.topic || 'Bloco sugerido'}</strong>
                            <span className="muted">{formatTimestamp(lf.start)} – {formatTimestamp(lf.end)}</span>
                          </div>
                          <div className="scores">
                            <span className="score">Total {lf.selection_score ?? '—'}</span>
                            <span className="score">Editorial {lf.editorial_score ?? '—'}</span>
                            <span className="score">Contexto {lf.context_integrity_score ?? '—'}</span>
                            <span className="score">Potencial {lf.potential_score ?? '—'}</span>
                          </div>
                          {lf.shorts && lf.shorts.length > 0 && (
                            <div className="shorts">
                              {lf.shorts.map((short, si) => <ShortCard key={`${job.id}-lf-${i}-s-${si}`} short={short} index={si} />)}
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  )}

                  {!longForm && legacyClips && legacyClips.length > 0 && (
                    <div className="clips">
                      {legacyClips.slice(0, job.clip_count).map((clip, i) => <ShortCard key={`${job.id}-${i}`} short={clip} index={i} />)}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </aside>
      </div>
    </main>
  )
}
