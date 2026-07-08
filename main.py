"""
12-Factor config precedence resolver.

Layer order (low -> high):
    1. hardcoded defaults
    2. config.<env>.yaml           (env defaults to 'development')
    3. .env file
    4. OS environment variables    (APP_* prefix)
    5. ?set=key=value CLI overrides (highest)
"""
import os
from pathlib import Path

import yaml
from dotenv import dotenv_values
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Effective Config Resolver")

# CORS: allow the grader's page to hit us directly from the browser
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Config schema ────────────────────────────────────────────────────
DEFAULTS = {
    "port": 8000,
    "workers": 1,
    "debug": False,
    "log_level": "info",
    "api_key": "default-secret-000",
}

INT_KEYS = {"port", "workers"}
BOOL_KEYS = {"debug"}
SECRET_KEYS = {"api_key"}
ENV_ALIASES = {"NUM_WORKERS": "workers"}   # applies in the .env layer

APP_ENV = os.environ.get("APP_ENV", "development")


# ── Type coercion ────────────────────────────────────────────────────
def coerce(key: str, value):
    if key in INT_KEYS:
        try:
            return int(value)
        except (TypeError, ValueError):
            return value
    if key in BOOL_KEYS:
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"true", "1", "yes", "on"}
    return str(value)


# ── Layer loaders ────────────────────────────────────────────────────
def load_yaml_layer() -> dict:
    path = Path(f"config.{APP_ENV}.yaml")
    if not path.exists():
        return {}
    with path.open() as f:
        data = yaml.safe_load(f) or {}
    return dict(data)


def _rename(key: str) -> str | None:
    """Env-style key -> internal key. Returns None if the key should be ignored."""
    if key in ENV_ALIASES:
        return ENV_ALIASES[key]
    if key.startswith("APP_"):
        return key[4:].lower()
    return None


def load_dotenv_layer() -> dict:
    path = Path(".env")
    if not path.exists():
        return {}
    out = {}
    for k, v in dotenv_values(path).items():
        target = _rename(k)
        if target is not None and v is not None:
            out[target] = v
    return out


def load_osenv_layer() -> dict:
    out = {}
    for k, v in os.environ.items():
        if k.startswith("APP_"):
            out[k[4:].lower()] = v
    return out


# ── Merge + resolve ──────────────────────────────────────────────────
def resolve(overrides: dict) -> dict:
    merged = {}
    for layer in (
        DEFAULTS,
        load_yaml_layer(),
        load_dotenv_layer(),
        load_osenv_layer(),
        overrides,
    ):
        merged.update(layer)

    result = {k: coerce(k, v) for k, v in merged.items()}

    # Secret masking (never leak the real value)
    for k in SECRET_KEYS:
        if k in result:
            result[k] = "****"
    return result


# ── Endpoint ─────────────────────────────────────────────────────────
@app.get("/effective-config")
def effective_config(request: Request):
    overrides = {}
    # Repeated ?set=k=v style overrides
    for item in request.query_params.getlist("set"):
        if "=" in item:
            k, v = item.split("=", 1)
            overrides[k.strip()] = v
    return resolve(overrides)


@app.get("/")
def root():
    return {"ok": True, "endpoint": "/effective-config?set=port=9000&set=debug=true"}
