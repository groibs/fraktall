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
from urllib.parse import parse_qs, urlparse

import requests
import yt_dlp


SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
WORKER_ID = os.environ.get("FRAKTALL_WORKER_ID", socket.gethostname()).strip() or socket.gethostname()

LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "lmstudio").strip().lower()
LMSTUDIO_BASE_URL = os.environ.get("LMSTUDIO_BASE_URL", "http://127.0.0.1:1234/v1").rstrip("/")
LMSTUDIO_MODEL = os.environ.get("LMSTUDIO_MODEL", "qwen/qwen3-1.7b").strip()
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "").strip()
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini").strip()

WHISPER_BASE_URL = os.environ.get("WHISPER_BASE_URL", "http://127.0.0.1:8178/v1").rstrip("/")
WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "small").strip()
WHISPER_LANGUAGE = os.environ.get("WHISPER_LANGUAGE", "pt").strip()
POLL_SECONDS = max(1.0, float(os.environ.get("POLL_SECONDS", "3")))

# Below this, a video is short enough that splitting it into multiple
# "long-form" segments would be artificial busywork; treat it as one block.
LONGFORM_MIN_VIDEO_SECONDS = 12 * 60

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
    """A transient network hiccup here (Wi-Fi blip, a long-running job's
    connection dropping) must not throw away hours of processing on an
    otherwise-successful job. Retry connection-level failures; a genuine
    HTTP error status (bad request, auth, etc.) is not retried."""
    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            res = SESSION.request(
                method,
                f"{SUPABASE_URL}/rest/v1/{path}",
                headers=_supa_headers(prefer),
                json=json_body,
                timeout=30,
            )
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
            last_exc = exc
            print(f"[fraktall-worker] Supabase {method} {path} connection failed (attempt {attempt + 1}/3): {exc}")
            time.sleep(2.0 * (attempt + 1))
            continue
        if not res.ok:
            raise RuntimeError(f"Supabase {method} {path} failed: HTTP {res.status_code} {res.text[:500]}")
        return res
    assert last_exc is not None
    raise last_exc


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
            "llm_provider": LLM_PROVIDER,
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


def resolve_llm_model() -> str:
    """Returns the model id to send in LLM requests. For LM Studio, tolerates
    LMSTUDIO_MODEL not matching a loaded model's id verbatim (LM Studio's
    reported ids can differ slightly from a user's config) by falling back to
    a substring match."""
    if LLM_PROVIDER == "openai":
        if not OPENAI_API_KEY:
            raise RuntimeError("OPENAI_API_KEY is required when LLM_PROVIDER=openai")
        return OPENAI_MODEL

    lm = SESSION.get(f"{LMSTUDIO_BASE_URL}/models", timeout=10)
    if not lm.ok:
        raise RuntimeError(f"LM Studio is unavailable: HTTP {lm.status_code}")
    ids = [m.get("id") for m in lm.json().get("data", []) if m.get("id")]
    if LMSTUDIO_MODEL in ids:
        return LMSTUDIO_MODEL

    wanted = LMSTUDIO_MODEL.lower()
    for candidate in ids:
        if wanted in candidate.lower() or candidate.lower() in wanted:
            print(f"[fraktall-worker] LMSTUDIO_MODEL={LMSTUDIO_MODEL!r} not loaded verbatim; using {candidate!r}")
            return candidate
    raise RuntimeError(
        f"LM Studio model {LMSTUDIO_MODEL!r} is not available. Loaded models: {sorted(x for x in ids if x)}"
    )


def check_whisper() -> None:
    whisper = SESSION.get(WHISPER_BASE_URL.rsplit("/v1", 1)[0] + "/health", timeout=10)
    if not whisper.ok:
        raise RuntimeError(f"Local Whisper is unavailable: HTTP {whisper.status_code}")


def _extract_json_content(data: dict[str, Any]) -> dict[str, Any]:
    content = (((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
    if content.startswith("```"):
        content = content.strip("`")
        if content.lower().startswith("json"):
            content = content[4:].lstrip()
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        # Small local models occasionally wrap the JSON in stray prose even
        # under a strict schema. Retry against just the outermost {...} span
        # before giving up.
        start = content.find("{")
        end = content.rfind("}")
        if start != -1 and end > start:
            return json.loads(content[start : end + 1])
        raise


def _call_lmstudio(system: str, prompt: str, schema: dict[str, Any], schema_name: str, max_tokens: int, model_id: str) -> dict[str, Any]:
    body = {
        "model": model_id,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
            {"role": "user", "content": "/no_think"},
        ],
        "temperature": 0.1,
        "max_tokens": max_tokens,
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": schema_name, "strict": True, "schema": schema},
        },
    }
    res = SESSION.post(f"{LMSTUDIO_BASE_URL}/chat/completions", json=body, timeout=10 * 60)
    if not res.ok:
        raise RuntimeError(f"LM Studio failed: HTTP {res.status_code} {res.text[:500]}")
    return _extract_json_content(res.json())


def _call_openai(system: str, prompt: str, schema: dict[str, Any], schema_name: str, max_tokens: int) -> dict[str, Any]:
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is required when LLM_PROVIDER=openai")
    body = {
        "model": OPENAI_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.1,
        "max_tokens": max_tokens,
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": schema_name, "strict": True, "schema": schema},
        },
    }
    res = SESSION.post(
        f"{OPENAI_BASE_URL}/chat/completions",
        json=body,
        headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
        timeout=5 * 60,
    )
    if not res.ok:
        raise RuntimeError(f"OpenAI failed: HTTP {res.status_code} {res.text[:500]}")
    return _extract_json_content(res.json())


def call_llm(system: str, prompt: str, schema: dict[str, Any], schema_name: str, max_tokens: int, model_id: str) -> dict[str, Any]:
    """A local model occasionally returns malformed JSON even under a strict
    schema (truncation, a stray token). One retry recovers most of these
    without giving up on a whole chunk's worth of analysis over a glitch."""
    attempts = 2
    last_exc: Exception | None = None
    for attempt in range(attempts):
        try:
            if LLM_PROVIDER == "openai":
                return _call_openai(system, prompt, schema, schema_name, max_tokens)
            return _call_lmstudio(system, prompt, schema, schema_name, max_tokens, model_id)
        except (json.JSONDecodeError, RuntimeError, requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
            last_exc = exc
            print(f"[fraktall-worker] LLM call failed (attempt {attempt + 1}/{attempts}): {exc}")
    assert last_exc is not None
    raise last_exc


# ---------------------------------------------------------------------------
# Transcript acquisition: prefer YouTube's own captions (free, instant) over
# downloading audio and running local Whisper (slow, needs a GPU/CPU budget).
# ---------------------------------------------------------------------------


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


def _pick_caption_track(source: dict[str, Any], language: str) -> dict[str, Any] | None:
    prefix = language.split("-")[0].lower()
    matches = [formats for code, formats in source.items() if formats and code.split("-")[0].lower() == prefix]
    if not matches:
        return None
    formats = matches[0]
    for fmt in formats:
        if fmt.get("ext") == "json3":
            return fmt
    return formats[0]


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


def fetch_youtube_captions(source_url: str, language: str) -> tuple[list[Segment], dict[str, Any], str] | None:
    """Reuses YouTube's own subtitle tracks without downloading audio/video.
    Tries a human-written (manual) track before the auto-generated one."""
    opts: dict[str, Any] = {
        "skip_download": True,
        "quiet": True,
        "no_warnings": True,
        "retries": 3,
        "socket_timeout": 30,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(source_url, download=False)

    for bucket_key, source_key in (("subtitles", "youtube_manual"), ("automatic_captions", "youtube_auto")):
        track = _pick_caption_track(info.get(bucket_key) or {}, language)
        if track is None or not track.get("url"):
            continue
        res = SESSION.get(track["url"], timeout=30)
        if not res.ok:
            continue
        segments = _parse_json3_captions(res.json())
        if segments:
            return segments, info, source_key
    return None


def _extract_youtube_id(source_url: str) -> str | None:
    parsed = urlparse(source_url)
    host = parsed.hostname or ""
    if host in ("youtu.be", "www.youtu.be"):
        video_id = parsed.path.lstrip("/")
        return video_id or None
    if "youtube.com" in host:
        if parsed.path == "/watch":
            values = parse_qs(parsed.query).get("v")
            return values[0] if values else None
        parts = [p for p in parsed.path.split("/") if p]
        if len(parts) >= 2 and parts[0] in ("shorts", "live", "embed"):
            return parts[1]
    return None


def _fetch_video_metadata(source_url: str) -> dict[str, Any]:
    opts: dict[str, Any] = {"skip_download": True, "quiet": True, "no_warnings": True, "retries": 2, "socket_timeout": 20}
    with yt_dlp.YoutubeDL(opts) as ydl:
        return ydl.extract_info(source_url, download=False) or {}


def fetch_via_youtube_transcript_api(source_url: str, language: str) -> tuple[list[Segment], dict[str, Any], str] | None:
    """Independent second implementation of caption fetching (different
    library/maintainer than yt-dlp), used as redundancy when yt-dlp's own
    caption extraction fails or YouTube changes something it doesn't handle
    yet. Never raises; a bad or missing dependency just skips this tier."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError:
        return None

    video_id = _extract_youtube_id(source_url)
    if not video_id:
        return None

    prefix = language.split("-")[0].lower()
    langs = [prefix] if language == prefix else [prefix, language]

    raw: Any = None
    try:
        raw = YouTubeTranscriptApi().fetch(video_id, languages=langs)
    except AttributeError:
        try:
            raw = YouTubeTranscriptApi.get_transcript(video_id, languages=langs)
        except Exception:
            return None
    except Exception:
        return None

    segments: list[Segment] = []
    for item in raw or []:
        if isinstance(item, dict):
            text, start, dur = item.get("text"), item.get("start"), item.get("duration")
        else:
            text = getattr(item, "text", None)
            start = getattr(item, "start", None)
            dur = getattr(item, "duration", None)
        text = str(text or "").strip()
        if not text or start is None:
            continue
        segments.append(Segment(start=float(start), end=float(start) + float(dur or 2.0), text=text))

    if not segments:
        return None

    try:
        info = _fetch_video_metadata(source_url)
    except Exception:
        info = {}
    return segments, info, "youtube_transcript_api"


def fetch_transcript(
    source_url: str, language: str, job_id: str, report: Any
) -> tuple[list[Segment], dict[str, Any], str, tempfile.TemporaryDirectory[str] | None]:
    """Cascade: YouTube captions (manual/auto, via yt-dlp) -> youtube-transcript-api
    -> Whisper local. Only downloads audio when every faster option fails."""
    report("Procurando legendas do YouTube", 6)
    try:
        result = fetch_youtube_captions(source_url, language)
    except Exception as exc:
        result = None
        print(f"[fraktall-worker] yt-dlp caption fetch failed: {exc}")
    if result:
        segments, info, source_key = result
        report(f"Legenda encontrada ({source_key})", 30)
        return segments, info, source_key, None

    report("Tentando transcript alternativo", 10)
    try:
        result = fetch_via_youtube_transcript_api(source_url, language)
    except Exception as exc:
        result = None
        print(f"[fraktall-worker] youtube-transcript-api failed: {exc}")
    if result:
        segments, info, source_key = result
        report("Transcript recuperado por fallback", 30)
        return segments, info, source_key, None

    report("Nenhuma legenda disponível — baixando áudio", 12)
    check_whisper()
    audio_path, info, temp = download_audio(source_url, job_id)
    report("Transcrevendo com Whisper local", 20)
    transcript = transcribe(audio_path)
    segments = to_segments(transcript)
    if not segments:
        raise RuntimeError("Whisper returned no transcript segments")
    return segments, info, "whisper_local", temp


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


# ---------------------------------------------------------------------------
# Pass 1: long-form segmentation (semantic topic map over the whole video).
# ---------------------------------------------------------------------------

LONGFORM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["segments"],
    "properties": {
        "segments": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["start", "end", "topic", "reason", "editorial_score", "context_integrity_score", "potential_score"],
                "properties": {
                    "start": {"type": "number"},
                    "end": {"type": "number"},
                    "topic": {"type": "string"},
                    "reason": {"type": "string"},
                    "editorial_score": {"type": "integer"},
                    "context_integrity_score": {"type": "integer"},
                    "potential_score": {"type": "integer"},
                },
            },
        }
    },
}


def analyze_longform_chunk(chunk: list[Segment], model_id: str) -> list[dict[str, Any]]:
    system = (
        "Você é o motor de decupagem do Fraktall. Analise uma janela de transcrição de um vídeo/podcast longo "
        "e proponha candidatos a blocos de assunto que poderiam virar um vídeo horizontal independente no YouTube. "
        "Um bom bloco tem início natural de assunto, desenvolvimento e conclusão, e faz sentido sozinho para quem não "
        "viu o resto do vídeo — mas essa janela é só um pedaço do vídeo, então um assunto pode ter começado antes ou "
        "continuar depois dela; proponha o melhor recorte possível dentro do que está visível aqui, mesmo que não seja "
        "perfeito. Sempre proponha pelo menos 1 candidato quando houver qualquer conteúdo substancial na janela — "
        "quem filtra qualidade é a pontuação depois, não você decidir omitir. Se um candidato for realmente fraco, "
        "dê notas baixas em vez de não retornar nada. Blocos podem durar de poucos minutos a mais de 30 minutos. "
        "Retorne apenas JSON válido. Escreva topic e reason em português."
    )
    prompt = (
        "Proponha até 4 candidatos a bloco nesta janela de transcrição, do melhor para o pior. "
        "Dê editorial_score (qualidade do conteúdo), context_integrity_score (o bloco se sustenta sozinho sem o resto do vídeo) "
        "e potential_score (potencial de audiência) de 0 a 99 — seja honesto, inclusive com notas baixas quando for o caso. "
        "Use somente timestamps existentes na transcrição.\n\n"
        f"TRANSCRIÇÃO:\n{transcript_block(chunk)}"
    )
    data = call_llm(system, prompt, LONGFORM_SCHEMA, "fraktall_longform", 900, model_id)
    return list(data.get("segments") or [])


def clamp_score(value: Any, fallback: int = 0) -> int:
    try:
        return max(0, min(99, int(round(float(value)))))
    except Exception:
        return fallback


def overlap_fraction(a: dict[str, Any], b: dict[str, Any]) -> float:
    overlap = min(a["end"], b["end"]) - max(a["start"], b["start"])
    if overlap <= 0:
        return 0.0
    return overlap / min(a["end"] - a["start"], b["end"] - b["start"])


def normalize_longform_candidate(raw: dict[str, Any], duration: float) -> dict[str, Any] | None:
    try:
        start = max(0.0, min(float(raw.get("start")), max(0.0, duration - 30)))
        end = max(start + 30, min(float(raw.get("end")), duration))
    except Exception:
        return None
    if end - start < 60:
        return None

    editorial = clamp_score(raw.get("editorial_score"), 50)
    context = clamp_score(raw.get("context_integrity_score"), 70)
    potential = clamp_score(raw.get("potential_score"), 50)
    return {
        "start": round(start, 2),
        "end": round(end, 2),
        "topic": str(raw.get("topic") or "Bloco sugerido").strip()[:160],
        "reason": str(raw.get("reason") or "").strip()[:500],
        "editorial_score": editorial,
        "context_integrity_score": context,
        "potential_score": potential,
        "selection_score": round(editorial * 0.45 + context * 0.25 + potential * 0.3),
    }


def merge_adjacent_longform(candidates: list[dict[str, Any]], gap_seconds: float = 15.0) -> list[dict[str, Any]]:
    """Chunk boundaries are arbitrary, so one real topic can be split across
    two adjacent candidates. Merge candidates that touch or nearly touch."""
    ordered = sorted(candidates, key=lambda c: c["start"])
    merged: list[dict[str, Any]] = []
    for cand in ordered:
        if merged and cand["start"] - merged[-1]["end"] <= gap_seconds:
            prev = merged[-1]
            if cand["selection_score"] > prev["selection_score"]:
                prev["topic"] = cand["topic"]
                prev["reason"] = cand["reason"]
            prev["end"] = max(prev["end"], cand["end"])
            prev["editorial_score"] = max(prev["editorial_score"], cand["editorial_score"])
            prev["context_integrity_score"] = min(prev["context_integrity_score"], cand["context_integrity_score"])
            prev["potential_score"] = max(prev["potential_score"], cand["potential_score"])
            prev["selection_score"] = round(
                prev["editorial_score"] * 0.45 + prev["context_integrity_score"] * 0.25 + prev["potential_score"] * 0.3
            )
        else:
            merged.append(dict(cand))
    return merged


def select_longform_segments(candidates: list[dict[str, Any]], max_segments: int = 12) -> list[dict[str, Any]]:
    ordered = sorted(candidates, key=lambda c: (c["selection_score"], c["context_integrity_score"]), reverse=True)
    kept: list[dict[str, Any]] = []
    for candidate in ordered:
        if candidate["context_integrity_score"] < 55:
            continue
        if any(overlap_fraction(candidate, existing) > 0.3 for existing in kept):
            continue
        kept.append(candidate)
        if len(kept) >= max_segments:
            break
    kept.sort(key=lambda c: c["start"])
    return kept


def _whole_video_block(title: str, duration: float, reason: str) -> dict[str, Any]:
    return {
        "start": 0.0,
        "end": round(duration, 2),
        "topic": title,
        "reason": reason,
        "editorial_score": 60,
        "context_integrity_score": 75,
        "potential_score": 60,
        "selection_score": 65,
    }


def longform_windows(
    segments: list[Segment], window_seconds: float = 35 * 60, overlap_seconds: float = 6 * 60, max_chars: int = 9_000
) -> list[list[Segment]]:
    """Sliding, overlapping windows (unlike chunk_segments' back-to-back
    chunks) so a topic near a window boundary is still fully visible in at
    least one window instead of being split with neither half complete."""
    if not segments:
        return []
    windows: list[list[Segment]] = []
    video_start = segments[0].start
    video_end = segments[-1].end
    step = max(60.0, window_seconds - overlap_seconds)

    window_start = video_start
    while window_start < video_end:
        window_end = window_start + window_seconds
        window = [s for s in segments if s.end > window_start and s.start < window_end]
        if window:
            trimmed: list[Segment] = []
            chars = 0
            for seg in window:
                trimmed.append(seg)
                chars += len(seg.text) + 32
                if chars > max_chars:
                    break
            windows.append(trimmed)
        window_start += step
    return windows


def build_long_form_segments(segments: list[Segment], duration: float, title: str, model_id: str, report: Any) -> list[dict[str, Any]]:
    if duration <= LONGFORM_MIN_VIDEO_SECONDS:
        return [_whole_video_block(title, duration, "Vídeo já é curto o suficiente para ser tratado como um único bloco.")]

    lf_chunks = longform_windows(segments)
    lf_candidates: list[dict[str, Any]] = []
    for index, chunk in enumerate(lf_chunks):
        report(
            f"Mapeando assuntos: bloco {index + 1}/{len(lf_chunks)}",
            40 + round((index / max(1, len(lf_chunks))) * 20),
        )
        try:
            raw = analyze_longform_chunk(chunk, model_id)
        except Exception as exc:
            print(f"[fraktall-worker] long-form chunk {index + 1}/{len(lf_chunks)} failed, skipping it: {exc}")
            continue
        for item in raw:
            normalized = normalize_longform_candidate(item, duration)
            if normalized:
                lf_candidates.append(normalized)

    report("Consolidando blocos longos", 62)
    lf_candidates = merge_adjacent_longform(lf_candidates)
    selected = select_longform_segments(lf_candidates)
    if not selected:
        print("[fraktall-worker] no long-form candidate survived filtering; falling back to whole-video block")
        return [
            _whole_video_block(
                title,
                duration,
                "Nenhum bloco longo com contexto suficiente foi identificado separadamente; tratando o vídeo inteiro como um bloco.",
            )
        ]
    return selected


# ---------------------------------------------------------------------------
# Pass 2: shorts derived from each selected long-form segment.
# ---------------------------------------------------------------------------

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


def analyze_chunk(chunk: list[Segment], mode: str, candidate_count: int, model_id: str, longform_topic: str | None = None) -> list[dict[str, Any]]:
    context_line = f"Este trecho faz parte de um vídeo mais longo sobre: {longform_topic}\n\n" if longform_topic else ""
    system = (
        "Você é o motor editorial do Fraktall. Selecione cortes verticais (Shorts/Reels) a partir de uma transcrição. "
        "Cada corte precisa ser entendível por um espectador frio, começar e terminar em um pensamento natural e preservar o contexto. "
        "Não escolha falas de ligação, perguntas soltas sem resposta, trechos curtos demais ou frases que dependem do que veio antes. "
        "Retorne apenas JSON válido. Escreva title e reason em português."
    )
    prompt = (
        f"{context_line}"
        f"Modo de curadoria: {mode}. {curation_guidance(mode)}\n\n"
        f"Escolha no máximo {candidate_count} candidatos fortes neste bloco. "
        "Idealmente cada corte deve ter entre 20 e 90 segundos, mas complete o pensamento antes de obedecer duração. "
        "Dê virality_score, editorial_score e context_integrity_score de 0 a 99. "
        "Use somente timestamps existentes na transcrição.\n\n"
        f"TRANSCRIÇÃO:\n{transcript_block(chunk)}"
    )
    data = call_llm(system, prompt, CANDIDATE_SCHEMA, "fraktall_candidates", 950, model_id)
    return list(data.get("clips") or [])


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


def normalize_candidate(raw: dict[str, Any], mode: str, max_end: float, min_start: float = 0.0) -> dict[str, Any] | None:
    try:
        start = max(min_start, min(float(raw.get("start")), max(min_start, max_end - 0.5)))
        end = max(start + 0.5, min(float(raw.get("end")), max_end))
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


def shorts_for_longform(
    segments: list[Segment], longform: dict[str, Any], mode: str, shorts_wanted: int, model_id: str
) -> list[dict[str, Any]]:
    scoped = [s for s in segments if s.end > longform["start"] and s.start < longform["end"]]
    if not scoped:
        return []

    chunks = chunk_segments(scoped)
    candidate_per_chunk = max(2, min(5, math.ceil(shorts_wanted / max(1, len(chunks))) + 1))
    candidates: list[dict[str, Any]] = []
    for chunk in chunks:
        try:
            raw_candidates = analyze_chunk(chunk, mode, candidate_per_chunk, model_id, longform_topic=longform.get("topic"))
        except Exception as exc:
            print(f"[fraktall-worker] shorts chunk for {longform.get('topic')!r} failed, skipping it: {exc}")
            continue
        for raw in raw_candidates:
            normalized = normalize_candidate(raw, mode, longform["end"], min_start=longform["start"])
            if normalized:
                candidates.append(normalized)
    return select_best(candidates, shorts_wanted)


def process_job(job: dict[str, Any]) -> None:
    job_id = str(job["id"])
    source_url = str(job["source_url"])
    mode = str(job.get("curation_mode") or "podcast")
    shorts_wanted = max(1, min(10, int(job.get("clip_count") or 3)))
    temp: tempfile.TemporaryDirectory[str] | None = None

    def report(stage: str, progress: int) -> None:
        update_job(job_id, stage=stage, progress=progress)

    try:
        heartbeat("running", job_id)
        update_job(job_id, status="running", stage="Validando serviços locais", progress=2, started_at=_now_iso(), error=None)
        model_id = resolve_llm_model()

        transcript_started = time.monotonic()
        segments, info, transcript_source, temp = fetch_transcript(source_url, WHISPER_LANGUAGE, job_id, report)
        transcript_fetch_seconds = round(time.monotonic() - transcript_started, 2)

        duration = float(info.get("duration") or 0.0)
        title = str(info.get("title") or source_url)
        if duration <= 0:
            duration = segments[-1].end

        long_form_segments = build_long_form_segments(segments, duration, title, model_id, report)

        report(f"Selecionados {len(long_form_segments)} vídeo(s) longo(s)", 65)
        for lf_index, lf in enumerate(long_form_segments):
            report(
                f"Buscando shorts do vídeo {lf_index + 1}/{len(long_form_segments)}",
                65 + round((lf_index / max(1, len(long_form_segments))) * 30),
            )
            lf["shorts"] = shorts_for_longform(segments, lf, mode, shorts_wanted, model_id)

        result = {
            "title": title,
            "source_url": source_url,
            "duration": round(duration, 2),
            "curation_mode": mode,
            "transcript": {
                "source": transcript_source,
                "language": WHISPER_LANGUAGE,
                "fetch_seconds": transcript_fetch_seconds,
            },
            "long_form": long_form_segments,
        }
        update_job(
            job_id,
            status="done",
            stage="Seleção concluída",
            progress=100,
            result=result,
            finished_at=_now_iso(),
        )
        total_shorts = sum(len(lf.get("shorts") or []) for lf in long_form_segments)
        print(f"[fraktall-worker] done {job_id}: {len(long_form_segments)} long-form segments, {total_shorts} shorts")
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
    print(f"[fraktall-worker] LLM provider={LLM_PROVIDER} LM Studio={LMSTUDIO_BASE_URL} model={LMSTUDIO_MODEL}")
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
