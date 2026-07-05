"""
Android entry point for Style-Bert-VITS2 TTS (Chaquopy).
Loaded by TTSService.java via Chaquopy Python bridge.

Exports:
    start_server(host: str, port: int) - Initialize models, start uvicorn in bg thread, return immediately
    stop_server() - Set stop event; uvicorn will exit on next iteration
    is_running() -> bool - Check if the server is currently active
"""

import os
import sys
import threading
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Path setup: ensure style_bert_vits2 package is importable
# ---------------------------------------------------------------------------
_HERE = Path(__file__).parent.resolve()

# Add the python/ dir and parent dirs to sys.path
for p in [_HERE, _HERE.parent, _HERE.parent.parent]:
    sp = str(p)
    if sp not in sys.path:
        sys.path.insert(0, sp)

# Suppress argparse usage since we get params from Java
if not hasattr(sys, 'argv') or sys.argv is None or len(sys.argv) == 0:
    sys.argv = ['server_main.py']

# ---------------------------------------------------------------------------
# Logger config
# ---------------------------------------------------------------------------
import logging
logging.getLogger("uvicorn").setLevel(logging.WARNING)
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
logging.getLogger("uvicorn.error").setLevel(logging.WARNING)

logger = logging.getLogger("stbvs22-android")
logger.setLevel(logging.INFO)
if not logger.handlers:
    ch = logging.StreamHandler()
    ch.setFormatter(logging.Formatter("[TTS] %(message)s"))
    logger.addHandler(ch)

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------
_stop_event = threading.Event()
_server_started = threading.Event()
_exception_box = []  # thread-safe list to capture init errors


def _background_server(host: str, port: int):
    """
    Run in a daemon thread.  Loads models, builds the FastAPI app,
    then calls uvicorn.run() which blocks until the server stops.
    """
    # Re-set sys.path for the background thread (Chaquopy may not inherit it)
    for p in [_HERE, _HERE.parent, _HERE.parent.parent]:
        sp = str(p)
        if sp not in sys.path:
            sys.path.insert(0, sp)

    try:
        _run_server(host, port)
    except Exception as exc:
        logger.exception("Fatal error in server thread")
        _exception_box.append(exc)
    finally:
        _server_started.clear()


def _run_server(host: str, port: int):
    """Heavy lifting: config, models, FastAPI app, uvicorn."""
    import uvicorn

    from style_bert_vits2.constants import Languages
    from style_bert_vits2.logging import logger as vb_logger
    from style_bert_vits2.nlp import onnx_bert_models
    from style_bert_vits2.tts_model import TTSModel, TTSModelHolder

    # Import config_android from the bundled source
    from config_android import get_android_config

    # ---------------------------------------------------------------
    # Japanese text processing support (graceful fallback)
    # ---------------------------------------------------------------
    _japanese_available = False
    try:
        from style_bert_vits2.nlp.japanese import pyopenjtalk_worker as pyopenjtalk
        from style_bert_vits2.nlp.japanese.user_dict import update_dict
        _japanese_available = True
    except Exception as e:
        vb_logger.warning(f"pyopenjtalk not available: {e}")

    if _japanese_available:
        try:
            pyopenjtalk.initialize_worker()
            update_dict()
        except Exception as e:
            vb_logger.warning(f"pyopenjtalk init failed: {e}")
            _japanese_available = False

    # ---------------------------------------------------------------
    # Configuration
    # ---------------------------------------------------------------
    config = get_android_config()
    device = "cpu"
    onnx_providers = ["CPUExecutionProvider"]
    vb_logger.info(f"Android APK mode: device={device}")

    # ---------------------------------------------------------------
    # BERT models (ONNX, CPU)
    # ---------------------------------------------------------------
    vb_logger.info("Loading ONNX BERT models (CPU)...")
    try:
        onnx_bert_models.load_model(
            Languages.JP,
            onnx_providers=onnx_providers,
        )
        onnx_bert_models.load_tokenizer(Languages.JP)
    except Exception as e:
        vb_logger.warning(f"ONNX BERT init failed (non-fatal): {e}")

    # ---------------------------------------------------------------
    # Discover models
    # ---------------------------------------------------------------
    model_dir = Path(config.assets_root)
    if not model_dir.is_absolute():
        model_dir = _HERE / config.assets_root

    model_holder = TTSModelHolder(
        model_dir, device, onnx_providers,
    )
    if len(model_holder.model_names) == 0:
        vb_logger.error(f"No models found in {model_dir}")
        alt_dir = Path("/storage/emulated/0") / "model_assets"
        if alt_dir.exists():
            vb_logger.info(f"Trying fallback: {alt_dir}")
            model_holder = TTSModelHolder(
                alt_dir, device, onnx_providers,
            )
        if len(model_holder.model_names) == 0:
            vb_logger.error("No models found anywhere.")
            return

    vb_logger.info(f"Found models: {model_holder.model_names}")
    vb_logger.info("Loading models...")

    loaded_models = []
    for model_name, model_paths in model_holder.model_files_dict.items():
        model = TTSModel(
            model_path=model_paths[0],
            config_path=model_holder.root_dir / model_name / "config.json",
            style_vec_path=model_holder.root_dir / model_name / "style_vectors.npy",
            device=model_holder.device,
        )
        loaded_models.append(model)

    limit = config.server_config.limit
    if limit < 1:
        limit = None

    # ---------------------------------------------------------------
    # FastAPI app
    # ---------------------------------------------------------------
    import base64
    import json
    import time
    from io import BytesIO
    from typing import Optional
    from urllib.parse import unquote

    from fastapi import FastAPI, HTTPException, Query, Request
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import FileResponse, JSONResponse, Response
    from scipy.io import wavfile

    from style_bert_vits2.constants import (
        DEFAULT_ASSIST_TEXT_WEIGHT, DEFAULT_LENGTH, DEFAULT_LINE_SPLIT,
        DEFAULT_NOISE, DEFAULT_NOISEW, DEFAULT_SDP_RATIO,
        DEFAULT_SPLIT_INTERVAL, DEFAULT_STYLE, DEFAULT_STYLE_WEIGHT,
        Languages,
    )

    ln = config.server_config.language

    def _read_proc_meminfo() -> dict:
        """Read /proc/meminfo as a lightweight alternative to psutil."""
        info = {}
        try:
            with open("/proc/meminfo") as f:
                for line in f:
                    parts = line.split(":")
                    if len(parts) == 2:
                        key = parts[0].strip()
                        val_str = parts[1].strip().split()[0]
                        info[key] = int(val_str) * 1024  # kB to bytes
        except (OSError, ValueError):
            return {"total": 0, "available": 0, "used": 0, "percent": 0}
        total = info.get("MemTotal", 0)
        available = info.get("MemAvailable", info.get("MemFree", 0))
        used = total - available if total > 0 else 0
        percent = (used / total) * 100 if total > 0 else 0
        return {"total": total, "available": available, "used": used, "percent": round(percent, 1)}

    def get_memory_info() -> dict:
        return _read_proc_meminfo()

    def get_cpu_info() -> dict:
        count = os.cpu_count() or 1
        # Simple one-shot CPU usage from /proc/stat
        try:
            with open("/proc/stat") as f:
                line = f.readline()
            vals = list(map(int, line.strip().split()[1:]))
            total = sum(vals)
            idle = vals[3]
            percent = round((1 - idle / total) * 100, 1) if total > 0 else 0
        except (OSError, ValueError, IndexError):
            percent = 0
        return {"percent": percent, "count": count, "freq": None}

    app = FastAPI(
        title="Style-Bert-VITS2 TTS (Android)",
        description="TTS API for Android APK",
        version="2.7.0-android",
    )

    if config.server_config.origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=config.server_config.origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    # ---- Endpoints ----

    @app.get("/health")
    async def health():
        return {"status": "ok", "timestamp": time.time()}

    @app.get("/status")
    def get_status():
        return {
            "server": {
                "version": "2.7.0-android",
                "device": device,
                "models_loaded": len(loaded_models),
                "model_names": model_holder.model_names,
                "port": port,
                "japanese_support": _japanese_available,
            },
            "system": {
                "cpu": get_cpu_info(),
                "memory": get_memory_info(),
                "platform": "android",
                "python_version": sys.version,
            },
        }

    @app.get("/models/info")
    def get_loaded_models_info():
        result = {}
        for mid, model in enumerate(loaded_models):
            result[str(mid)] = {
                "config_path": str(model.config_path),
                "model_path": str(model.model_path),
                "device": model.device,
                "spk2id": model.spk2id,
                "id2spk": model.id2spk,
                "style2id": model.style2id,
            }
        return result

    @app.post("/models/refresh")
    def refresh():
        model_holder.refresh()
        loaded_models.clear()
        for model_name, model_paths in model_holder.model_files_dict.items():
            model = TTSModel(
                model_path=model_paths[0],
                config_path=model_holder.root_dir / model_name / "config.json",
                style_vec_path=model_holder.root_dir / model_name / "style_vectors.npy",
                device=model_holder.device,
            )
            loaded_models.append(model)
        return get_loaded_models_info()

    @app.api_route("/voice", methods=["GET", "POST"])
    async def voice(
        request: Request,
        text: str = Query(..., min_length=1, max_length=limit),
        encoding: str = Query(None),
        model_name: str = Query(None),
        model_id: int = Query(0),
        speaker_name: str = Query(None),
        speaker_id: int = Query(0),
        sdp_ratio: float = Query(DEFAULT_SDP_RATIO),
        noise: float = Query(DEFAULT_NOISE),
        noisew: float = Query(DEFAULT_NOISEW),
        length: float = Query(DEFAULT_LENGTH),
        language: Languages = Query(ln),
        auto_split: bool = Query(DEFAULT_LINE_SPLIT),
        split_interval: float = Query(DEFAULT_SPLIT_INTERVAL),
        assist_text: Optional[str] = Query(None),
        assist_text_weight: float = Query(DEFAULT_ASSIST_TEXT_WEIGHT),
        style: Optional[str] = Query(DEFAULT_STYLE),
        style_weight: float = Query(DEFAULT_STYLE_WEIGHT),
        reference_audio_path: Optional[str] = Query(None),
        response_format: str = Query("wav"),
    ):
        vb_logger.info(f"/voice  {text[:50]}... lang={language}")

        if model_id >= len(model_holder.model_names):
            raise HTTPException(422, f"model_id={model_id} not found")

        if model_name:
            ids = [i for i, x in enumerate(model_holder.models_info) if x.name == model_name]
            if not ids:
                raise HTTPException(422, f"model_name={model_name} not found")
            model_id = ids[0]

        model = loaded_models[model_id]

        if speaker_name is None:
            if speaker_id not in model.id2spk:
                raise HTTPException(422, f"speaker_id={speaker_id} not found")
        else:
            if speaker_name not in model.spk2id:
                raise HTTPException(422, f"speaker_name={speaker_name} not found")
            speaker_id = model.spk2id[speaker_name]

        if style not in model.style2id:
            raise HTTPException(422, f"style={style} not found")

        if encoding:
            text = unquote(text, encoding=encoding)

        try:
            sr, audio = model.infer(
                text=text, language=language, speaker_id=speaker_id,
                reference_audio_path=reference_audio_path,
                sdp_ratio=sdp_ratio, noise=noise, noise_w=noisew,
                length=length, line_split=auto_split,
                split_interval=split_interval,
                assist_text=assist_text, assist_text_weight=assist_text_weight,
                use_assist_text=bool(assist_text),
                style=style, style_weight=style_weight,
            )
        except Exception as e:
            vb_logger.error(f"TTS failed: {e}")
            raise HTTPException(500, f"TTS failed: {str(e)}")

        if response_format == "json":
            with BytesIO() as buf:
                wavfile.write(buf, sr, audio)
                b64 = base64.b64encode(buf.getvalue()).decode()
            return JSONResponse(content={
                "audio": b64, "sample_rate": sr, "format": "wav",
                "model": model_name or model_holder.model_names[model_id],
                "speaker_id": speaker_id,
            })
        else:
            with BytesIO() as buf:
                wavfile.write(buf, sr, audio)
                return Response(content=buf.getvalue(), media_type="audio/wav")

    @app.get("/tools/get_audio")
    def get_audio(request: Request, path: str = Query(...)):
        if not os.path.isfile(path):
            raise HTTPException(422, f"path={path} not found")
        return FileResponse(path=path, media_type="audio/wav")

    # ---------------------------------------------------------------
    # Log startup info
    # ---------------------------------------------------------------
    vb_logger.info("=" * 50)
    vb_logger.info("Style-Bert-VITS2 TTS Server (Android APK)")
    vb_logger.info(f"Listening: http://{host}:{port}")
    vb_logger.info(f"API docs:  http://{host}:{port}/docs")
    vb_logger.info(f"Health:    http://{host}:{port}/health")
    vb_logger.info(f"Models:    {len(loaded_models)} loaded")
    vb_logger.info(f"Device:    {device}")
    vb_logger.info(f"Japanese:  {'yes' if _japanese_available else 'no'}")
    vb_logger.info("=" * 50)

    # Mark as started BEFORE uvicorn (so Java can poll /health)
    _server_started.set()

    # ---------------------------------------------------------------
    # Run uvicorn (blocking) — this thread stops here until server exits
    # ---------------------------------------------------------------
    uvicorn.run(app, port=port, host=host, log_level="warning")


# ------------------------------------------------------------------
# Public API for Java bridge
# ------------------------------------------------------------------

def start_server(host: str = "0.0.0.0", port: int = 5000):
    """
    Called from TTSService.java.
    Returns immediately after spawning the server background thread.
    """
    global _server_thread, _stop_event, _exception_box
    _stop_event.clear()
    _server_started.clear()
    _exception_box.clear()

    _server_thread = threading.Thread(
        target=_background_server,
        args=(host, port),
        daemon=True,
        name="tts-server",
    )
    _server_thread.start()
    logger.info(f"Server thread started for {host}:{port}")

    # Wait a few seconds for startup, then return
    ready = _server_started.wait(timeout=120.0)
    if not ready:
        logger.warning("Server thread didn't signal ready within 120s")
    if _exception_box:
        logger.error(f"Server thread raised: {_exception_box[0]}")
        raise _exception_box[0]


def stop_server():
    """Called from Java to request graceful shutdown."""
    _stop_event.set()
    logger.info("Stop requested.")
    # uvicorn checks the stop event in current design — we rely on the
    # daemon thread being killed when the Python interpreter shuts down.
    # A future improvement could use uvicorn's lifespan shutdown hook.


def is_running() -> bool:
    """Returns True if the server has started and is (presumably) running."""
    return _server_started.is_set() and not _stop_event.is_set()