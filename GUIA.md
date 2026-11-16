# Guía de TARS, paso a paso

Esta guía supone que nunca has usado nada de esto. Léela en orden: cada parte
se apoya en la anterior.

---

## 1. Qué es, en simple

Es un programa que vive en tu Raspberry Pi o en tu computador. Tú le hablas
(o le escribes), él entiende lo que quieres, y le manda la orden a tu robot.
No necesita internet para funcionar.

Piensa en él como una persona con cuatro partes:

| Parte | Qué hace | Programa que lo hace |
|---|---|---|
| **Oídos** | Convierte tu voz en texto | faster-whisper |
| **Cerebro** | Entiende el texto y decide qué hacer | Un modelo de IA pequeño, que corre dentro de un programa llamado **Ollama** |
| **Boca** | Convierte su respuesta en voz | Piper |
| **Manos** | Le envía la orden al robot por cable o por red | El código de este proyecto |

Yo no "fabriqué" una IA desde cero: eso requiere máquinas enormes. Lo que hice
fue tomar una IA pequeña y gratuita que ya existe, darle la personalidad de
TARS, y construir todo lo que la rodea para que pueda mandar a tus robots de
forma segura.

**Lo más importante de entender:** la IA no mueve el robot directamente. La IA
solo *pide* ("quiero que el rover avance 50 cm"). Antes de enviar nada, el
programa revisa esa petición contra una lista que escribes **tú**. Si la IA
pide algo que no está en tu lista, o un número fuera del rango que permitiste,
no se envía. Así una equivocación de la IA no termina en un robot estrellado.

---

## 2. Qué necesitas

- Una Raspberry Pi 5 **o** un computador con Linux (Ubuntu, Debian o Raspberry
  Pi OS de 64 bits). Si tu computador es Windows o Mac, mira el apartado 9.
- Internet **solo el día de la instalación** (se descargan unos 3 GB).
- Para hablarle: un micrófono USB y un altavoz. Para escribirle: nada más.

---

## 3. Instalación

Abre la **terminal** (la ventana negra donde se escriben comandos). Copia cada
bloque, pégalo y pulsa Enter. Espera a que termine uno antes de pegar el
siguiente.

**Paso 1 — Bajar el proyecto.**

```bash
git clone -b claude/quirky-pasteur-5s4nm5 https://github.com/SamCrack-sudo/sagal-mini-AI.git
```

**Paso 2 — Entrar en la carpeta.**

```bash
cd sagal-mini-AI
```

**Paso 3 — Instalar todo.** Tarda entre 10 y 30 minutos. Te pedirá tu
contraseña una vez.

```bash
./scripts/instalar.sh
```

Al final puede salir una línea que empieza por `AVISO:`. Si sale, haz lo que
dice (el apartado 7 explica cómo editar `config.toml`).

**Paso 4 — Comprobar.**

```bash
.venv/bin/tars --check
```

Debe aparecer `Ollama: OK, modelo '...' disponible` y debajo la lista de
robots. Si en vez de eso sale un error, ve al apartado 8.

> Nota honesta: este instalador lo escribí pero no pude ejecutarlo en una
> Raspberry real. Si se detiene con un error, cópiame el mensaje y lo arreglo.

---

## 4. Primer uso (escribiendo)

```bash
.venv/bin/tars
```

Aparece `tú>`. Escribe algo y pulsa Enter. Prueba, en este orden:

| Escribe esto | Qué debería pasar |
|---|---|
| `hola, quién eres` | Te contesta con su personalidad |
| `avanza el rover 50 centímetros` | Aparece una línea `→ rover.avanzar {"distancia_cm": 50} ✓` y luego te confirma |
| `avanza el rover 100 metros` | Lo rechaza: supera el máximo permitido |
| `abre la pinza del brazo` | `→ brazo.pinza {"accion": "abrir"} ✓` |
| `para` | Detiene todos los robots al instante |
| `pon el humor al 20` | Se vuelve más serio |
| `/robots` | Lista los robots y lo que sabe hacer cada uno |
| `/salir` | Cierra el programa |

La línea que empieza con `→` es **lo que realmente se le envió al robot**. Si
esa línea no aparece, no se envió nada, diga lo que diga TARS. Fíate de la
flecha, no de las palabras.

Por ahora `rover` y `brazo` son **robots de mentira**: sirven para practicar
sin romper nada. En el apartado 6 los cambias por los tuyos.

La primera respuesta tarda más (el modelo se está cargando en memoria). En una
Raspberry Pi 5, cada respuesta tarda varios segundos; es normal.

---

## 5. Hablarle con la voz

Conecta micrófono y altavoz, y:

```bash
.venv/bin/tars --voz
```

1. Pulsa **Enter**.
2. Cuando diga `Escuchando...`, habla.
3. Quédate callado un segundo: así sabe que terminaste.
4. Te contesta por el altavoz.

También puedes escribir la orden en vez de hablar; funciona igual.

---

## 6. Conectar un robot de verdad

Esto tiene dos mitades: decirle a TARS cómo es tu robot, y hacer que tu robot
entienda los mensajes de TARS.

### 6.1. Qué mensaje recibe el robot

Cada orden le llega como **una línea de texto** con este formato (se llama
JSON):

```json
{"id": 7, "cmd": "avanzar", "args": {"distancia_cm": 50}}
```

- `cmd` es el nombre del comando.
- `args` son los datos del comando.
- `id` es un número que va subiendo, para distinguir una orden de otra.

Tu robot lee esa línea, hace lo que dice, y puede contestar con otra línea:

```json
{"id": 7, "ok": true}
```

### 6.2. Ejemplo para Arduino o ESP32 (por cable USB)

Instala la librería **ArduinoJson** desde el gestor de librerías del Arduino
IDE y usa esto como punto de partida. No pude probarlo en una placa, así que
tómalo como base, no como algo garantizado:

```cpp
#include <ArduinoJson.h>

void setup() {
  Serial.begin(115200);
}

void loop() {
  if (!Serial.available()) return;

  String linea = Serial.readStringUntil('\n');
  JsonDocument doc;
  if (deserializeJson(doc, linea)) return;   // línea ilegible: se ignora

  long id = doc["id"] | 0;
  String cmd = doc["cmd"] | "";

  if (cmd == "avanzar") {
    int cm = doc["args"]["distancia_cm"] | 0;
    // ... aquí tu código para mover los motores "cm" centímetros ...
  } else if (cmd == "parar") {
    // ... aquí tu código para detener los motores ...
  }

  Serial.print("{\"id\":");
  Serial.print(id);
  Serial.println(",\"ok\":true}");
}
```

### 6.3. Decirle a TARS cómo es tu robot

Abre el archivo `config.toml` con cualquier editor de texto. Busca el bloque
`[robots.rover]` y cámbialo así:

```toml
[robots.rover]
descripcion = "Mi robot con ruedas"
transporte = "serial"
puerto = "/dev/ttyUSB0"
baudios = 115200
comando_parada = "parar"
```

- `transporte = "serial"` significa "por cable USB". Antes decía `"sim"`
  (simulado).
- `puerto` es dónde está enchufado. Para averiguarlo, conecta el robot y
  ejecuta:

```bash
ls /dev/ttyUSB* /dev/ttyACM*
```

- `baudios` debe ser el mismo número que pusiste en `Serial.begin(...)`.

Otras formas de conectar, si tu robot usa wifi:

| Si tu robot... | Pon esto |
|---|---|
| Tiene una página/servidor web | `transporte = "http"` y `url = "http://192.168.1.50/cmd"` |
| Usa MQTT | `transporte = "mqtt"`, `broker = "127.0.0.1"` y `tema = "robots/rover/cmd"` |

### 6.4. Añadir o cambiar un comando

Cada comando es un bloque así en `config.toml`:

```toml
[robots.rover.comandos.avanzar]
descripcion = "Avanza en línea recta"
parametros = { distancia_cm = { tipo = "numero", min = 1, max = 300 } }
```

Leído en simple: *"el robot `rover` tiene un comando `avanzar`, que necesita un
número llamado `distancia_cm`, entre 1 y 300"*.

- La `descripcion` es lo que lee la IA para saber cuándo usarlo. Escríbela
  clara, como se lo explicarías a una persona.
- `min` y `max` son tu red de seguridad: pon los límites reales de tu robot.

Para un comando nuevo, copia un bloque y cambia los nombres. Ejemplos:

```toml
# Sin datos: solo el nombre
[robots.rover.comandos.luces_encender]
descripcion = "Enciende las luces"

# Con opciones fijas en vez de un número
[robots.rover.comandos.velocidad]
descripcion = "Cambia la velocidad"
parametros = { modo = { tipo = "texto", opciones = ["lento", "normal", "rapido"] } }
```

Y recuerda: el nombre del comando (`luces_encender`) es lo que llegará en
`"cmd"` a tu robot, así que tu Arduino tiene que reconocerlo.

Para un **robot nuevo**, copia todo desde `[robots.rover]` hasta su último
comando, y cambia `rover` por el nombre nuevo en todas las líneas.

Después de cualquier cambio, cierra TARS y vuelve a abrirlo. Comprueba con
`.venv/bin/tars --check` que tu robot aparece en la lista.

---

## 7. Cómo modificar otras cosas

Casi todo se cambia en `config.toml`, sin tocar código.

| Quiero cambiar... | Dónde | Qué tocar |
|---|---|---|
| El nombre (que no se llame TARS) | `config.toml`, sección `[tars]` | `nombre = "..."` |
| El humor o la honestidad de fábrica | `config.toml`, sección `[tars]` | `humor`, `honestidad` (0 a 100) |
| Que hable en otro idioma | `config.toml` | `idioma` en `[tars]` y `stt_idioma` en `[voz]` |
| La IA que usa (más lista o más rápida) | `config.toml`, sección `[llm]` | `modelo = "..."`, y antes descárgala con `ollama pull nombre` |
| Que responda más largo o más corto | `config.toml`, sección `[llm]` | `max_tokens` |
| Que entienda mejor mi voz | `config.toml`, sección `[voz]` | `stt_modelo = "small"` (más preciso, más lento) |
| Cuánto silencio espera antes de dejar de escuchar | `config.toml`, sección `[voz]` | `silencio_seg` |

Estas otras sí requieren abrir un archivo de código, pero son cambios de texto:

| Quiero cambiar... | Archivo | Qué tocar |
|---|---|---|
| **Su personalidad y sus reglas** | `tars/personality.py`, función `system_prompt` (línea 58) | Es un texto en español normal. Lo que escribas ahí es lo que la IA "cree que es". |
| Cómo se comporta según el nivel de humor | `tars/personality.py`, función `_humor_rule` (línea 40) | Las frases entre comillas |
| Las palabras que disparan la parada de emergencia | `tars/brain.py`, línea 17 | Añade palabras separadas por `\|`, en minúsculas y sin tildes |

Si rompes algo, este comando deja un archivo como estaba originalmente (cambia
el nombre del archivo por el que quieras recuperar):

```bash
git checkout config.toml
```

Y este comprueba que el programa sigue funcionando bien después de tus cambios
(debe terminar en `OK`):

```bash
python3 -m unittest
```

### Sobre elegir la IA

| Modelo | RAM que necesita | Cómo es |
|---|---|---|
| `qwen2.5:1.5b` | 4 GB | El más rápido; se equivoca más |
| `llama3.2:3b` | 8 GB | Equilibrado (el que viene por defecto) |
| `qwen2.5:7b` | 16 GB | Bastante más listo; lento en una Raspberry, bien en un computador |

Puedes probar uno sin cambiar la configuración:

```bash
.venv/bin/tars --modelo qwen2.5:1.5b
```

---

## 8. Si algo falla

| Lo que ves | Qué significa | Qué hacer |
|---|---|---|
| `No puedo conectar con Ollama` | El programa de la IA no está encendido | Ejecuta `ollama serve` en otra terminal, o reinicia el equipo |
| `Ollama no tiene el modelo ...` | Falta descargar la IA | Ejecuta el comando `ollama pull ...` que te muestra el mensaje |
| `→ rechazado: ...` | La IA pidió algo que tu lista no permite | Es la protección funcionando. Si la orden era razonable, revisa `min`/`max` o la `descripcion` del comando |
| TARS dice que hizo algo pero no hay línea `→` | La IA se lo inventó | No se envió nada. Repite la orden de forma más directa, o prueba un modelo más grande |
| `No pude abrir /dev/ttyUSB0` | No encuentra el robot en ese puerto | Revisa el cable y el `puerto` (apartado 6.3). Si dice "permission denied": `sudo usermod -aG dialout $USER` y reinicia |
| `No pude abrir el micrófono` | No detecta micrófono | Comprueba que está conectado; prueba otro puerto USB |
| `(no oí nada)` | No captó tu voz | Habla más cerca o más alto, justo después de `Escuchando...` |
| `Sin voz de salida` | Falta la voz de Piper | Vuelve a ejecutar `./scripts/instalar.sh` con internet |
| Responde muy lento | El modelo es grande para tu equipo | Usa `qwen2.5:1.5b` y baja `max_tokens` a 100 |
| `Error de configuración` | Hay un error de escritura en `config.toml` | Revisa comillas, llaves y comas de lo último que cambiaste, o recupéralo con `git checkout config.toml` |

---

## 9. Si tu computador es Windows o Mac

El instalador automático es solo para Linux. A mano, el modo de escribir se
monta así (no lo he probado en esos sistemas):

1. Instala **Ollama** desde ollama.com y **Python 3.11 o superior** desde
   python.org.
2. Descarga el proyecto (paso 1 del apartado 3) y entra en la carpeta.
3. Descarga la IA:

```bash
ollama pull llama3.2:3b
```

4. Arranca:

```bash
python -m tars
```

La voz en Windows o Mac necesita pasos extra; si la quieres, dímelo y la
preparo.

---

## 10. Mapa de archivos

| Archivo | Para qué sirve | ¿Lo tocarás? |
|---|---|---|
| `config.toml` | Tus ajustes y tus robots | **Sí, casi siempre aquí** |
| `tars/personality.py` | El carácter de TARS | A veces |
| `tars/brain.py` | Decide qué hacer con cada frase; parada de emergencia | Rara vez |
| `tars/robots.py` | Revisa que cada orden esté permitida | No |
| `tars/transports.py` | Envía la orden por cable, wifi, etc. | No |
| `tars/llm.py` | Habla con Ollama | No |
| `tars/voice.py` | Micrófono y altavoz | No |
| `tars/cli.py` | La pantalla de chat | No |
| `scripts/instalar.sh` | El instalador | No |
| `tests/` | Pruebas automáticas | No |

---

## 11. Seguridad

- La parada por voz tarda uno o dos segundos. Si tu robot puede hacer daño,
  ponle **un botón físico de apagado**. No dependas de decir "para".
- Pon en `min` y `max` los límites reales de tu robot. Es lo único que impide
  que una equivocación de la IA llegue al motor.
- La primera vez con un robot real, pruébalo levantado del suelo o con los
  motores desconectados, y mira las líneas `→` para ver qué se envía.

---

## 12. Palabras raras

- **Terminal**: la ventana donde se escriben comandos.
- **Modelo**: la IA en sí; un archivo grande que "sabe" lenguaje.
- **Ollama**: el programa que carga el modelo y lo hace funcionar.
- **Local / offline**: que corre en tu equipo, sin internet.
- **JSON**: una forma ordenada de escribir datos como texto, con llaves `{}`.
- **Puerto serie**: la conexión por cable USB con una placa como Arduino.
- **MQTT**: un sistema de mensajes por red muy usado en robótica.
- **config.toml**: el archivo de texto con tus ajustes.
- **`.venv`**: la carpeta donde quedó instalado el programa.
