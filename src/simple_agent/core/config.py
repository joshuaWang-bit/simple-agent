from __future__ import annotations

import logging
import os
import tomllib
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

_DEFAULT_CONFIG_PATH = "~/.sagent/config.toml"


class AgentConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 7437
    log_level: str = "INFO"
    llm_tier: str = "fast"  # ultra | pro | fast
    llm_api_base: str = "https://api.siliconflow.cn/v1"
    llm_api_key: str | None = None
    llm_model_ultra: str = "THUDM/glm-5.1"
    llm_model_pro: str = ""
    llm_model_fast: str = "Qwen/Qwen3.6-35B-A3B"
    llm_enable_thinking: bool = False
    agent_max_steps: int = 20
    compaction_auto_threshold: float = 0.0
    compaction_tool_result_limit: int = 8_000
    compaction_tool_result_keep: int = 4_000
    trace_enabled: bool = False
    trace_file: str = "~/.sagent/traces/daemon.jsonl"
    trace_include_llm_payload: bool = True
    mcp_servers: list[dict[str, Any]] = Field(default_factory=list)

    model_config = {"extra": "ignore"}


def setup_logging(config: AgentConfig) -> None:
    logging.basicConfig(
        level=getattr(logging, config.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    # 抑制第三方库的 INFO 日志（重试、HTTP请求等）
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def _flatten_toml(data: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in data.items():
        flat_key = f"{prefix}{key}" if not prefix else f"{prefix}_{key}"
        if isinstance(value, dict):
            result.update(_flatten_toml(value, flat_key))
        else:
            result[flat_key] = value
    return result


def _apply_toml(config: AgentConfig, data: dict[str, Any]) -> None:
    flat = _flatten_toml(data)
    for key, value in flat.items():
        if hasattr(config, key):
            setattr(config, key, value)


def _apply_env(config: AgentConfig) -> None:
    for key in AgentConfig.model_fields.keys():
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
