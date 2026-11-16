"""El cerebro: decide entre la vía rápida (sin LLM) y el modelo con herramientas."""

from __future__ import annotations

import json
import re
from pathlib import Path

from tars.llm import LLMError
from tars.personality import Personality, system_prompt
from tars.robots import Fleet, normalize

MAX_TOOL_ROUNDS = 4

# Parada de emergencia: la frase entera es una orden de parar (así "¿para qué
# sirve el rover?" no dispara nada), o menciona una emergencia.
_STOP_WORD = r"(alto|para|paren|parad|parar|parate|parense|detente|detenganse|detener|stop|quieto|quietos|frena|frenen)"
_STOP_FILLER = r"(ya|todo|todos|ahora|ahi|los robots|el robot|inmediatamente|ya mismo)"
STOP_RE = re.compile(rf"^(tars )?{_STOP_WORD}( {_STOP_FILLER})*$")
EMERGENCY_RE = re.compile(r"\b(parada de emergencia|emergencia|aborta|abortar)\b")

SETTING_RE = re.compile(r"\b(humor|honestidad|sinceridad)\b[^\d]{0,25}(\d{1,3})\b")
SETTING_NAMES = {"humor": "humor", "honestidad": "honestidad", "sinceridad": "honestidad"}


def is_stop(text: str) -> bool:
    norm = re.sub(r"[^\w ]", " ", normalize(text))
    norm = " ".join(norm.split())
    return bool(STOP_RE.match(norm) or EMERGENCY_RE.search(norm))


def parse_setting(text: str) -> tuple[str, int] | None:
    match = SETTING_RE.search(normalize(text))
    if match:
        return SETTING_NAMES[match.group(1)], int(match.group(2))
    return None


class _StreamGate:
    """Retiene la salida si parece JSON (una llamada a herramienta escrita como
    texto por un modelo pequeño) para no leerle llaves al usuario."""

    def __init__(self, sink):
        self.sink = sink
        self.buffer = ""
        self.mode = None  # None = indeciso, "pass" = dejar pasar, "hold" = retener

    def feed(self, piece: str) -> None:
        if self.mode == "pass":
            if self.sink:
                self.sink(piece)
            return
        self.buffer += piece
        if self.mode is None and self.buffer.strip():
            if self.buffer.lstrip()[0] in "{[<`":
                self.mode = "hold"
            else:
                self.mode = "pass"
                self.flush()

    def flush(self) -> None:
        if self.buffer and self.sink:
            self.sink(self.buffer)
        self.buffer = ""


def parse_inline_tool_calls(content: str) -> list[dict]:
    """Recupera llamadas del estilo {"name": ..., "arguments": {...}} escritas como texto."""
    text = content.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text).strip()
    text = re.sub(r"^<tool_call>|</tool_call>$", "", text).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    calls = []
    for item in data if isinstance(data, list) else [data]:
        if isinstance(item, dict) and isinstance(item.get("name"), str):
            args = item.get("arguments", item.get("parameters", {}))
            if isinstance(args, dict):
                calls.append({"function": {"name": item["name"], "arguments": args}})
    return calls


class Brain:
    def __init__(
        self,
        llm,
        fleet: Fleet,
        personality: Personality | None = None,
        max_history: int = 12,
        state_path: Path | None = None,
        on_command=None,
    ):
        self.llm = llm
        self.fleet = fleet
        self.personality = personality or Personality()
        self.max_history = max_history
        self.state_path = state_path
        self.on_command = on_command  # callback(resultado) para mostrar qué se envió
        self.history: list[dict] = []
        self.personality.load_state(state_path)

    def reset(self) -> None:
        self.history.clear()

    # ------------------------------------------------------------------ API
    def handle(self, text: str, on_token=None) -> str:
        """Procesa una frase del operador. Todo lo devuelto pasa también por on_token."""
        text = text.strip()
        if not text:
            return ""

        if is_stop(text):
            return self._say(text, self._emergency_stop(), on_token)

        setting = parse_setting(text)
        if setting:
            name, value = setting
            value = self.personality.set(name, value)
            self.personality.save_state(self.state_path)
            return self._say(text, f"{name.capitalize()} ajustado al {value} por ciento.", on_token)

        try:
            reply, turn = self._ask_llm(text, on_token)
        except LLMError as exc:
            message = f"Mi módulo de lenguaje no responde. {exc}"
            if on_token:
                on_token(message)
            return message
        self.history.extend(turn)
        self._trim_history()
        return reply

    # ------------------------------------------------------------ internals
    def _say(self, user_text: str, reply: str, on_token) -> str:
        self.history += [
            {"role": "user", "content": user_text},
            {"role": "assistant", "content": reply},
        ]
        self._trim_history()
        if on_token:
            on_token(reply)
        return reply

    def _emergency_stop(self) -> str:
        results = self.fleet.stop_all()
        for result in results.values():
            self._notify(result)
        if not results:
            return "No hay robots configurados que detener."
        failed = [name for name, r in results.items() if not r.get("ok")]
        if failed:
            return (
                f"Atención: no pude detener {', '.join(failed)}. "
                f"Detenidos: {', '.join(n for n in results if n not in failed) or 'ninguno'}."
            )
        return f"Parada enviada a {', '.join(results)}."

    def _notify(self, result: dict) -> None:
        if self.on_command:
            self.on_command(result)

    def _run_tool(self, call: dict) -> dict:
        function = call.get("function") or {}
        args = function.get("arguments") or {}
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {}
        if function.get("name") != "comando_robot":
            return {"ok": False, "error": f"no existe la herramienta '{function.get('name')}'"}
        command_args = args.get("argumentos") or args.get("args") or {}
        if not isinstance(command_args, dict):
            command_args = {}
        # Los modelos pequeños a veces ponen los argumentos al mismo nivel.
        extras = {k: v for k, v in args.items() if k not in ("robot", "comando", "argumentos", "args")}
        result = self.fleet.execute(args.get("robot"), args.get("comando"), {**extras, **command_args})
        self._notify(result)
        return result

    def _ask_llm(self, text: str, on_token) -> tuple[str, list[dict]]:
        system = system_prompt(self.personality, self.fleet.describe())
        turn = [{"role": "user", "content": text}]
        tools = self.fleet.tool_schema()
        for _ in range(MAX_TOOL_ROUNDS):
            gate = _StreamGate(on_token)
            messages = [{"role": "system", "content": system}, *self.history, *turn]
            result = self.llm.chat(messages, tools=tools, on_token=gate.feed)
            calls = result["tool_calls"] or (
                parse_inline_tool_calls(result["content"]) if gate.mode == "hold" else []
            )
            if not calls:
                gate.flush()
                reply = result["content"].strip()
                turn.append({"role": "assistant", "content": reply})
                return reply, turn
            turn.append({"role": "assistant", "content": "", "tool_calls": calls})
            for call in calls:
                outcome = self._run_tool(call)
                turn.append(
                    {
                        "role": "tool",
                        "tool_name": "comando_robot",
                        "content": json.dumps(outcome, ensure_ascii=False),
                    }
                )
        reply = "Me he quedado en bucle con los comandos. Repíteme la orden de forma más simple."
        if on_token:
            on_token(reply)
        turn.append({"role": "assistant", "content": reply})
        return reply, turn

    def _trim_history(self) -> None:
        if len(self.history) > self.max_history:
            self.history = self.history[-self.max_history :]
            while self.history and self.history[0]["role"] != "user":
                self.history.pop(0)
