"""Voz local: faster-whisper para escuchar, Piper para hablar.

Las dependencias son opcionales (pip install 'tars-local[voz]') y se importan
al usarlas, para que el modo texto funcione sin ellas.
"""

from __future__ import annotations

import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import wave
from pathlib import Path

RATE = 16000
BLOCK = 480  # 30 ms


class VoiceError(Exception):
    pass


def _need(module: str):
    try:
        return __import__(module)
    except ImportError as exc:
        raise VoiceError(f"Falta '{module}'. Instala la voz con: pip install 'tars-local[voz]'") from exc
    except OSError as exc:  # sounddevice sin PortAudio
        raise VoiceError(f"No pude cargar '{module}': {exc} (sudo apt install libportaudio2)") from exc


class Listener:
    """Graba del micrófono hasta que hay silencio y transcribe en local."""

    def __init__(self, model: str = "base", language: str = "es", silence_sec: float = 1.0, max_sec: float = 15):
        self.np = _need("numpy")
        self.sd = _need("sounddevice")
        whisper = _need("faster_whisper")
        self.language, self.silence_sec, self.max_sec = language, silence_sec, max_sec
        try:
            self.model = whisper.WhisperModel(model, device="cpu", compute_type="int8")
        except Exception as exc:  # modelo sin descargar y sin red, etc.
            raise VoiceError(f"No pude cargar el modelo de voz '{model}': {exc}") from exc

    def _rms(self, block) -> float:
        return float(self.np.sqrt(self.np.mean(block**2)))

    def record(self):
        blocks: queue.Queue = queue.Queue()
        try:
            stream = self.sd.InputStream(
                samplerate=RATE,
                channels=1,
                dtype="float32",
                blocksize=BLOCK,
                callback=lambda data, *_: blocks.put(data[:, 0].copy()),
            )
        except Exception as exc:
            raise VoiceError(f"No pude abrir el micrófono: {exc}") from exc
        per_sec = RATE / BLOCK
        with stream:
            frames = [blocks.get() for _ in range(10)]  # 0,3 s de ruido ambiente
            threshold = max(0.01, 3 * max(self._rms(f) for f in frames))
            spoken, silent = False, 0
            while len(frames) < self.max_sec * per_sec:
                block = blocks.get()
                frames.append(block)
                if self._rms(block) > threshold:
                    spoken, silent = True, 0
                elif spoken:
                    silent += 1
                    if silent >= self.silence_sec * per_sec:
                        break
                elif len(frames) > 6 * per_sec:  # nadie habló
                    break
        return self.np.concatenate(frames) if spoken else None

    def listen(self) -> str:
        audio = self.record()
        if audio is None:
            return ""
        segments, _ = self.model.transcribe(audio, language=self.language, vad_filter=True)
        return " ".join(s.text.strip() for s in segments).strip()


class Speaker:
    """Sintetiza con Piper; si no está, usa espeak-ng; si tampoco, calla."""

    def __init__(self, voice_path: str):
        self.voice = Path(voice_path)
        self.backend = None
        try:
            __import__("piper")
            has_piper = True
        except ImportError:
            has_piper = False
        if has_piper and self.voice.is_file():
            self.backend = "piper"
            self.np = _need("numpy")
            self.sd = _need("sounddevice")
        elif shutil.which("espeak-ng"):
            self.backend = "espeak"

    def why_silent(self) -> str:
        return f"Sin voz de salida: no encuentro Piper con la voz {self.voice} ni espeak-ng."

    def say(self, text: str) -> None:
        text = text.strip()
        if not text or not self.backend:
            return
        if self.backend == "espeak":
            subprocess.run(["espeak-ng", "-v", "es", text], check=False)
            return
        with tempfile.NamedTemporaryFile(suffix=".wav") as tmp:
            done = subprocess.run(
                [sys.executable, "-m", "piper", "-m", str(self.voice), "-f", tmp.name],
                input=text.encode(),
                capture_output=True,
                check=False,
            )
            if done.returncode != 0:
                print(f"[voz] Piper falló: {done.stderr.decode(errors='replace')[-200:]}", file=sys.stderr)
                return
            with wave.open(tmp.name, "rb") as wav:
                rate = wav.getframerate()
                audio = self.np.frombuffer(wav.readframes(wav.getnframes()), dtype=self.np.int16)
        self.sd.play(audio, rate)
        self.sd.wait()


class SentenceSpeaker:
    """Recibe tokens del LLM y va hablando frase a frase en otro hilo, para
    empezar a hablar antes de que el modelo termine de generar."""

    _END = re.compile(r"(?<=[.!?…])\s+")

    def __init__(self, speaker: Speaker):
        self.speaker = speaker
        self.buffer = ""
        self.pending: queue.Queue = queue.Queue()
        threading.Thread(target=self._worker, daemon=True).start()

    def _worker(self) -> None:
        while True:
            sentence = self.pending.get()
            try:
                self.speaker.say(sentence)
            except Exception as exc:  # que un fallo de audio no mate el hilo
                print(f"[voz] {exc}", file=sys.stderr)
            finally:
                self.pending.task_done()

    def feed(self, piece: str) -> None:
        self.buffer += piece
        *complete, self.buffer = self._END.split(self.buffer)
        for sentence in complete:
            self.pending.put(sentence)

    def finish(self) -> None:
        """Dice lo que quede y espera a que termine de hablar."""
        if self.buffer.strip():
            self.pending.put(self.buffer)
        self.buffer = ""
        self.pending.join()
