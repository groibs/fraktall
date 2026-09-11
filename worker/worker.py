from __future__ import annotations

import json
import math
import os
import socket
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests
import yt_dlp


SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
WORKER_ID = os.environ.get("FRAKTALL_WORKER_ID", socket.gethostname()).strip() or socket.gethostname()
LMSTUDIO_BASE_URL = os.environ.get("LMSTUDIO_BASE_URL", "http://127.0.0.1:1234/v1").rstrip("/")
LMSTUDIO_MODEL = os.environ.get("LMSTUDIO_MODEL", "qwen/qwen3-1.7b").strip()
WHISPER_BASE_URL = os.environ.get("WHISPER_BASE_URL", "http://127.0.0.1:8178/v1").rstrip("/")
WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "small").strip()
WHISPER_LANGUAGE = os.environ.get("WHISPER_LANGUAGE", "pt").strip()
POLL_SECONDS = max(1.0, float(os.environ.get("POLL_SECONDS", "3")))

SESSION = requests.Session()


@dataclass
class Segment:
    start: float
    end: float
    text: str


def _require_env() -> None:
    missing = []
    if not SUPABASE_URL:
        missing.append("SUPABASE_URL")
    if not SUPABASE_KEY:
        missing.append("SUPABASE_SERVICE_ROLE_KEY")
    if missing:
        raise SystemExit("Missing environment variables: " + ", ".join(missing))


def _supa_headers(prefer: str | None = None) -> dict[str, str]:
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
    }
    if prefer:
        headers["Prefer"] = prefer
    return headers


def _supa(method: str, path: str, *, json_body: Any | None = None, prefer: str | None = None) -> requests.Response:
    res = SESSION.request(
        method,
        f"{SUPABASE_URL}/rest/v1/{path}",
        headers=_supa_headers(prefer),
        json=json_body,
        timeout=30,
    )
    if not res.ok:
        raise RuntimeError(f"Supabase {method} {path} failed: HTTP {res.status_code} {res.text[:500]}")
    return res


def _now_iso() -> str:
    # PostgREST accepts this ISO timestamp; database default timezone is UTC.
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def heartbeat(status: str = "idle", current_job: str | None = None) -> None:
    payload = {
        "id": WORKER_ID,
        "status": status,
        "current_job": current_job,
        "last_seen": _now_iso(),
        "metadata": {
            "lmstudio_model": LMSTUDIO_MODEL,
            "lmstudio_base": LMSTUDIO_BASE_URL,
            "whisper_model": WHISPER_MODEL,
        },
    }
    _supa(
        "POST",
        "fraktall_workers?on_conflict=id",
        json_body=payload,
        prefer="resolution=merge-duplicates,return=minimal",
    )


def update_job(job_id: str, **fields: Any) -> None:
    fields["updated_at"] = _now_iso()
    _supa(
        "PATCH",
        f"fraktall_jobs?id=eq.{job_id}",
        json_body=fields,
        prefer="return=minimal",
    )


def claim_next_job() -> dict[str, Any] | None:
    res = _supa(
        "GET",
        "fraktall_jobs?status=eq.queued&select=*&order=created_at.asc&limit=1",
    )
    rows = res.json()
    if not rows:
        return None

    job = rows[0]
    job_id = job["id"]
    claim = SESSION.patch(
        f"{SUPABASE_URL}/rest/v1/fraktall_jobs?id=eq.{job_id}&status=eq.queued",
        headers=_supa_headers("return=representation"),
        json={
            "status": "claimed",
            "worker_id": WORKER_ID,
            "claimed_at": _now_iso(),
            "stage": "Worker assumiu o job",
            "progress": 2,
            "updated_at": _now_iso(),
        },
        timeout=30,
    )
    if not claim.ok:
        raise RuntimeError(f"Could not claim job {job_id}: {claim.status_code} {claim.text[:500]}")
    claimed_rows = claim.json()
    return claimed_rows[0] if claimed_rows else None


def check_lmstudio() -> None:
    lm = SESSION.get(f"{LMSTUDIO_BASE_URL}/models", timeout=10)
    if not lm.ok:
        raise RuntimeError(f"LM Studio is unavailable: HTTP {lm.status_code}")
    ids = {m.get("id") for m in lm.json().get("data", [])}
    if LMSTUDIO_MODEL not in ids:
        raise RuntimeError(
            f"LM Studio model {LMSTUDIO_MODEL!r} is not available. Loaded/known models: {sorted(x for x in ids if x)}"
        )


def check_whisper() -> None:
    whisper = SESSION.get(WHISPER_BASE_URL.rsplit("/v1", 1)[0] + "/health", timeout=10)
    if not whisper.ok:
        raise RuntimeError(f"Local Whisper is unavailable: HTTP {whisper.status_code}")


def download_audio(source_url: str, job_id: str) -> tuple[Path, dict[str, Any], tempfile.TemporaryDirectory[str]]:
    tmp = tempfile.TemporaryDirectory(prefix=f"fraktall-{job_id[:8]}-")
    root = Path(tmp.name)
    outtmpl = str(root / "source.%(ext)s")
    opts: dict[str, Any] = {
        "format": "bestaudio/best",
        "outtmpl": outtmpl,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "retries": 3,
        "socket_timeout": 30,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(source_url, download=True)
        filename = Path(ydl.prepare_filename(info))

    if not filename.exists():
        candidates = [p for p in root.iterdir() if p.is_file()]
        if not candidates:
            tmp.cleanup()
            raise RuntimeError("yt-dlp finished but no audio file was found")
        filename = max(candidates, key=lambda p: p.stat().st_size)
    return filename, info, tmp


def _pick_caption_track(info: dict[str, Any], language: str) -> dict[str, Any] | None:
    """Prefer a human-written track over YouTube's own auto-generated one,
    and prefer the json3 format (structured cues) when the track offers it."""
    prefix = language.split("-")[0].lower()
    for source in (info.get("subtitles") or {}, info.get("automatic_captions") or {}):
        matches = [
            formats
            for code, formats in source.items()
            if formats and code.split("-")[0].lower() == prefix
        ]
        if not matches:
            continue
        formats = matches[0]
        for fmt in formats:
            if fmt.get("ext") == "json3":
                return fmt
        return formats[0]
    return None


def _parse_json3_captions(data: dict[str, Any]) -> list[Segment]:
    segments: list[Segment] = []
    for event in data.get("events") or []:
        segs = event.get("segs")
        if not segs:
            continue
        text = "".join(str(s.get("utf8") or "") for s in segs).replace("\n", " ").strip()
        if not text:
            continue
        start = float(event.get("tStartMs") or 0) / 1000.0
        duration_ms = event.get("dDurationMs")
        end = start + (float(duration_ms) / 1000.0 if duration_ms else 2.0)
        segments.append(Segment(start=start, end=end, text=text))
    return segments


def fetch_captions(source_url: str, language: str) -> tuple[list[Segment], dict[str, Any]] | None:
    """Try to reuse YouTube's own subtitles/auto-captions instead of
    downloading audio and running local Whisper. Much faster and free
    when available; callers must fall back to Whisper when this returns
    None (captions disabled, wrong language, or the fetch failed)."""
    opts: dict[str, Any] = {
        "skip_download": True,
        "quiet": True,
        "no_warnings": True,
        "retries": 3,
        "socket_timeout": 30,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(source_url, download=False)

    track = _pick_caption_track(info, language)
    if track is None or not track.get("url"):
        return None

    res = SESSION.get(track["url"], timeout=30)
    if not res.ok:
        return None

    segments = _parse_json3_captions(res.json())
    if not segments:
        return None
    return segments, info


def transcribe(audio_path: Path) -> dict[str, Any]:
    mime = "application/octet-stream"
    with audio_path.open("rb") as handle:
        res = SESSION.post(
            f"{WHISPER_BASE_URL}/audio/transcriptions",
            files={"file": (audio_path.name, handle, mime)},
            data={
                "model": WHISPER_MODEL,
                "response_format": "verbose_json",
                "language": WHISPER_LANGUAGE,
            },
            timeout=60 * 60,
        )
    if not res.ok:
        raise RuntimeError(f"Whisper failed: HTTP {res.status_code} {res.text[:500]}")
    body = res.json()
    if body.get("error"):
        raise RuntimeError(f"Whisper failed: {body['error']}")
    return body


def to_segments(transcript: dict[str, Any]) -> list[Segment]:
    raw = transcript.get("segments") or []
    result: list[Segment] = []
    for item in raw:
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        result.append(
            Segment(
                start=float(item.get("start") or 0.0),
                end=float(item.get("end") or 0.0),
                text=text,
            )
        )
    return result


def chunk_segments(segments: list[Segment], max_chars: int = 10_000, max_seconds: float = 12 * 60) -> list[list[Segment]]:
    chunks: list[list[Segment]] = []
    current: list[Segment] = []
    chars = 0
    start = 0.0

    for seg in segments:
        if not current:
            start = seg.start
        projected = chars + len(seg.text) + 32
        duration = seg.end - start
        if current and (projected > max_chars or duration > max_seconds):
            chunks.append(current)
            current = []
            chars = 0
            start = seg.start
        current.append(seg)
        chars += len(seg.text) + 32
    if current:
        chunks.append(current)
    return chunks


def curation_guidance(mode: str) -> str:
    return {
        "viral": "Priorize hook, emoção, surpresa, controvérsia, humor, utilidade prática e compartilhamento.",
        "podcast": "Priorize histórias fechadas, opiniões fortes, discordâncias, experiências pessoais, explicações úteis e frases memoráveis. Evite conversa genérica.",
        "insight": "Priorize ideias que ensinam, explicam mecanismos, desafiam suposições ou entregam modelos mentais e aprendizados acionáveis.",
        "news": "Priorize informação nova: anúncio, decisão, número, data, mudança, compromisso, consequência, correção ou declaração noticiável.",
        "institutional": "Priorize interesse público, decisão, política, prazo, serviço, investimento, dado concreto e fala institucional. Integridade de contexto é crítica.",
    }.get(mode, "Priorize momentos completos, relevantes e autoexplicativos.")


def transcript_block(chunk: list[Segment]) -> str:
    return "\n".join(f"[{s.start:.1f}s - {s.end:.1f}s] {s.text}" for s in chunk)


CANDIDATE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["clips"],
    "properties": {
        "clips": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "start",
                    "end",
                    "title",
                    "virality_score",
                    "editorial_score",
                    "context_integrity_score",
                    "reason",
                ],
                "properties": {
                    "start": {"type": "number"},
                    "end": {"type": "number"},
                    "title": {"type": "string"},
                    "virality_score": {"type": "integer"},
                    "editorial_score": {"type": "integer"},
                    "context_integrity_score": {"type": "integer"},
                    "reason": {"type": "string"},
                },
            },
        }
    },
}


def analyze_chunk(chunk: list[Segment], mode: str, candidate_count: int) -> list[dict[str, Any]]:
    system = (
        "Você é o motor editorial do Fraktall. Selecione cortes verticais a partir de uma transcrição. "
        "Cada corte precisa ser entendível por um espectador frio, começar e terminar em um pensamento natural e preservar o contexto. "
        "Não escolha falas de ligação, perguntas soltas sem resposta, trechos curtos demais ou frases que dependem do que veio antes. "
        "Retorne apenas JSON válido. Escreva title e reason em português."
    )
    prompt = (
        f"Modo de curadoria: {mode}. {curation_guidance(mode)}\n\n"
        f"Escolha no máximo {candidate_count} candidatos fortes neste bloco. "
        "Idealmente cada corte deve ter entre 20 e 90 segundos, mas complete o pensamento antes de obedecer duração. "
        "Dê virality_score, editorial_score e context_integrity_score de 0 a 99. "
        "Use somente timestamps existentes na transcrição.\n\n"
        f"TRANSCRIÇÃO:\n{transcript_block(chunk)}"
    )
    body = {
        "model": LMSTUDIO_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
            {"role": "user", "content": "/no_think"},
        ],
        "temperature": 0.1,
        "max_tokens": 950,
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "fraktall_candidates", "strict": True, "schema": CANDIDATE_SCHEMA},
        },
    }
    res = SESSION.post(f"{LMSTUDIO_BASE_URL}/chat/completions", json=body, timeout=10 * 60)
    if not res.ok:
        raise RuntimeError(f"LM Studio failed: HTTP {res.status_code} {res.text[:500]}")
    data = res.json()
    content = (((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
    if content.startswith("```"):
        content = content.strip("`")
        if content.lower().startswith("json"):
            content = content[4:].lstrip()
    parsed = json.loads(content)
    return list(parsed.get("clips") or [])


def clamp_score(value: Any, fallback: int = 0) -> int:
    try:
        return max(0, min(99, int(round(float(value)))))
    except Exception:
        return fallback


def rank_score(mode: str, viral: int, editorial: int, context: int) -> int:
    weights = {
        "viral": (0.65, 0.20, 0.15),
        "podcast": (0.40, 0.40, 0.20),
        "insight": (0.25, 0.55, 0.20),
        "news": (0.20, 0.60, 0.20),
        "institutional": (0.10, 0.65, 0.25),
    }
    v, e, c = weights.get(mode, weights["podcast"])
    penalty = (60 - context) * 0.65 if context < 60 else 0
    return max(0, min(99, round(viral * v + editorial * e + context * c - penalty)))


def normalize_candidate(raw: dict[str, Any], mode: str, duration: float) -> dict[str, Any] | None:
    try:
        start = max(0.0, min(float(raw.get("start")), max(0.0, duration - 0.5)))
        end = max(start + 0.5, min(float(raw.get("end")), duration))
    except Exception:
        return None
    if end - start < 8:
        return None

    viral = clamp_score(raw.get("virality_score"), 50)
    editorial = clamp_score(raw.get("editorial_score"), viral)
    context = clamp_score(raw.get("context_integrity_score"), 70)
    return {
        "start": round(start, 2),
        "end": round(end, 2),
        "title": str(raw.get("title") or "Corte sugerido").strip()[:120],
        "reason": str(raw.get("reason") or "").strip()[:500],
        "virality_score": viral,
        "editorial_score": editorial,
        "context_integrity_score": context,
        "selection_score": rank_score(mode, viral, editorial, context),
    }


def overlap_fraction(a: dict[str, Any], b: dict[str, Any]) -> float:
    overlap = min(a["end"], b["end"]) - max(a["start"], b["start"])
    if overlap <= 0:
        return 0.0
    return overlap / min(a["end"] - a["start"], b["end"] - b["start"])


def select_best(candidates: list[dict[str, Any]], clip_count: int) -> list[dict[str, Any]]:
    ordered = sorted(candidates, key=lambda c: (c["selection_score"], c["context_integrity_score"]), reverse=True)
    kept: list[dict[str, Any]] = []
    for candidate in ordered:
        if candidate["context_integrity_score"] < 55:
            continue
        if any(overlap_fraction(candidate, existing) > 0.4 for existing in kept):
            continue
        kept.append(candidate)
        if len(kept) >= clip_count:
            break
    return kept


def process_job(job: dict[str, Any]) -> None:
    job_id = str(job["id"])
    source_url = str(job["source_url"])
    mode = str(job.get("curation_mode") or "podcast")
    clip_count = max(1, min(40, int(job.get("clip_count") or 8)))
    temp: tempfile.TemporaryDirectory[str] | None = None

    try:
        heartbeat("running", job_id)
        update_job(job_id, status="running", stage="Validando serviços locais", progress=4, started_at=_now_iso(), error=None)
        check_lmstudio()

        update_job(job_id, stage="Procurando legendas do YouTube", progress=8)
        segments: list[Segment] = []
        info: dict[str, Any] = {}
        try:
            captions_result = fetch_captions(source_url, WHISPER_LANGUAGE)
        except Exception as exc:
            captions_result = None
            print(f"[fraktall-worker] caption fetch failed, falling back to Whisper: {exc}")

        if captions_result:
            segments, info = captions_result
            update_job(job_id, stage="Legendas do YouTube encontradas", progress=35)
        else:
            check_whisper()
            update_job(job_id, stage="Baixando áudio", progress=8)
            audio_path, info, temp = download_audio(source_url, job_id)

            update_job(job_id, stage="Transcrevendo com Whisper local", progress=20)
            transcript = transcribe(audio_path)
            segments = to_segments(transcript)
            if not segments:
                raise RuntimeError("Whisper returned no transcript segments")

        duration = float(info.get("duration") or 0.0)
        title = str(info.get("title") or source_url)
        if duration <= 0:
            duration = segments[-1].end

        chunks = chunk_segments(segments)
        candidate_per_chunk = max(2, min(5, math.ceil(clip_count / max(1, len(chunks))) + 1))
        all_candidates: list[dict[str, Any]] = []

        for index, chunk in enumerate(chunks):
            pct = 40 + round((index / max(1, len(chunks))) * 48)
            update_job(
                job_id,
                stage=f"Analisando bloco {index + 1}/{len(chunks)} no LM Studio",
                progress=min(88, pct),
            )
            raw_candidates = analyze_chunk(chunk, mode, candidate_per_chunk)
            for raw in raw_candidates:
                normalized = normalize_candidate(raw, mode, duration)
                if normalized:
                    all_candidates.append(normalized)

        update_job(job_id, stage="Rankeando e removendo duplicados", progress=92)
        selected = select_best(all_candidates, clip_count)
        result = {
            "title": title,
            "source_url": source_url,
            "duration": round(duration, 2),
            "curation_mode": mode,
            "transcript_source": "youtube_captions" if captions_result else "whisper",
            "chunks_analyzed": len(chunks),
            "candidates_considered": len(all_candidates),
            "clips": selected,
        }
        update_job(
            job_id,
            status="done",
            stage="Seleção concluída",
            progress=100,
            result=result,
            finished_at=_now_iso(),
        )
        print(f"[fraktall-worker] done {job_id}: {len(selected)} clips from {len(all_candidates)} candidates")
    except Exception as exc:
        print(f"[fraktall-worker] job {job_id} failed: {exc}")
        try:
            update_job(
                job_id,
                status="error",
                stage="Erro",
                error=str(exc)[:2000],
                finished_at=_now_iso(),
            )
        except Exception as update_exc:
            print(f"[fraktall-worker] could not persist error: {update_exc}")
    finally:
        if temp is not None:
            temp.cleanup()
        try:
            heartbeat("idle", None)
        except Exception:
            pass


def main() -> None:
    _require_env()
    print(f"[fraktall-worker] id={WORKER_ID}")
    print(f"[fraktall-worker] LM Studio={LMSTUDIO_BASE_URL} model={LMSTUDIO_MODEL}")
    print(f"[fraktall-worker] Whisper={WHISPER_BASE_URL} model={WHISPER_MODEL}")

    last_heartbeat = 0.0
    while True:
        try:
            now = time.monotonic()
            if now - last_heartbeat >= 10:
                heartbeat("idle", None)
                last_heartbeat = now
            job = claim_next_job()
            if job:
                process_job(job)
                last_heartbeat = 0.0
            else:
                time.sleep(POLL_SECONDS)
        except KeyboardInterrupt:
            print("\n[fraktall-worker] stopped")
            try:
                heartbeat("offline", None)
            except Exception:
                pass
            return
        except Exception as exc:
            print(f"[fraktall-worker] loop error: {exc}")
            time.sleep(max(5.0, POLL_SECONDS))


if __name__ == "__main__":
    main()
