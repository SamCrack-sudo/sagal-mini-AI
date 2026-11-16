# sagal-mini-AI — TARS local para tus robots

Un asistente con el carácter de TARS (Interstellar) que corre **entero en tu
máquina** —Raspberry Pi 5 o computador—, sin internet, y que traduce lo que le
dices (por texto o por voz) en comandos para tus robots.

```
tú> avanza el rover medio metro y abre la pinza
  → rover.avanzar {"distancia_cm": 50} ✓
  → brazo.pinza {"accion": "abrir"} ✓
TARS> Rover medio metro adelante y pinza abierta. De nada.
tú> para
  → rover.parar {} ✓
  → brazo.parar {} ✓
TARS> Parada enviada a rover, brazo.
tú> pon el humor al 30
TARS> Humor ajustado al 30 por ciento.
```

## Cómo funciona

```
micrófono ─ faster-whisper ─┐                       ┌─ serial (Arduino/ESP32)
                            ├─ cerebro ─ validación ─┼─ MQTT (broker local)
teclado ────────────────────┘     │                 ├─ HTTP (red local)
                                  │                 └─ sim (pruebas)
                    Ollama (modelo pequeño) ── Piper ─ altavoz
```

- **Cerebro** (`tars/brain.py`): dos caminos.
  - *Vía rápida, sin modelo*: "para", "alto", "parada de emergencia" detienen
    todos los robots al instante; "humor al 60" cambia un ajuste. Funcionan
    aunque Ollama esté caído.
  - *Modelo de lenguaje*: todo lo demás va a un modelo pequeño en Ollama, que
    puede pedir comandos mediante una herramienta (`comando_robot`).
- **Validación** (`tars/robots.py`): el modelo nunca toca el hardware. Solo
  puede pedir `(robot, comando, argumentos)` y eso se comprueba contra la lista
  cerrada y los rangos de `config.toml`. Lo que no cuadra se rechaza y no se
  envía nada.
- **Transportes** (`tars/transports.py`): serial, MQTT, HTTP o simulado.

## Instalación

Necesita internet **una sola vez**, para descargar los modelos:

```bash
./scripts/instalar.sh
```

```bash
.venv/bin/tars --check
```

Elige el modelo según la RAM (`qwen2.5:1.5b` con menos de 6 GB, `llama3.2:3b`
con más). Para forzar otro: `TARS_MODELO=gemma3:4b ./scripts/instalar.sh`.

Solo el modo texto, sin voz ni dependencias (basta Python ≥ 3.11 y Ollama):

```bash
ollama pull llama3.2:3b
```

```bash
python3 -m tars
```

## Uso

| Comando | Qué hace |
|---|---|
| `tars` | Chat por texto |
| `tars --voz` | Pulsas Enter, hablas, TARS contesta por el altavoz |
| `tars --una "estado del rover"` | Una frase y termina (útil en scripts) |
| `tars --check` | Comprueba Ollama, el modelo y los robots |
| `tars --modelo qwen2.5:1.5b` | Usa otro modelo sin tocar la configuración |

Dentro del chat: `/robots`, `/estado`, `/reset`, `/salir`.

## Conectar tus robots

Edita `config.toml`. Los dos robots que vienen (`rover`, `brazo`) son
**simulados**: sirven para probar y como plantilla. Para uno real cambia el
transporte y declara sus comandos:

```toml
[robots.rover]
descripcion = "Robot explorador con ruedas"
transporte = "serial"
puerto = "/dev/ttyUSB0"
baudios = 115200
comando_parada = "parar"

[robots.rover.comandos.avanzar]
descripcion = "Avanza en línea recta"
parametros = { distancia_cm = { tipo = "numero", min = 1, max = 300 } }
```

El robot recibe **una línea JSON por comando**:

```json
{"id": 7, "cmd": "avanzar", "args": {"distancia_cm": 50}}
```

y puede contestar (opcional) con otra línea JSON, por ejemplo
`{"id": 7, "ok": true, "bateria_pct": 80}`; TARS te cuenta lo que diga. En
Arduino/ESP32 lo más cómodo para leerlo es la librería ArduinoJson.

Tipos de parámetro: `numero` (con `min`/`max`), `texto` (con `opciones`),
`booleano`; `opcional = true` si puede omitirse.

## Pruebas

```bash
python3 -m unittest
```

## Límites conocidos

- La parada por voz pasa por "Enter → grabar → transcribir": tarda uno o dos
  segundos. **No sustituye a un botón físico de emergencia** en robots que
  puedan hacer daño.
- Un modelo de 1,5–3 mil millones de parámetros se equivoca a veces (elige mal
  un comando o pide un dato que ya le diste). La validación impide que eso
  llegue al robot fuera de rango, pero no que elija un comando válido que no
  querías.
- Por MQTT no se espera confirmación del robot; solo se sabe que el broker
  recibió el mensaje.
