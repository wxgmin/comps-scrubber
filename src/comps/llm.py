from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from abc import ABC, abstractmethod
from pathlib import Path

from .config import (
    PROJECT_ROOT,
    get_anthropic_api_key,
    get_anthropic_model,
    get_codex_model,
    get_llm_provider,
    get_openai_api_key,
    get_openai_base_url,
    get_openai_model,
)

_SCHEMA_NAME = "adjustments_extraction"

_NOT_CONFIGURED = (
    "No LLM provider is configured. Set LLM_PROVIDER in .env to one of "
    "'openai', 'openai-compat', 'anthropic', or 'codex', and supply that "
    "provider's credentials (e.g. OPENAI_API_KEY, ANTHROPIC_API_KEY, or a "
    "ChatGPT-authenticated Codex CLI)."
)


class LLMProvider(ABC):
    """Turns (system, user, json_schema) into a parsed JSON object."""

    name: str = ""

    @abstractmethod
    def extract_json(self, system: str, user: str, json_schema: dict) -> dict:
        raise NotImplementedError


class OpenAIProvider(LLMProvider):
    """OpenAI platform API (native JSON-schema structured output)."""

    name = "openai"

    def extract_json(self, system: str, user: str, json_schema: dict) -> dict:
        key = get_openai_api_key()
        if not key:
            raise RuntimeError(_NOT_CONFIGURED)
        from openai import OpenAI

        client = OpenAI(api_key=key)
        resp = client.chat.completions.create(
            model=get_openai_model(),
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {"name": _SCHEMA_NAME, "schema": json_schema, "strict": False},
            },
            temperature=0.0,
        )
        return json.loads(resp.choices[0].message.content or "{}")


class OpenAICompatProvider(LLMProvider):
    """Any OpenAI-compatible endpoint: DeepSeek, Groq, OpenRouter, Ollama, LM Studio, etc.

    Uses `response_format={"type": "json_object"}` for maximum compatibility and injects
    the schema into the system prompt (many third-party endpoints do not support the
    native `json_schema` response format).
    """

    name = "openai-compat"

    def extract_json(self, system: str, user: str, json_schema: dict) -> dict:
        key = get_openai_api_key()
        base_url = get_openai_base_url()
        if not key or not base_url:
            raise RuntimeError(
                "OPENAI_API_KEY and OPENAI_BASE_URL are required for the 'openai-compat' provider."
            )
        from openai import OpenAI

        client = OpenAI(api_key=key, base_url=base_url)
        sys_msg = (
            system
            + "\n\nRespond with a single JSON object matching exactly this schema:\n"
            + json.dumps(json_schema)
        )
        resp = client.chat.completions.create(
            model=get_openai_model(),
            messages=[
                {"role": "system", "content": sys_msg},
                {"role": "user", "content": user},
            ],
            response_format={"type": "json_object"},
            temperature=0.0,
        )
        return json.loads(resp.choices[0].message.content or "{}")


class AnthropicProvider(LLMProvider):
    """Anthropic Claude via forced tool use (structured output)."""

    name = "anthropic"

    def extract_json(self, system: str, user: str, json_schema: dict) -> dict:
        key = get_anthropic_api_key()
        if not key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set.")
        import anthropic

        client = anthropic.Anthropic(api_key=key)
        resp = client.messages.create(
            model=get_anthropic_model(),
            max_tokens=4096,
            system=system,
            messages=[{"role": "user", "content": user}],
            tools=[
                {
                    "name": _SCHEMA_NAME,
                    "description": "Return the extracted adjustments as structured data.",
                    "input_schema": json_schema,
                }
            ],
            tool_choice={"type": "tool", "name": _SCHEMA_NAME},
        )
        for block in resp.content:
            if getattr(block, "type", None) == "tool_use":
                return block.input
        raise RuntimeError("Claude did not return a tool_use block for the extraction.")


class CodexProvider(LLMProvider):
    """OpenAI Codex CLI, authenticated with a ChatGPT account (no API key)."""

    name = "codex"

    def extract_json(self, system: str, user: str, json_schema: dict) -> dict:
        codex = _find_codex()
        if not codex:
            raise RuntimeError(
                "LLM_PROVIDER=codex but the Codex CLI was not found. Install/authenticate "
                "Codex (developers.openai.com/codex) or choose another LLM_PROVIDER."
            )

        cmd = [
            codex,
            "exec",
            "--skip-git-repo-check",
            "--ephemeral",
            "--ignore-user-config",  # skip the user's MCP servers; auth is separate
            "-s",
            "read-only",
            "-C",
            str(PROJECT_ROOT),
            "--output-schema",
            "<schema>",
            "-o",
            "<out>",
        ]
        model = get_codex_model()
        if model:
            cmd += ["-m", model]
        cmd += ["-"]  # read the prompt from stdin

        with tempfile.TemporaryDirectory() as td:
            schema_file = Path(td) / "schema.json"
            schema_file.write_text(json.dumps(json_schema), encoding="utf-8")
            out_file = Path(td) / "out.json"
            cmd = [str(schema_file) if a == "<schema>" else a for a in cmd]
            cmd = [str(out_file) if a == "<out>" else a for a in cmd]

            prompt = f"{system}\n\n{user}"
            proc = subprocess.run(
                cmd,
                input=prompt,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=900,
            )
            if proc.returncode != 0 or not out_file.exists():
                tail = (proc.stderr or "")[-2000:]
                raise RuntimeError(f"codex exec failed (exit {proc.returncode}): {tail}")

            raw = out_file.read_text(encoding="utf-8").strip()
            if raw.startswith("```"):
                raw = raw.strip("`")
                if "\n" in raw:
                    raw = raw[raw.find("\n") + 1 :]
                raw = raw.strip()
        return json.loads(raw)


PROVIDERS: dict[str, type[LLMProvider]] = {
    OpenAIProvider.name: OpenAIProvider,
    OpenAICompatProvider.name: OpenAICompatProvider,
    AnthropicProvider.name: AnthropicProvider,
    CodexProvider.name: CodexProvider,
}


def _find_codex() -> str | None:
    """Locate the Codex CLI binary (used for ChatGPT-account auth)."""
    env = os.getenv("CODEX_CLI_PATH")
    if env and Path(env).exists():
        return env
    on_path = shutil.which("codex")
    if on_path:
        return on_path
    # Codex records its own CLI path in config.toml (survives version bumps).
    cfg = Path.home() / ".codex" / "config.toml"
    if cfg.exists():
        try:
            for line in cfg.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("CODEX_CLI_PATH"):
                    val = line.split("=", 1)[1].strip().strip("'\"")
                    if val and Path(val).exists():
                        return val
        except OSError:
            pass
    # Windows Store installs live under WindowsApps with a versioned folder.
    pf = os.environ.get("ProgramFiles", r"C:\Program Files")
    base = Path(pf) / "WindowsApps"
    try:
        candidates = sorted(base.glob("OpenAI.Codex_*/app/resources/codex.exe"), reverse=True)
        if candidates:
            return str(candidates[0])
    except OSError:
        pass
    return None


def resolve_provider_name() -> str:
    """Resolve the configured provider, with sensible auto-detection."""
    name = get_llm_provider()
    if name in PROVIDERS:
        return name
    if name == "auto":
        if get_openai_api_key():
            return "openai"
        if get_anthropic_api_key():
            return "anthropic"
        if _find_codex():
            return "codex"
        return "openai"  # falls through to a clear error message
    raise ValueError(
        f"Unknown LLM_PROVIDER '{name}'. Choose one of: {sorted(PROVIDERS)} or 'auto'."
    )


def extract_json(system: str, user: str, json_schema: dict) -> dict:
    """Run the configured LLM provider and return the parsed structured object."""
    name = resolve_provider_name()
    return PROVIDERS[name]().extract_json(system, user, json_schema)
