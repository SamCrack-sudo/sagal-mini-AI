"""Carga de config.toml con valores por defecto."""

from __future__ import annotations

import copy
import tomllib
from pathlib import Path

DEFAULTS: dict = {
    "tars": {"nombre": "TARS", "idioma": "español", "humor": 75, "honestidad": 90},
    "llm": {
        "host": "http://127.0.0.1:11434",
        "modelo": "llama3.2:3b",
        "contexto": 4096,
        "max_tokens": 200,
        "temperatura": 0.6,
    },
    "voz": {
        "stt_modelo": "base",
        "stt_idioma": "es",
        "tts_voz": "voces/es_MX-claude-high.onnx",
        "silencio_seg": 1.0,
        "max_seg": 15,
    },
    "robots": {},
}

SEARCH_PATHS = (Path("config.toml"), Path.home() / ".config" / "tars" / "config.toml")


def find_config(explicit: str | None = None) -> Path | None:
    if explicit:
        path = Path(explicit)
        if not path.is_file():
            raise FileNotFoundError(f"No existe el archivo de configuración: {path}")
        return path
    return next((p for p in SEARCH_PATHS if p.is_file()), None)


def load_config(explicit: str | None = None) -> dict:
    config = copy.deepcopy(DEFAULTS)
    path = find_config(explicit)
    if path:
        with path.open("rb") as fh:
            user = tomllib.load(fh)
        for section, values in user.items():
            if isinstance(values, dict) and isinstance(config.get(section), dict):
                config[section].update(values)
            else:
                config[section] = values
    config["_ruta"] = path
    return config
