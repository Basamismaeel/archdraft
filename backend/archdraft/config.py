"""Paths and environment settings shared by the API, the CLI script and `adk web`."""

import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent
SAMPLES_DIR = REPO_ROOT / "samples"
DATA_DIR = REPO_ROOT / "data"
PROMPTS_DIR = Path(__file__).resolve().parent / "agents" / "prompts"

# Variables already set in the shell win over .env, so a teammate can override per run.
load_dotenv(REPO_ROOT / ".env", override=False)


class ConfigError(RuntimeError):
    """Raised when a required setting is missing. The message says how to fix it."""


def model_name() -> str:
    """The Gemini model string, read from GEMINI_MODEL. Never defaulted in code."""
    name = os.environ.get("GEMINI_MODEL", "").strip()
    if not name:
        raise ConfigError(
            "GEMINI_MODEL is not set. Copy .env.example to .env and set GEMINI_MODEL "
            "to a model listed at https://ai.google.dev/gemini-api/docs/models."
        )
    return name


def fallback_model_names() -> list[str]:
    """Optional backup models, tried in order when GEMINI_MODEL is overloaded (HTTP 429/5xx).

    GEMINI_FALLBACK_MODEL takes one model or a comma-separated list."""
    raw = os.environ.get("GEMINI_FALLBACK_MODEL", "")
    return [name.strip() for name in raw.split(",") if name.strip()]


def require_credentials() -> None:
    """Fail early with a readable message instead of a stack trace from the SDK."""
    vertex = os.environ.get("GOOGLE_GENAI_USE_ENTERPRISE") or os.environ.get(
        "GOOGLE_GENAI_USE_VERTEXAI",
        "",  # the pre-2026 name, still accepted
    )
    if vertex.upper() in {"TRUE", "1"}:
        return
    if not (os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")):
        raise ConfigError(
            "GOOGLE_API_KEY is not set. Put your Gemini API key in the .env file "
            "at the repository root (see .env.example)."
        )
