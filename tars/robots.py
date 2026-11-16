"""Flota de robots: lista cerrada de comandos, validación y envío.

El modelo de lenguaje nunca habla directamente con el hardware. Solo puede
pedir un (robot, comando, argumentos) y aquí se comprueba contra lo declarado
en config.toml antes de enviar nada.
"""

from __future__ import annotations

import itertools
import unicodedata
from dataclasses import dataclass, field

from tars.transports import TransportError, make_transport

TRANSPORT_KEYS = {"puerto", "baudios", "espera_seg", "tema", "broker", "url"}


class CommandError(Exception):
    pass


def normalize(text: str) -> str:
    """Minúsculas y sin tildes, para comparar nombres con tolerancia."""
    text = unicodedata.normalize("NFD", str(text).lower().strip())
    return "".join(c for c in text if unicodedata.category(c) != "Mn")


@dataclass
class Param:
    name: str
    kind: str = "numero"  # numero | texto | booleano
    min: float | None = None
    max: float | None = None
    options: list | None = None
    optional: bool = False

    def check(self, value):
        if self.kind == "numero":
            if isinstance(value, bool):
                raise CommandError(f"'{self.name}' debe ser un número")
            try:
                number = float(str(value).replace(",", "."))
            except ValueError:
                raise CommandError(f"'{self.name}' debe ser un número, no '{value}'") from None
            if number != number or number in (float("inf"), float("-inf")):
                raise CommandError(f"'{self.name}' debe ser un número finito")
            if self.min is not None and number < self.min:
                raise CommandError(f"'{self.name}'={value} está por debajo del mínimo ({self.min})")
            if self.max is not None and number > self.max:
                raise CommandError(f"'{self.name}'={value} supera el máximo ({self.max})")
            return int(number) if number.is_integer() else number
        if self.kind == "booleano":
            if isinstance(value, bool):
                return value
            norm = normalize(value)
            if norm in ("true", "si", "1", "verdadero"):
                return True
            if norm in ("false", "no", "0", "falso"):
                return False
            raise CommandError(f"'{self.name}' debe ser verdadero o falso")
        text = str(value)
        if self.options:
            for option in self.options:
                if normalize(option) == normalize(text):
                    return option
            raise CommandError(f"'{self.name}' debe ser uno de: {', '.join(map(str, self.options))}")
        return text

    def describe(self) -> str:
        if self.options:
            detail = "|".join(map(str, self.options))
        elif self.kind == "numero" and (self.min is not None or self.max is not None):
            detail = f"número {self.min if self.min is not None else ''}..{self.max if self.max is not None else ''}"
        else:
            detail = {"numero": "número", "booleano": "true|false"}.get(self.kind, "texto")
        return f"{self.name} ({detail}{', opcional' if self.optional else ''})"


@dataclass
class Command:
    name: str
    description: str = ""
    params: dict[str, Param] = field(default_factory=dict)

    def validate(self, args: dict) -> dict:
        by_norm = {normalize(k): v for k, v in (args or {}).items()}
        clean = {}
        for param in self.params.values():
            key = normalize(param.name)
            if key in by_norm and by_norm[key] is not None:
                clean[param.name] = param.check(by_norm.pop(key))
            elif not param.optional:
                raise CommandError(f"falta el argumento '{param.name}' ({param.describe()})")
            else:
                by_norm.pop(key, None)
        if by_norm:
            raise CommandError(
                f"'{self.name}' no acepta el argumento '{next(iter(by_norm))}'. "
                f"Acepta: {', '.join(self.params) or 'ninguno'}"
            )
        return clean


class Robot:
    def __init__(self, name: str, spec: dict):
        self.name = name
        self.description = spec.get("descripcion", "")
        self.stop_command = spec.get("comando_parada", "parar")
        self.commands: dict[str, Command] = {}
        for cmd_name, cmd_spec in (spec.get("comandos") or {}).items():
            params = {
                p_name: Param(
                    name=p_name,
                    kind=p.get("tipo", "numero"),
                    min=p.get("min"),
                    max=p.get("max"),
                    options=p.get("opciones"),
                    optional=p.get("opcional", False),
                )
                for p_name, p in (cmd_spec.get("parametros") or {}).items()
            }
            self.commands[cmd_name] = Command(cmd_name, cmd_spec.get("descripcion", ""), params)
        options = {k: v for k, v in spec.items() if k in TRANSPORT_KEYS}
        self.transport = make_transport(spec.get("transporte", "sim"), options)

    def find_command(self, name: str) -> Command:
        for cmd in self.commands.values():
            if normalize(cmd.name) == normalize(name):
                return cmd
        raise CommandError(
            f"el robot '{self.name}' no tiene el comando '{name}'. Tiene: {', '.join(self.commands)}"
        )


class Fleet:
    def __init__(self, robots_config: dict | None = None):
        self.robots = {name: Robot(name, spec) for name, spec in (robots_config or {}).items()}
        self._ids = itertools.count(1)

    def find_robot(self, name: str | None) -> Robot:
        if not name and len(self.robots) == 1:
            return next(iter(self.robots.values()))
        for robot in self.robots.values():
            if normalize(robot.name) == normalize(name or ""):
                return robot
        raise CommandError(
            f"no existe el robot '{name}'. Robots disponibles: {', '.join(self.robots) or 'ninguno'}"
        )

    def execute(self, robot_name: str | None, command_name: str, args: dict | None = None) -> dict:
        """Valida y envía. Nunca lanza: los fallos vuelven como {"ok": False}."""
        try:
            robot = self.find_robot(robot_name)
            command = robot.find_command(command_name or "")
            clean = command.validate(args or {})
            payload = {"id": next(self._ids), "cmd": command.name, "args": clean}
            reply = robot.transport.send(payload)
        except (CommandError, TransportError) as exc:
            return {"ok": False, "error": str(exc)}
        reply.setdefault("ok", True)
        return {"robot": robot.name, "comando": command.name, "argumentos": clean, **reply}

    def stop_all(self) -> dict[str, dict]:
        """Parada de emergencia: comando de parada a todos los robots."""
        results = {}
        for robot in self.robots.values():
            if robot.stop_command in robot.commands:
                results[robot.name] = self.execute(robot.name, robot.stop_command)
            else:
                results[robot.name] = {"ok": False, "error": "sin comando de parada configurado"}
        return results

    def describe(self) -> str:
        if not self.robots:
            return "(no hay ningún robot configurado)"
        lines = []
        for robot in self.robots.values():
            lines.append(f"- {robot.name}: {robot.description}")
            for cmd in robot.commands.values():
                params = "; ".join(p.describe() for p in cmd.params.values()) or "sin argumentos"
                lines.append(f"    · {cmd.name}: {cmd.description} [{params}]")
        return "\n".join(lines)

    def tool_schema(self) -> list[dict]:
        if not self.robots:
            return []
        commands = sorted({c for r in self.robots.values() for c in r.commands})
        return [
            {
                "type": "function",
                "function": {
                    "name": "comando_robot",
                    "description": "Envía un comando a uno de los robots y devuelve su respuesta.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "robot": {"type": "string", "enum": list(self.robots)},
                            "comando": {"type": "string", "enum": commands},
                            "argumentos": {
                                "type": "object",
                                "description": "Argumentos del comando, p. ej. {\"distancia_cm\": 50}",
                            },
                        },
                        "required": ["robot", "comando"],
                    },
                },
            }
        ]

    def close(self) -> None:
        for robot in self.robots.values():
            robot.transport.close()
