import importlib.util
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from faster_whisper import WhisperModel


def _register_cuda_dll_dirs() -> None:
    """Make pip-installed NVIDIA CUDA/cuDNN wheels (nvidia-cublas-cu12,
    nvidia-cudnn-cu12) discoverable on Windows without requiring a full
    CUDA Toolkit install or editing the system PATH."""
    if sys.platform != "win32":
        return
    try:
        spec = importlib.util.find_spec("nvidia")
        if spec is None or not spec.submodule_search_locations:
            return
        base = Path(next(iter(spec.submodule_search_locations)))
        for bin_dir in base.glob("*/bin"):
            try:
                os.add_dll_directory(str(bin_dir))
            except OSError:
                pass
    except Exception:
        pass


_register_cuda_dll_dirs()

app = FastAPI(title="Fraktall Local Whisper")

_model: WhisperModel | None = None
_runtime: dict[str, str] = {}


def _want_cuda() -> bool:
    requested = os.getenv("WHISPER_DEVICE", "auto").strip().lower()
    if requested == "cpu":
        return False
    if requested == "cuda":
        return True
    return shutil.which("nvidia-smi") is not None


def _load_model() -> WhisperModel:
    global _model, _runtime
    if _model is not None:
        return _model

    model_name = os.getenv("WHISPER_MODEL", "small").strip() or "small"

    if _want_cuda():
        try:
            candidate = WhisperModel(model_name, device="cuda", compute_type="int8_float16")
            # ctranslate2 loads CUDA libraries (e.g. cuBLAS) lazily on first
            # inference rather than at construction time, so a missing/broken
            # CUDA install only surfaces here. Run a throwaway transcription
            # now so that failure is caught and falls back to CPU, instead of
            # surfacing as a 500 on the first real job.
            silence = np.zeros(16000, dtype=np.float32)
            list(candidate.transcribe(silence)[0])
            _model = candidate
            _runtime = {
                "model": model_name,
                "device": "cuda",
                "compute_type": "int8_float16",
            }
            print(f"[fraktall-whisper] loaded {model_name} on CUDA", flush=True)
            return _model
        except Exception as exc:
            print(f"[fraktall-whisper] CUDA failed; using CPU instead: {exc}", flush=True)

    _model = WhisperModel(model_name, device="cpu", compute_type="int8")
    _runtime = {"model": model_name, "device": "cpu", "compute_type": "int8"}
    print(f"[fraktall-whisper] loaded {model_name} on CPU", flush=True)
    return _model


@app.get("/health")
def health() -> dict[str, Any]:
    return {"ok": True, "loaded": _model is not None, **_runtime}


@app.get("/v1/models")
def models() -> dict[str, Any]:
    model_name = os.getenv("WHISPER_MODEL", "small").strip() or "small"
    return {
        "object": "list",
        "data": [{"id": model_name, "object": "model", "owned_by": "local"}],
    }


@app.post("/v1/audio/transcriptions")
async def transcriptions(request: Request) -> JSONResponse:
    form = await request.form()
    upload = form.get("file")
    if upload is None or not hasattr(upload, "read"):
        return JSONResponse({"error": {"message": "Missing audio file"}}, status_code=400)

    language_raw = str(form.get("language") or "").strip()
    language = None if not language_raw or language_raw == "auto" else language_raw
    prompt = str(form.get("prompt") or "").strip() or None

    suffix = Path(getattr(upload, "filename", "audio.mp3") or "audio.mp3").suffix or ".mp3"
    fd, tmp_name = tempfile.mkstemp(prefix="fraktall-", suffix=suffix)
    os.close(fd)

    try:
        payload = await upload.read()
        Path(tmp_name).write_bytes(payload)

        model = _load_model()
        segments_iter, info = model.transcribe(
            tmp_name,
            language=language,
            initial_prompt=prompt,
            word_timestamps=True,
            vad_filter=True,
            beam_size=5,
        )

        segments: list[dict[str, Any]] = []
        words: list[dict[str, Any]] = []
        full_text: list[str] = []

        for idx, seg in enumerate(segments_iter):
            text = (seg.text or "").strip()
            if text:
                full_text.append(text)

            segment_words: list[dict[str, Any]] = []
            for word in seg.words or []:
                item = {
                    "word": word.word,
                    "start": float(word.start),
                    "end": float(word.end),
                }
                segment_words.append(item)
                words.append(item)

            segments.append(
                {
                    "id": idx,
                    "text": text,
                    "start": float(seg.start),
                    "end": float(seg.end),
                    "no_speech_prob": float(getattr(seg, "no_speech_prob", 0.0) or 0.0),
                    "avg_logprob": float(getattr(seg, "avg_logprob", 0.0) or 0.0),
                    "compression_ratio": float(getattr(seg, "compression_ratio", 0.0) or 0.0),
                    "words": segment_words,
                }
            )

        duration = float(getattr(info, "duration", 0.0) or 0.0)
        detected_language = str(getattr(info, "language", language or "pt") or (language or "pt"))

        return JSONResponse(
            {
                "task": "transcribe",
                "language": detected_language,
                "duration": duration,
                "text": " ".join(full_text),
                "words": words,
                "segments": segments,
            }
        )
    except Exception as exc:
        return JSONResponse({"error": {"message": str(exc)}}, status_code=500)
    finally:
        try:
            Path(tmp_name).unlink(missing_ok=True)
        except Exception:
            pass
