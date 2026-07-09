import os
import io
import wave
import threading
import logging
from typing import Optional

import numpy as np
import sherpa_onnx
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- 情绪映射表 (必须与 PC 端 export_onnx.py --styles 顺序严格一致) ---
STYLE_TO_SID = {
    "Neutral": 0,
    "Happy": 1,
    "Sad": 2,
    "Angry": 3,
}

def pcm_to_wav_bytes(pcm: np.ndarray, sample_rate: int) -> bytes:
    """将 float32 PCM 转换为标准 16-bit WAV 字节流"""
    pcm_int16 = np.clip(pcm * 32767.0, -32768, 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_int16.tobytes())
    return buf.getvalue()


class TTSEngine:
    """线程安全的 sherpa-onnx TTS 单例"""
    _instance = None
    _lock = threading.Lock()

    @classmethod
    def get(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def __init__(self):
        model_dir = os.environ.get("SBV2_MODEL_DIR")
        if not model_dir or not os.path.isdir(model_dir):
            raise RuntimeError(f"Invalid SBV2_MODEL_DIR: {model_dir}")

        required = ["model.onnx", "tokens.txt"]
        for f in required:
            if not os.path.exists(os.path.join(model_dir, f)):
                raise FileNotFoundError(f"Missing required file: {f} in {model_dir}")

        logger.info(f"Loading SBV2 model from: {model_dir}")
        self.tts = sherpa_onnx.OfflineTts(
            config=sherpa_onnx.OfflineTtsConfig(
                model=sherpa_onnx.OfflineTtsModelConfig(
                    vits=sherpa_onnx.OfflineTtsVitsModelConfig(
                        model=os.path.join(model_dir, "model.onnx"),
                        tokens=os.path.join(model_dir, "tokens.txt"),
                        lexicon=os.path.join(model_dir, "lexicon.txt"),
                        dict_dir=os.path.join(model_dir, "dict"),
                        noise_scale=0.667,
                        noise_scale_w=0.8,
                        length_scale=1.0,
                    ),
                    provider="cpu",
                    num_threads=4,
                ),
                max_num_sentences=1,
            )
        )
        self.sample_rate = self.tts.sample_rate
        logger.info(f"✅ TTS Engine ready. SR={self.sample_rate}, Styles={list(STYLE_TO_SID.keys())}")

    def synthesize(self, text: str, style: str = "Neutral", speed: float = 1.0) -> np.ndarray:
        sid = STYLE_TO_SID.get(style, 0)
        # VITS 非线程安全，必须在锁内调用 generate
        with self._lock:
            audio = self.tts.generate(text=text, sid=sid, speed=speed)
        return audio.samples


# --- FastAPI 应用 ---
app = FastAPI(title="SBV2 Mobile TTS API")

@app.post("/synthesize")
async def synthesize(
    text: str,
    style: Optional[str] = "Neutral",
    speed: Optional[float] = 1.0,
):
    try:
        engine = TTSEngine.get()
        audio_samples = engine.synthesize(text, style=style, speed=speed)
        wav_data = pcm_to_wav_bytes(audio_samples, engine.sample_rate)
        
        return StreamingResponse(
            io.BytesIO(wav_data),
            media_type="audio/wav",
            headers={"Content-Disposition": "inline; filename=tts_output.wav"}
        )
    except KeyError as e:
        raise HTTPException(status_code=400, detail=f"Unknown style: {e}")
    except Exception as e:
        logger.error(f"Synthesis error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/styles")
async def list_styles():
    return {"styles": list(STYLE_TO_SID.keys())}

@app.get("/health")
async def health_check():
    loaded = TTSEngine._instance is not None
    return {"status": "ok" if loaded else "loading", "engine_ready": loaded}

# ⚠️ 注意：uvicorn 的启动由 Kotlin 端触发或通过独立后台线程管理
# 若需在 Python 内部自启，请取消下方注释并确保在非主线程执行
# import uvicorn
# TTSEngine.get() 
# uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")