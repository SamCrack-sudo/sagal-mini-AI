"""Transportes: cómo llega físicamente un comando al robot.

Todos envían el mismo mensaje (un objeto JSON) y devuelven la respuesta del
robot como dict. Las dependencias externas se importan solo si se usan.
"""

from __future__ import annotations

import json
import urllib.request


class TransportError(Exception):
    pass


class SimTransport:
    """No envía nada: guarda los mensajes. Para probar sin hardware."""

    def __init__(self, **_):
        self.sent: list[dict] = []

    def send(self, payload: dict) -> dict:
        self.sent.append(payload)
        reply = {"ok": True, "simulado": True}
        if payload["cmd"] == "estado":
            reply.update(bateria_pct=87, motores="detenidos")
        return reply

    def close(self) -> None:
        pass


class SerialTransport:
    """Línea JSON por puerto serie (Arduino, ESP32, Pico...)."""

    def __init__(self, puerto: str, baudios: int = 115200, espera_seg: float = 2.0, **_):
        self.port, self.baud, self.timeout = puerto, baudios, espera_seg
        self._conn = None

    def _open(self):
        if self._conn is None:
            try:
                import serial
            except ImportError as exc:
                raise TransportError("Falta pyserial: pip install 'tars-local[robots]'") from exc
            try:
                self._conn = serial.Serial(self.port, self.baud, timeout=self.timeout)
            except serial.SerialException as exc:
                raise TransportError(f"No pude abrir {self.port}: {exc}") from exc
        return self._conn

    def send(self, payload: dict) -> dict:
        conn = self._open()
        try:
            conn.reset_input_buffer()
            conn.write((json.dumps(payload, ensure_ascii=False) + "\n").encode())
            conn.flush()
            line = conn.readline().decode(errors="replace").strip()
        except OSError as exc:
            self.close()
            raise TransportError(f"Fallo en el puerto {self.port}: {exc}") from exc
        if not line:
            return {"ok": True, "confirmado": False, "nota": "enviado; el robot no contestó"}
        try:
            reply = json.loads(line)
            return reply if isinstance(reply, dict) else {"ok": True, "respuesta": reply}
        except json.JSONDecodeError:
            return {"ok": True, "respuesta": line}

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            finally:
                self._conn = None


class MqttTransport:
    """Publica el JSON en un tema MQTT de un broker local (p. ej. mosquitto)."""

    def __init__(self, tema: str, broker: str = "127.0.0.1", puerto: int = 1883, **_):
        self.topic, self.broker, self.port = tema, broker, puerto
        self._client = None

    def _open(self):
        if self._client is None:
            try:
                import paho.mqtt.client as mqtt
            except ImportError as exc:
                raise TransportError("Falta paho-mqtt: pip install 'tars-local[robots]'") from exc
            try:  # paho-mqtt 2.x
                client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
            except AttributeError:  # paho-mqtt 1.x
                client = mqtt.Client()
            try:
                client.connect(self.broker, self.port, keepalive=30)
            except OSError as exc:
                raise TransportError(f"No pude conectar al broker {self.broker}: {exc}") from exc
            client.loop_start()
            self._client = client
        return self._client

    def send(self, payload: dict) -> dict:
        info = self._open().publish(self.topic, json.dumps(payload, ensure_ascii=False), qos=1)
        try:
            info.wait_for_publish(timeout=3)
        except (RuntimeError, ValueError) as exc:
            raise TransportError(f"No pude publicar en {self.topic}: {exc}") from exc
        if not info.is_published():
            raise TransportError(f"El broker no confirmó la publicación en {self.topic}")
        return {"ok": True, "confirmado": False, "nota": "publicado en MQTT"}

    def close(self) -> None:
        if self._client is not None:
            self._client.loop_stop()
            self._client.disconnect()
            self._client = None


class HttpTransport:
    """POST del JSON a un robot con servidor HTTP en la red local."""

    def __init__(self, url: str, espera_seg: float = 3.0, **_):
        self.url, self.timeout = url, espera_seg
        # Sin proxy: los robots están en la red local.
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def send(self, payload: dict) -> dict:
        req = urllib.request.Request(
            self.url,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        try:
            with self._opener.open(req, timeout=self.timeout) as resp:
                body = resp.read().decode(errors="replace").strip()
        except OSError as exc:
            raise TransportError(f"El robot en {self.url} no responde: {exc}") from exc
        try:
            reply = json.loads(body) if body else {"ok": True}
            return reply if isinstance(reply, dict) else {"ok": True, "respuesta": reply}
        except json.JSONDecodeError:
            return {"ok": True, "respuesta": body}

    def close(self) -> None:
        pass


TRANSPORTS = {
    "sim": SimTransport,
    "serial": SerialTransport,
    "mqtt": MqttTransport,
    "http": HttpTransport,
}


def make_transport(kind: str, options: dict):
    try:
        cls = TRANSPORTS[kind]
    except KeyError:
        raise TransportError(f"Transporte desconocido '{kind}'. Opciones: {', '.join(TRANSPORTS)}") from None
    try:
        return cls(**options)
    except TypeError as exc:
        raise TransportError(f"Configuración incompleta para el transporte '{kind}': {exc}") from exc
