from __future__ import annotations

import logging
import os
import tomllib
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from pydantic import BaseModel

logger = logging.getLogger(__name__)

_DEFAULT_CONFIG_PATH = "~/.sagent/config.toml"


class AgentConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 7437
    log_level: str = "INFO"

    model_config = {"extra": "ignore"}


def setup_logging(config: AgentConfig) -> None:
    logging.basicConfig(
        level=getattr(logging, config.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def _apply_toml(config: AgentConfig, data: dict[str, Any]) -> None:
    for key, value in data.items():
        if hasattr(config, key):
            setattr(config, key, value)


def _apply_env(config: AgentConfig) -> None:
    for key in config.model_fields.keys():
        env_key = f"SAGENT_{key.upper()}"
        if env_key in os.environ:
            setattr(config, key, os.environ[env_key])


def get_config() -> AgentConfig:
    config = AgentConfig()

    load_dotenv(".env", override=False)

    config_path = Path(
        os.environ.get("SAGENT_CONFIG", _DEFAULT_CONFIG_PATH)
    ).expanduser()
    if config_path.exists():
        with open(config_path, "rb") as f:
            data = tomllib.load(f)
        _apply_toml(config, data)

    _apply_env(config)
    return config
