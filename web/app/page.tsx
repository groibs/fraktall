'use client'

import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react'

type Clip = {
  start: number
  end: number
  title?: string
  reason?: string
  selection_score?: number
  virality_score?: number
  editorial_score?: number
  context_integrity_score?: number
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
  result: { title?: string; clips?: Clip[] } | null
  error: string | null
}

const modes = [
  ['podcast', 'Podcast'],
  ['viral', 'Viral'],
  ['insight', 'Insight'],
  ['news', 'Notícia'],
  ['institutional', 'Institucional']
]

export default function Home() {
  const [token, setToken] = useState('')
  const [url, setUrl] = useState('')
  const [mode, setMode] = useState('podcast')
  const [clipCount, setClipCount] = useState(8)
  const [jobs, setJobs] = useState<Job[]>([])
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')

  useEffect(() => {
    setToken(localStorage.getItem('fraktall-token') ?? '')
  }, [])

  const authHeaders = useMemo(() => ({ 'x-fraktall-token': token }), [token])

  const refresh = useCallback(async () => {
    if (!token) return
    try {
      const res = await fetch('/api/jobs', { headers: authHeaders, cache: 'no-store' })
      if (!res.ok) return
      setJobs(await res.json())
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

  const workerOnline = jobs.some((j) => j.worker_id && ['claimed', 'running'].includes(j.status))

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
                <label>Nº de cortes</label>
                <input className="input" type="number" min={1} max={40} value={clipCount} onChange={(e) => setClipCount(Number(e.target.value))} />
              </div>
            </div>
            <button className="btn" disabled={busy || !url || !token}>{busy ? 'Enviando…' : 'Processar no meu PC'}</button>
            {message && <div className={message.toLowerCase().includes('erro') ? 'error' : 'muted'}>{message}</div>}
          </form>

          <div className="notice">
            Este primeiro MVP remoto retorna seleção, timestamps e scores. Render, face tracking e previews remotos entram na próxima etapa; o motor desktop atual continua disponível enquanto migramos essas partes.
          </div>
        </section>

        <aside className="card">
          <div className="statusline">
            <h2>Jobs recentes</h2>
            <span className="muted"><span className={`dot ${workerOnline ? 'online' : ''}`} style={{display:'inline-block',marginRight:6}} />{workerOnline ? 'worker ativo' : 'aguardando worker'}</span>
          </div>
          <div className="jobs">
            {jobs.length === 0 && <p className="muted">Nenhum job ainda.</p>}
            {jobs.map((job) => (
              <div className="job" key={job.id}>
                <div className="jobhead">
                  <div className="jobtitle">{job.result?.title || job.source_url}</div>
                  <span className="badge">{job.status}</span>
                </div>
                <div className="progress"><span style={{width:`${Math.max(0, Math.min(100, job.progress || 0))}%`}} /></div>
                <div className="meta"><span>{job.stage || 'na fila'}</span><span>{job.progress || 0}%</span></div>
                {job.error && <div className="error">{job.error}</div>}
                {job.result?.clips && (
                  <div className="clips">
                    {job.result.clips.slice(0, job.clip_count).map((clip, i) => (
                      <div className="clip" key={`${job.id}-${i}`}>
                        <strong>{i + 1}. {clip.title || 'Corte sugerido'}</strong>
                        <div className="muted">{formatTimestamp(clip.start)} – {formatTimestamp(clip.end)}</div>
                        <div className="scores">
                          <span className="score">Total {clip.selection_score ?? '—'}</span>
                          <span className="score">Viral {clip.virality_score ?? '—'}</span>
                          <span className="score">Editorial {clip.editorial_score ?? '—'}</span>
                          <span className="score">Contexto {clip.context_integrity_score ?? '—'}</span>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        </aside>
      </div>
    </main>
  )
}
