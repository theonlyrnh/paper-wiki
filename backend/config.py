"""Configuration loader for Paper Wiki."""

import os
import re
import yaml
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent

# Load .env file if it exists
_env_path = PROJECT_ROOT / ".env"
if _env_path.exists():
    for line in _env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, value = line.split("=", 1)
            key, value = key.strip(), value.strip()
            if key and value and not key.startswith("#"):
                os.environ.setdefault(key, value)


def _expand_env_vars(value: str) -> str:
    """Replace ${ENV_VAR} placeholders with environment variable values."""
    pattern = re.compile(r"\$\{(\w+)\}")

    def replacer(match):
        var_name = match.group(1)
        return os.environ.get(var_name, "")

    if isinstance(value, str):
        return pattern.sub(replacer, value)
    return value


def _walk_and_expand(obj):
    """Recursively expand env vars in config."""
    if isinstance(obj, dict):
        return {k: _walk_and_expand(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_walk_and_expand(item) for item in obj]
    elif isinstance(obj, str):
        return _expand_env_vars(obj)
    return obj


def load_config() -> dict:
    """Load and return the config dictionary."""
    config_path = PROJECT_ROOT / "config.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    config = _walk_and_expand(raw)

    # Override LLM config from env vars if set
    if os.environ.get("LLM_API_KEY"):
        config.setdefault("llm", {})
        config["llm"]["api_key"] = os.environ["LLM_API_KEY"]
    if os.environ.get("LLM_API_BASE"):
        config.setdefault("llm", {})
        config["llm"]["api_base"] = os.environ["LLM_API_BASE"]
    if os.environ.get("LLM_MODEL"):
        config.setdefault("llm", {})
        config["llm"]["model"] = os.environ["LLM_MODEL"]

    return config


CONFIG = load_config()


def get_storage_path(key: str) -> Path:
    """Get an absolute storage path from config."""
    relative = CONFIG["storage"][key]
    path = PROJECT_ROOT / relative
    # For file paths (with extension), ensure parent dir exists
    # For directory paths, create the directory itself
    if path.suffix:
        path.parent.mkdir(parents=True, exist_ok=True)
    else:
        path.mkdir(parents=True, exist_ok=True)
    return path
