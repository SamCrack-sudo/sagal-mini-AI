#!/usr/bin/env bash
# Instalación en Raspberry Pi OS (64 bits) / Debian / Ubuntu.
# Es el ÚNICO paso que necesita internet: descarga Ollama, el modelo de
# lenguaje, el modelo de voz y la voz de Piper. Después todo funciona offline.
set -euo pipefail
cd "$(dirname "$0")/.."

ram_gb=$(awk '/MemTotal/ {printf "%d", $2/1024/1024 + 0.5}' /proc/meminfo)
if [ "$ram_gb" -lt 6 ]; then modelo="qwen2.5:1.5b"; else modelo="llama3.2:3b"; fi
modelo="${TARS_MODELO:-$modelo}"
echo "==> RAM: ${ram_gb} GB -> modelo de lenguaje: $modelo"

echo "==> Paquetes del sistema (audio)"
sudo apt-get update
sudo apt-get install -y python3-venv libportaudio2 espeak-ng curl

if ! command -v ollama >/dev/null; then
  echo "==> Instalando Ollama"
  curl -fsSL https://ollama.com/install.sh | sh
fi
echo "==> Descargando $modelo"
ollama pull "$modelo"

echo "==> Entorno de Python"
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -e '.[voz,robots]'

echo "==> Voz de Piper (es_MX)"
mkdir -p voces
base="https://huggingface.co/rhasspy/piper-voices/resolve/main/es/es_MX/claude/high"
for f in es_MX-claude-high.onnx es_MX-claude-high.onnx.json; do
  [ -s "voces/$f" ] || curl -fL -o "voces/$f" "$base/$f"
done

echo "==> Modelo de reconocimiento de voz (faster-whisper)"
stt=$(.venv/bin/python -c "from tars.config import load_config; print(load_config()['voz']['stt_modelo'])")
.venv/bin/python -c "from faster_whisper import WhisperModel; WhisperModel('$stt', device='cpu', compute_type='int8')"

if ! grep -q "modelo = \"$modelo\"" config.toml; then
  echo "AVISO: pon  modelo = \"$modelo\"  en la sección [llm] de config.toml"
fi
echo "Listo. Comprueba con:  .venv/bin/tars --check"
echo "Texto:  .venv/bin/tars        Voz:  .venv/bin/tars --voz"
