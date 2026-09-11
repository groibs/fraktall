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
      'fraktall_workers?select=id,status,current_job,last_seen,metadata&order=last_seen.desc&limit=10'
    )
    const body = await res.json()
    if (!res.ok) return NextResponse.json({ error: body?.message || 'Falha ao listar workers.' }, { status: 500 })
    return NextResponse.json(body)
  } catch (err) {
    return NextResponse.json({ error: err instanceof Error ? err.message : 'Erro interno.' }, { status: 500 })
  }
}
