"""
Android-optimized global configuration
- CPU-only (no CUDA on typical Android)
- Simplified path handling for Termux
- Mobile-friendly defaults
"""

import shutil
from pathlib import Path
from typing import Any

import yaml

from style_bert_vits2.logging import logger


class ServerConfig:
    """Android-optimized server configuration."""

    def __init__(
        self,
        port: int = 5000,
        limit: int = 50,
        language: str = "JP",
        origins: list[str] | None = None,
    ):
        self.port = port
        self.limit = limit
        self.language = language
        self.origins = origins or ["*"]

    @classmethod
    def from_dict(cls, data: dict[str, Any]):
        return cls(**{k: v for k, v in data.items() if k in cls.__init__.__annotations__})


class AndroidConfig:
    """Top-level config for Android deployment."""

    def __init__(self, config_path: str):
        with open(config_path, encoding="utf-8") as f:
            cfg: dict[str, Any] = yaml.safe_load(f.read())

        self.model_name: str = cfg.get("model_name", "model_name")
        self.assets_root = Path(cfg.get("assets_root", "model_assets"))
        self.server_config = ServerConfig.from_dict(cfg.get("server", {}))


def get_android_config() -> AndroidConfig:
    """Load Android-optimized configuration.

    Uses config_android.yml if it exists, otherwise falls back to config.yml.
    """
    candidates = ["config_android.yml", "config.yml"]
    config_path = None
    for c in candidates:
        if Path(c).exists():
            config_path = c
            break

    if config_path is None:
        logger.error("No config file found (tried: %s)", ", ".join(candidates))
        # Create a default config_android.yml
        _write_default_config()
        config_path = "config_android.yml"

    logger.info(f"Loading config from: {config_path}")
    return AndroidConfig(config_path)


def _write_default_config():
    """Write a default Android config file."""
    default = """# Style-Bert-VITS2 Android Configuration
model_name: "model_name"
assets_root: "model_assets"

server:
  port: 5000
  limit: 50
  language: "JP"
  origins:
    - "*"
"""
    with open("config_android.yml", "w", encoding="utf-8") as f:
        f.write(default)
    logger.info("Created default config_android.yml")
