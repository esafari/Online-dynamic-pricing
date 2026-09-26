from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "configs"


def load_yaml(name: str) -> Any:
    path = CONFIG_DIR / name
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PDS_", extra="ignore")

    env: str = "local"
    host: str = "0.0.0.0"
    port: int = 8080
    log_buffer_dir: Path = ROOT / "data" / "log_buffer"
    kafka_enabled: bool = False
    kafka_topic: str = "pricing.decisions.v1"
    offer_ttl_seconds: int = 600
    epsilon: float = 0.05
    propensity_mc_samples: int = 256
    propensity_floor: float = 0.05
    charm_pricing: bool = True
    default_currency: str = "USD"
    unknown_sku_policy: str = "error"  # error | category_fallback
    latency_budget_ms: int = 69


class VersionPinsConfig(BaseModel):
    policy_id: str
    causal_model_id: str
    guardrail_version: str
    candidate_set_version: str
    bandit_version: str
    reward_definition: str = "margin"
    response_schema_version: str = "v1"


class RuntimeConfig(BaseModel):
    settings: Settings
    versions: VersionPinsConfig
    ladders: dict[str, Any]
    guardrails: dict[str, Any]
    features: dict[str, Any]
    catalog: dict[str, Any]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


@lru_cache(maxsize=1)
def get_runtime_config() -> RuntimeConfig:
    return RuntimeConfig(
        settings=get_settings(),
        versions=VersionPinsConfig.model_validate(load_yaml("versions.yaml")),
        ladders=load_yaml("ladders.yaml"),
        guardrails=load_yaml("guardrails.yaml"),
        features=load_yaml("features.yaml"),
        catalog=load_yaml("catalog.yaml"),
    )


def reload_runtime_config() -> RuntimeConfig:
    get_runtime_config.cache_clear()
    get_settings.cache_clear()
    return get_runtime_config()
