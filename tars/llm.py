"""Cliente mínimo de Ollama (solo biblioteca estándar)."""

from __future__ import annotations

import json
import urllib.error
import urllib.request


class LLMError(Exception):
    pass


class OllamaClient:
    def __init__(self, host: str, model: str, options: dict | None = None, timeout: float = 300):
        self.host = host.rstrip("/")
        self.model = model
        self.options = options or {}
        self.timeout = timeout
        # Sin proxy: Ollama corre en esta máquina o en la red local.
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def _open(self, path: str, body: dict | None = None, timeout: float | None = None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            self.host + path, data=data, headers={"Content-Type": "application/json"}
        )
        try:
            return self._opener.open(req, timeout=timeout or self.timeout)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")
            try:
                detail = json.loads(detail).get("error", detail)
            except json.JSONDecodeError:
                pass
            if exc.code == 404 and body is not None:
                raise LLMError(
                    f"Ollama no tiene el modelo '{self.model}'. Descárgalo con: ollama pull {self.model}"
                ) from exc
            raise LLMError(f"Ollama devolvió un error {exc.code}: {detail}") from exc
        except OSError as exc:
            raise LLMError(
                f"No puedo conectar con Ollama en {self.host}. ¿Está en marcha? (ollama serve)"
            ) from exc

    def available_models(self) -> list[str]:
        with self._open("/api/tags", timeout=5) as resp:
            return [m["name"] for m in json.load(resp).get("models", [])]

    def chat(self, messages: list[dict], tools: list[dict] | None = None, on_token=None) -> dict:
        """Devuelve {"content": str, "tool_calls": [...]}. Emite el texto por on_token según llega."""
        body = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "options": self.options,
            "keep_alive": "30m",  # el modelo queda en RAM entre frases
        }
        if tools:
            body["tools"] = tools
        content, tool_calls = [], []
        try:
            with self._open("/api/chat", body) as resp:
                for line in resp:
                    if not line.strip():
                        continue
                    chunk = json.loads(line)
                    if chunk.get("error"):
                        raise LLMError(f"Ollama: {chunk['error']}")
                    message = chunk.get("message") or {}
                    piece = message.get("content") or ""
                    if piece:
                        content.append(piece)
                        if on_token:
                            on_token(piece)
                    tool_calls.extend(message.get("tool_calls") or [])
                    if chunk.get("done"):
                        break
        except (OSError, json.JSONDecodeError) as exc:
            raise LLMError(f"Se cortó la respuesta de Ollama: {exc}") from exc
        return {"content": "".join(content), "tool_calls": tool_calls}
