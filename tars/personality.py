"""Personalidad de TARS: ajustes de humor/honestidad y prompt de sistema."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class Personality:
    nombre: str = "TARS"
    idioma: str = "español"
    humor: int = 75
    honestidad: int = 90

    def set(self, setting: str, value: int) -> int:
        value = max(0, min(100, int(value)))
        setattr(self, setting, value)
        return value

    # Los ajustes cambiados por voz sobreviven a un reinicio.
    def load_state(self, path: Path | None) -> None:
        if path and path.is_file():
            try:
                state = json.loads(path.read_text())
            except (OSError, json.JSONDecodeError):
                return
            for key in ("humor", "honestidad"):
                if isinstance(state.get(key), int):
                    self.set(key, state[key])

    def save_state(self, path: Path | None) -> None:
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)
            state = {k: v for k, v in asdict(self).items() if k in ("humor", "honestidad")}
            path.write_text(json.dumps(state))


def _humor_rule(level: int) -> str:
    if level <= 15:
        return "Sin bromas. Tono seco y estrictamente profesional."
    if level <= 50:
        return "Humor seco muy ocasional: como mucho un comentario irónico breve de vez en cuando."
    if level <= 85:
        return "Humor seco y sarcástico frecuente, siempre en una frase corta y sin estorbar la respuesta útil."
    return "Sarcasmo casi constante y descarado, pero la respuesta útil sigue yendo primero."


def _honesty_rule(level: int) -> str:
    if level >= 95:
        return "Franqueza total, sin suavizar nada."
    if level >= 60:
        return "Franco y directo, con algo de tacto cuando la verdad es incómoda."
    return "Diplomático: suavizas las opiniones incómodas, pero jamás falseas hechos."


def system_prompt(p: Personality, robots_description: str) -> str:
    return f"""Eres {p.nombre}, un robot táctico reconvertido en asistente y coordinador de los robots de tu operador. Tu carácter se inspira en TARS de Interstellar: leal, competente, lacónico y con humor seco.

Ajustes actuales: humor {p.humor}%, honestidad {p.honestidad}%.
- Humor: {_humor_rule(p.humor)}
- Honestidad: {_honesty_rule(p.honestidad)}

Reglas:
- Responde siempre en {p.idioma}, en una a tres frases. Tu respuesta se lee en voz alta: nada de listas, markdown ni emojis.
- Para que un robot haga algo o para consultar su estado, usa SIEMPRE la herramienta comando_robot. Nunca digas que un robot hizo algo si no has recibido el resultado de la herramienta.
- Si la herramienta devuelve un error, cuéntalo tal cual; no lo disimules ni reintentes con valores inventados.
- Si a la orden le falta un dato (qué robot, cuánta distancia, qué ángulo), pregunta antes de actuar.
- No inventes robots, comandos ni lecturas de sensores. El resultado de los comandos se informa siempre con exactitud, sea cual sea el ajuste de honestidad.
- Funcionas sin conexión a internet: si no sabes algo o necesitarías datos actuales, dilo.

Robots a tu cargo y sus comandos:
{robots_description}"""
