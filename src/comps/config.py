from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = PROJECT_ROOT / "config"
CACHE_DIR = PROJECT_ROOT / "cache"
OUTPUT_DIR = PROJECT_ROOT / "output"


def _load_env() -> None:
    load_dotenv(PROJECT_ROOT / ".env")


def get_openai_api_key() -> str | None:
    _load_env()
    return (os.getenv("OPENAI_API_KEY") or "").strip() or None


def get_openai_model() -> str:
    _load_env()
    return (os.getenv("OPENAI_MODEL") or "gpt-4o").strip()


def get_openai_base_url() -> str:
    _load_env()
    return (os.getenv("OPENAI_BASE_URL") or "").strip()


def get_anthropic_api_key() -> str | None:
    _load_env()
    return (os.getenv("ANTHROPIC_API_KEY") or "").strip() or None


def get_anthropic_model() -> str:
    _load_env()
    return (os.getenv("ANTHROPIC_MODEL") or "claude-sonnet-4-20250514").strip()


def get_llm_provider() -> str:
    """LLM provider selector: 'auto' (default), 'openai', 'openai-compat', 'anthropic', 'codex'."""
    _load_env()
    return (os.getenv("LLM_PROVIDER") or "auto").strip().lower()


def get_codex_model() -> str:
    """Optional explicit model for the Codex provider (empty = use account default)."""
    _load_env()
    return (os.getenv("CODEX_MODEL") or "").strip()


def get_sec_user_agent() -> str:
    _load_env()
    return os.getenv("SEC_USER_AGENT", "Comps Scrubber contact@example.com")


@dataclass
class CategoryPolicy:
    treatment: str
    enabled: bool = True
    requires_review: bool = False


@dataclass
class Policy:
    categories: dict[str, CategoryPolicy] = field(default_factory=dict)

    def treatment(self, category: str) -> str | None:
        p = self.categories.get(category)
        return p.treatment if p else None

    def enabled(self, category: str) -> bool:
        p = self.categories.get(category)
        return p.enabled if p else True

    def requires_review(self, category: str) -> bool:
        p = self.categories.get(category)
        return p.requires_review if p else False


def load_policy(path: Path | str | None = None) -> Policy:
    p = Path(path) if path else CONFIG_DIR / "policy.yaml"
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    cats: dict[str, CategoryPolicy] = {}
    for name, cfg in data.get("categories", {}).items():
        cats[name] = CategoryPolicy(
            treatment=cfg["treatment"],
            enabled=cfg.get("enabled", True),
            requires_review=cfg.get("requires_review", False),
        )
    return Policy(categories=cats)


@dataclass
class PeerConfig:
    peers: list[str]
    num_years: int
    output: Path


def load_peers(path: Path | str | None = None) -> PeerConfig:
    p = Path(path) if path else CONFIG_DIR / "peers.yaml"
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    out = Path(data.get("output", "output/comps_output.xlsx"))
    if not out.is_absolute():
        out = PROJECT_ROOT / out
    return PeerConfig(
        peers=data.get("peers", []),
        num_years=data.get("num_years", 3),
        output=out,
    )
