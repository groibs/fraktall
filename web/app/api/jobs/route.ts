import { NextRequest, NextResponse } from 'next/server'

function env(name: string): string {
  const value = process.env[name]?.trim()
  if (!value) throw new Error(`Missing environment variable: ${name}`)
  return value.replace(/\/$/, '')
}

function authorized(req: NextRequest): boolean {
  const expected = process.env.FRAKTALL_ACCESS_TOKEN?.trim()
  const received = req.headers.get('x-fraktall-token')?.trim()
  return Boolean(expected && received && expected === received)
}

async function supabase(path: string, init: RequestInit = {}) {
  const base = env('SUPABASE_URL')
  const key = env('SUPABASE_SERVICE_ROLE_KEY')
  return fetch(`${base}/rest/v1/${path}`, {
    ...init,
    headers: {
      apikey: key,
      Authorization: `Bearer ${key}`,
      'Content-Type': 'application/json',
      ...(init.headers || {})
    },
    cache: 'no-store'
  })
}

export async function GET(req: NextRequest) {
  if (!authorized(req)) return NextResponse.json({ error: 'Não autorizado.' }, { status: 401 })
  try {
    const res = await supabase(
      'fraktall_jobs?select=id,source_url,status,stage,progress,curation_mode,clip_count,worker_id,created_at,result,error&order=created_at.desc&limit=20'
    )
    const body = await res.json()
    if (!res.ok) return NextResponse.json({ error: body?.message || 'Falha ao listar jobs.' }, { status: 500 })
    return NextResponse.json(body)
  } catch (err) {
    return NextResponse.json({ error: err instanceof Error ? err.message : 'Erro interno.' }, { status: 500 })
  }
}

export async function POST(req: NextRequest) {
  if (!authorized(req)) return NextResponse.json({ error: 'Não autorizado.' }, { status: 401 })
  try {
    const body = await req.json()
    const sourceUrl = String(body.sourceUrl || '').trim()
    const curationMode = String(body.curationMode || 'podcast').trim()
    const clipCount = Math.max(1, Math.min(40, Number(body.clipCount || 8)))
    if (!/^https?:\/\//i.test(sourceUrl)) {
      return NextResponse.json({ error: 'Informe uma URL válida.' }, { status: 400 })
    }
    const allowedModes = new Set(['viral', 'podcast', 'insight', 'news', 'institutional'])
    if (!allowedModes.has(curationMode)) {
      return NextResponse.json({ error: 'Modo de curadoria inválido.' }, { status: 400 })
    }

    const res = await supabase('fraktall_jobs', {
      method: 'POST',
      headers: { Prefer: 'return=representation' },
      body: JSON.stringify({
        source_url: sourceUrl,
        curation_mode: curationMode,
        clip_count: clipCount,
        status: 'queued',
        stage: 'Aguardando worker',
        progress: 0
      })
    })
    const data = await res.json()
    if (!res.ok) return NextResponse.json({ error: data?.message || 'Falha ao criar job.' }, { status: 500 })
    return NextResponse.json(Array.isArray(data) ? data[0] : data, { status: 201 })
  } catch (err) {
    return NextResponse.json({ error: err instanceof Error ? err.message : 'Erro interno.' }, { status: 500 })
  }
}
