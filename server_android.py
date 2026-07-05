"""
Android-optimized API server for Style-Bert-VITS2 TTS
=====================================================
- Forces CPU mode (no CUDA dependency for Android/Termux)
- Removes GPUtil (not available on Android)
- Gracefully handles pyopenjtalk unavailability
- Adds /health and lightweight status endpoints for mobile apps
- Supports both raw WAV and base64 JSON responses
- Mobile-optimized defaults and error handling
"""

import argparse
import base64
import json
import os
import sys
import time
from io import BytesIO
from pathlib import Path
from typing import Any, Optional
from urllib.parse import unquote

import psutil
import torch
import uvicorn
from fastapi import FastAPI, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from scipy.io import wavfile

from config_android import get_android_config
from style_bert_vits2.constants import (
    DEFAULT_ASSIST_TEXT_WEIGHT,
    DEFAULT_LENGTH,
    DEFAULT_LINE_SPLIT,
    DEFAULT_NOISE,
    DEFAULT_NOISEW,
    DEFAULT_SDP_RATIO,
    DEFAULT_SPLIT_INTERVAL,
    DEFAULT_STYLE,
    DEFAULT_STYLE_WEIGHT,
    Languages,
)
from style_bert_vits2.logging import logger
from style_bert_vits2.nlp import bert_models, onnx_bert_models
from style_bert_vits2.tts_model import TTSModel, TTSModelHolder
from style_bert_vits2.utils import torch_device_to_onnx_providers


config = get_android_config()
ln = config.server_config.language

# --- Android-compatible init: gracefully handle optional deps ---
_japanese_available = False
try:
    from style_bert_vits2.nlp.japanese import pyopenjtalk_worker as pyopenjtalk
    from style_bert_vits2.nlp.japanese.user_dict import update_dict
    _japanese_available = True
except Exception as e:
    logger.warning(f"pyopenjtalk_worker not available on this platform: {e}")
    logger.warning("Japanese text processing will be limited.")

if _japanese_available:
    try:
        pyopenjtalk.initialize_worker()
        update_dict()
    except Exception as e:
        logger.warning(f"Failed to initialize pyopenjtalk worker: {e}")
        _japanese_available = False


# --- Android system info helpers (no GPUtil) ---
def get_memory_info() -> dict:
    """Get memory info without GPUtil."""
    mem = psutil.virtual_memory()
    return {
        "total": mem.total,
        "available": mem.available,
        "used": mem.used,
        "percent": mem.percent,
    }


def get_cpu_info() -> dict:
    """Get CPU info."""
    return {
        "percent": psutil.cpu_percent(interval=0.5),
        "count": psutil.cpu_count(),
        "freq": getattr(psutil.cpu_freq(), "current", None),
    }


# --- FastAPI app ---
def raise_validation_error(msg: str, param: str):
    logger.warning(f"Validation error: {msg}")
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=[{"type": "invalid_params", "msg": msg, "loc": ["query", param]}],
    )


class AudioResponse(Response):
    media_type = "audio/wav"


loaded_models: list[TTSModel] = []


def load_models(model_holder: TTSModelHolder):
    global loaded_models
    loaded_models = []
    for model_name, model_paths in model_holder.model_files_dict.items():
        model = TTSModel(
            model_path=model_paths[0],
            config_path=model_holder.root_dir / model_name / "config.json",
            style_vec_path=model_holder.root_dir / model_name / "style_vectors.npy",
            device=model_holder.device,
        )
        loaded_models.append(model)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Style-Bert-VITS2 TTS Server (Android Optimized)"
    )
    parser.add_argument(
        "--dir", "-d", type=str, help="Model directory", default=config.assets_root
    )
    parser.add_argument("--port", "-p", type=int, help="Server port", default=None)
    parser.add_argument("--host", type=str, help="Bind address", default="0.0.0.0")
    parser.add_argument("--preload_onnx_bert", action="store_true")
    parser.add_argument(
        "--no_japanese",
        action="store_true",
        help="Disable Japanese language support (avoids pyopenjtalk)",
    )
    args = parser.parse_args()

    # --- Always CPU on Android ---
    device = "cpu"
    logger.info(f"Android mode: forcing device={device}")

    # --- Load BERT models (CPU) ---
    logger.info("Loading BERT models (CPU)...")
    bert_models.load_model(Languages.JP, device_map=device)
    bert_models.load_tokenizer(Languages.JP)
    if args.preload_onnx_bert:
        onnx_bert_models.load_model(
            Languages.JP, onnx_providers=torch_device_to_onnx_providers(device)
        )
        onnx_bert_models.load_tokenizer(Languages.JP)

    # --- Discover models ---
    model_dir = Path(args.dir)
    model_holder = TTSModelHolder(
        model_dir, device, torch_device_to_onnx_providers(device)
    )
    if len(model_holder.model_names) == 0:
        logger.error(f"Models not found in {model_dir}.")
        sys.exit(1)

    logger.info(f"Found {len(model_holder.model_names)} model(s): {model_holder.model_names}")
    logger.info("Loading models... (this may take a while on Android)")
    load_models(model_holder)

    # --- Config ---
    limit = config.server_config.limit
    if limit < 1:
        limit = None

    port = args.port or config.server_config.port

    # --- FastAPI setup ---
    app = FastAPI(
        title="Style-Bert-VITS2 TTS (Android)",
        description="Text-to-Speech API optimized for Android/Termux",
        version="2.7.0-android",
    )

    allow_origins = config.server_config.origins
    if allow_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=config.server_config.origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    # ===================== API Endpoints =====================

    @app.get("/health")
    async def health():
        """Lightweight health check for Android app monitoring."""
        return {"status": "ok", "timestamp": time.time()}

    @app.api_route(
        "/voice",
        methods=["GET", "POST"],
        response_class=AudioResponse,
    )
    async def voice(
        request: Request,
        text: str = Query(
            ..., min_length=1, max_length=limit, description="Text to synthesize"
        ),
        encoding: str = Query(
            None, description="URL decode text (e.g. `utf-8`)"
        ),
        model_name: str = Query(
            None,
            description="Model name (takes priority over model_id). "
            "Directory name inside model_assets.",
        ),
        model_id: int = Query(
            0, description="Model ID (see GET /models/info)"
        ),
        speaker_name: str = Query(
            None,
            description="Speaker name (takes priority over speaker_id). "
            "Value from esd.list 2nd column.",
        ),
        speaker_id: int = Query(
            0,
            description="Speaker ID (see spk2id in config.json)",
        ),
        sdp_ratio: float = Query(
            DEFAULT_SDP_RATIO,
            description="SDP/DP mix ratio. Higher = more tone variation",
        ),
        noise: float = Query(
            DEFAULT_NOISE,
            description="Sample noise ratio. Higher = more randomness",
        ),
        noisew: float = Query(
            DEFAULT_NOISEW,
            description="SDP noise. Higher = more pronunciation interval variation",
        ),
        length: float = Query(
            DEFAULT_LENGTH,
            description="Speech speed. 1.0 = normal, larger = slower",
        ),
        language: Languages = Query(
            ln, description="Language of the text (JP/EN/ZH)"
        ),
        auto_split: bool = Query(
            DEFAULT_LINE_SPLIT,
            description="Split by newlines and generate separately",
        ),
        split_interval: float = Query(
            DEFAULT_SPLIT_INTERVAL,
            description="Silence interval (seconds) between splits",
        ),
        assist_text: Optional[str] = Query(
            None,
            description="Assist text to guide voice style/emotion",
        ),
        assist_text_weight: float = Query(
            DEFAULT_ASSIST_TEXT_WEIGHT,
            description="Strength of assist_text",
        ),
        style: Optional[str] = Query(
            DEFAULT_STYLE, description="Style name"
        ),
        style_weight: float = Query(
            DEFAULT_STYLE_WEIGHT, description="Style strength"
        ),
        reference_audio_path: Optional[str] = Query(
            None,
            description="Reference audio path for style transfer",
        ),
        response_format: str = Query(
            "wav",
            description='Response format: "wav" (raw audio) or "json" (base64 encoded)',
        ),
    ):
        """Synthesize speech from text with style control.

        Returns raw WAV audio by default, or JSON with base64-encoded audio
        when `response_format=json` is specified (useful for Android apps).
        """
        logger.info(
            f"{request.client.host}:{request.client.port}/voice  "
            f"{unquote(str(request.query_params))}"
        )

        if request.method == "GET":
            logger.warning(
                "GET method has restrictions; use POST for production."
            )

        # --- Validate model_id ---
        if model_id >= len(model_holder.model_names):
            raise_validation_error(
                f"model_id={model_id} not found", "model_id"
            )

        # --- Resolve model_name ---
        if model_name:
            model_ids = [
                i
                for i, x in enumerate(model_holder.models_info)
                if x.name == model_name
            ]
            if not model_ids:
                raise_validation_error(
                    f"model_name={model_name} not found", "model_name"
                )
            if len(model_ids) > 1:
                raise_validation_error(
                    f"model_name={model_name} is ambiguous", "model_name"
                )
            model_id = model_ids[0]

        model = loaded_models[model_id]

        # --- Resolve speaker ---
        if speaker_name is None:
            if speaker_id not in model.id2spk:
                raise_validation_error(
                    f"speaker_id={speaker_id} not found", "speaker_id"
                )
        else:
            if speaker_name not in model.spk2id:
                raise_validation_error(
                    f"speaker_name={speaker_name} not found", "speaker_name"
                )
            speaker_id = model.spk2id[speaker_name]

        # --- Validate style ---
        if style not in model.style2id:
            raise_validation_error(f"style={style} not found", "style")
        assert style is not None

        # --- URL decode ---
        if encoding is not None:
            text = unquote(text, encoding=encoding)

        # --- Synthesize ---
        try:
            sr, audio = model.infer(
                text=text,
                language=language,
                speaker_id=speaker_id,
                reference_audio_path=reference_audio_path,
                sdp_ratio=sdp_ratio,
                noise=noise,
                noise_w=noisew,
                length=length,
                line_split=auto_split,
                split_interval=split_interval,
                assist_text=assist_text,
                assist_text_weight=assist_text_weight,
                use_assist_text=bool(assist_text),
                style=style,
                style_weight=style_weight,
            )
        except Exception as e:
            logger.error(f"TTS inference failed: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"TTS synthesis failed: {str(e)}",
            )

        logger.success("Audio generated successfully")

        # --- Response ---
        if response_format == "json":
            with BytesIO() as wav_buf:
                wavfile.write(wav_buf, sr, audio)
                b64_audio = base64.b64encode(wav_buf.getvalue()).decode("utf-8")
            return JSONResponse(
                content={
                    "audio": b64_audio,
                    "sample_rate": sr,
                    "format": "wav",
                    "model": model_name or model_holder.model_names[model_id],
                    "speaker_id": speaker_id,
                }
            )
        else:
            with BytesIO() as wav_content:
                wavfile.write(wav_content, sr, audio)
                return Response(
                    content=wav_content.getvalue(), media_type="audio/wav"
                )

    @app.get("/models/info")
    def get_loaded_models_info():
        """Get info about all loaded models."""
        result: dict[str, dict[str, Any]] = {}
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
        """Reload models (call after adding/removing model files)."""
        model_holder.refresh()
        load_models(model_holder)
        return get_loaded_models_info()

    @app.get("/status")
    def get_status():
        """Get server and system status (Android-compatible)."""
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
                "platform": sys.platform,
                "python_version": sys.version,
            },
        }

    @app.get("/tools/get_audio", response_class=AudioResponse)
    def get_audio(
        request: Request, path: str = Query(..., description="Local WAV file path")
    ):
        """Retrieve a WAV file from the local filesystem."""
        logger.info(
            f"{request.client.host}:{request.client.port}/tools/get_audio  "
            f"{unquote(str(request.query_params))}"
        )
        if not os.path.isfile(path):
            raise_validation_error(f"path={path} not found", "path")
        if not path.lower().endswith(".wav"):
            raise_validation_error(f"not a WAV file: {path}", "path")
        return FileResponse(path=path, media_type="audio/wav")

    # ===================== Start Server =====================
    logger.info("=" * 50)
    logger.info(f"Style-Bert-VITS2 TTS Server (Android)")
    logger.info(f"Listening: http://{args.host}:{port}")
    logger.info(f"API docs: http://{args.host}:{port}/docs")
    logger.info(f"Health:   http://{args.host}:{port}/health")
    logger.info(f"Models:   {len(loaded_models)} loaded")
    logger.info(f"Device:   {device}")
    logger.info(f"Japanese: {'yes' if _japanese_available else 'no (use EN/ZH)'}")
    logger.info("=" * 50)

    uvicorn.run(app, port=port, host=args.host, log_level="warning")
