"""Interfaz de terminal: chat por texto o por voz."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from tars.brain import Brain
from tars.config import load_config
from tars.llm import LLMError, OllamaClient
from tars.personality import Personality
from tars.robots import Fleet
from tars.transports import TransportError

STATE_PATH = Path.home() / ".config" / "tars" / "state.json"
DIM, RESET = ("\033[2m", "\033[0m") if sys.stdout.isatty() else ("", "")

HELP = """Comandos: /robots  lista robots y comandos    /estado  ajustes actuales
          /reset   olvida la conversación     /salir   termina
Siempre disponibles sin pasar por el modelo: "para" / "alto" (parada de todos los
robots) y "pon el humor al 60" / "honestidad al 100"."""


def show_command(result: dict) -> None:
    if "comando" in result:
        mark = "✓" if result.get("ok") else "✗"
        args = json.dumps(result.get("argumentos", {}), ensure_ascii=False)
        print(f"{DIM}  → {result['robot']}.{result['comando']} {args} {mark}{RESET}")
    else:
        print(f"{DIM}  → rechazado: {result.get('error')}{RESET}")


def build(args) -> tuple[dict, Brain, OllamaClient]:
    config = load_config(args.config)
    llm_cfg = config["llm"]
    llm = OllamaClient(
        host=llm_cfg["host"],
        model=args.modelo or llm_cfg["modelo"],
        options={
            "num_ctx": llm_cfg["contexto"],
            "num_predict": llm_cfg["max_tokens"],
            "temperature": llm_cfg["temperatura"],
        },
    )
    tars_cfg = config["tars"]
    personality = Personality(
        nombre=tars_cfg["nombre"],
        idioma=tars_cfg["idioma"],
        humor=tars_cfg["humor"],
        honestidad=tars_cfg["honestidad"],
    )
    fleet = Fleet(config["robots"])
    brain = Brain(llm, fleet, personality, state_path=STATE_PATH, on_command=show_command)
    return config, brain, llm


def check(config: dict, brain: Brain, llm: OllamaClient) -> int:
    print(f"Configuración: {config['_ruta'] or '(valores por defecto, no hay config.toml)'}")
    status = 0
    try:
        models = llm.available_models()
        if any(m == llm.model or m.split(":")[0] == llm.model for m in models):
            print(f"Ollama: OK, modelo '{llm.model}' disponible")
        else:
            print(f"Ollama: en marcha, pero falta el modelo. Ejecuta: ollama pull {llm.model}")
            status = 1
    except (LLMError, OSError) as exc:
        print(f"Ollama: {exc}")
        status = 1
    print(f"Robots:\n{brain.fleet.describe()}")
    return status


def handle_slash(line: str, brain: Brain) -> bool:
    """Devuelve False si hay que salir."""
    command = line.lower()
    if command in ("/salir", "/exit", "/quit"):
        return False
    if command == "/robots":
        print(brain.fleet.describe())
    elif command == "/estado":
        p = brain.personality
        print(f"Humor {p.humor}%, honestidad {p.honestidad}%, modelo {brain.llm.model}")
    elif command == "/reset":
        brain.reset()
        print("Conversación olvidada.")
    else:
        print(HELP)
    return True


def respond(brain: Brain, text: str, speaker=None) -> None:
    name = brain.personality.nombre
    started = False

    def on_token(piece: str) -> None:
        nonlocal started
        if not started:
            print(f"{name}> ", end="")
            started = True
        print(piece, end="", flush=True)
        if speaker:
            speaker.feed(piece)

    brain.handle(text, on_token)
    print()
    if speaker:
        speaker.finish()


def run_text(brain: Brain) -> None:
    print(f"{brain.personality.nombre} en línea. Escribe /ayuda para ver los comandos.")
    while True:
        try:
            line = input("tú> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not line:
            continue
        if line.startswith("/"):
            if not handle_slash(line, brain):
                return
            continue
        try:
            respond(brain, line)
        except KeyboardInterrupt:
            print("\n(interrumpido)")


def run_voice(brain: Brain, config: dict) -> int:
    from tars.voice import Listener, SentenceSpeaker, Speaker, VoiceError

    voice_cfg = config["voz"]
    try:
        print("Cargando el modelo de voz...")
        listener = Listener(
            voice_cfg["stt_modelo"], voice_cfg["stt_idioma"], voice_cfg["silencio_seg"], voice_cfg["max_seg"]
        )
        speaker = Speaker(voice_cfg["tts_voz"])
    except VoiceError as exc:
        print(exc, file=sys.stderr)
        return 1
    if not speaker.backend:
        print(speaker.why_silent())
    sentences = SentenceSpeaker(speaker)
    print(f"{brain.personality.nombre} en línea. Pulsa Enter y habla (o escribe la orden). /salir para terminar.")
    while True:
        try:
            line = input("[Enter para hablar] ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if line.startswith("/"):
            if not handle_slash(line, brain):
                return 0
            continue
        if not line:
            try:
                print("Escuchando...")
                line = listener.listen()
            except VoiceError as exc:
                print(exc, file=sys.stderr)
                return 1
            if not line:
                print("(no oí nada)")
                continue
            print(f"tú> {line}")
        try:
            respond(brain, line, sentences)
        except KeyboardInterrupt:
            print("\n(interrumpido)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tars", description="Asistente local estilo TARS para tus robots")
    parser.add_argument("--config", help="ruta a config.toml (por defecto ./config.toml)")
    parser.add_argument("--modelo", help="modelo de Ollama (sobrescribe el de la configuración)")
    parser.add_argument("--voz", action="store_true", help="modo voz: micrófono y altavoz")
    parser.add_argument("--una", metavar="FRASE", help="responde a una sola frase y termina")
    parser.add_argument("--check", action="store_true", help="comprueba Ollama, el modelo y los robots")
    args = parser.parse_args(argv)

    try:
        config, brain, llm = build(args)
    except (FileNotFoundError, TransportError, ValueError) as exc:
        print(f"Error de configuración: {exc}", file=sys.stderr)
        return 2
    try:
        if args.check:
            return check(config, brain, llm)
        if args.una:
            respond(brain, args.una)
            return 0
        if args.voz:
            return run_voice(brain, config)
        run_text(brain)
        return 0
    finally:
        brain.fleet.close()


if __name__ == "__main__":
    raise SystemExit(main())
