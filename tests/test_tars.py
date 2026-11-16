import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from tars.brain import Brain, is_stop, parse_setting
from tars.config import load_config
from tars.llm import LLMError, OllamaClient
from tars.robots import Fleet

ROBOTS = load_config(str(Path(__file__).parent.parent / "config.toml"))["robots"]


class FakeLLM:
    """Devuelve respuestas guionizadas y guarda lo que se le pidió."""

    model = "fake"

    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []

    def chat(self, messages, tools=None, on_token=None):
        self.calls.append(messages)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        reply = {"content": "", "tool_calls": [], **reply}
        if reply["content"] and on_token:
            for word in reply["content"].split(" "):
                on_token(word + " ")
        return reply


def tool_call(**arguments):
    return {"tool_calls": [{"function": {"name": "comando_robot", "arguments": arguments}}]}


class FleetTest(unittest.TestCase):
    def setUp(self):
        self.fleet = Fleet(ROBOTS)

    def test_valid_command_reaches_transport(self):
        result = self.fleet.execute("rover", "avanzar", {"distancia_cm": 50})
        self.assertTrue(result["ok"])
        sent = self.fleet.robots["rover"].transport.sent
        self.assertEqual(sent, [{"id": 1, "cmd": "avanzar", "args": {"distancia_cm": 50}}])

    def test_tolerates_strings_case_and_accents(self):
        result = self.fleet.execute("Rover", "AVANZAR", {"distancia_cm": "120"})
        self.assertEqual(result["argumentos"], {"distancia_cm": 120})
        result = self.fleet.execute("brazo", "mover", {"articulación": "Codo", "angulo": 90})
        self.assertEqual(result["argumentos"], {"articulacion": "codo", "angulo": 90})

    def test_rejections_send_nothing(self):
        cases = [
            ("rover", "avanzar", {"distancia_cm": 5000}),  # fuera de rango
            ("rover", "avanzar", {}),  # falta argumento
            ("rover", "avanzar", {"distancia_cm": "mucho"}),
            ("rover", "avanzar", {"distancia_cm": float("nan")}),
            ("rover", "avanzar", {"distancia_cm": 10, "turbo": True}),  # argumento inventado
            ("rover", "despegar", {}),  # comando inventado
            ("dron", "avanzar", {"distancia_cm": 10}),  # robot inventado
            ("brazo", "pinza", {"accion": "aplastar"}),
        ]
        for robot, command, args in cases:
            with self.subTest(command=command, args=args):
                result = self.fleet.execute(robot, command, args)
                self.assertFalse(result["ok"])
                self.assertIn("error", result)
        for robot in self.fleet.robots.values():
            self.assertEqual(robot.transport.sent, [])

    def test_stop_all(self):
        results = self.fleet.stop_all()
        self.assertEqual(set(results), {"rover", "brazo"})
        self.assertTrue(all(r["ok"] for r in results.values()))


class FastPathTest(unittest.TestCase):
    def test_stop_phrases(self):
        for text in ["para", "¡Alto!", "TARS, detente ya", "paren todos", "stop", "parada de emergencia", "¡Emergencia, el rover se cae!"]:
            self.assertTrue(is_stop(text), text)

    def test_not_stop(self):
        for text in ["¿para qué sirve el rover?", "avanza y luego para", "qué tan alto es el brazo", "prepara el rover"]:
            self.assertFalse(is_stop(text), text)

    def test_settings(self):
        self.assertEqual(parse_setting("Pon el humor al 60%"), ("humor", 60))
        self.assertEqual(parse_setting("sinceridad a 100"), ("honestidad", 100))
        self.assertIsNone(parse_setting("¿cuál es tu nivel de humor?"))


class BrainTest(unittest.TestCase):
    def make(self, *replies, **kwargs):
        self.llm = FakeLLM(*replies)
        self.fleet = Fleet(ROBOTS)
        return Brain(self.llm, self.fleet, **kwargs)

    def test_stop_bypasses_llm(self):
        brain = self.make()
        reply = brain.handle("¡Para!")
        self.assertIn("rover", reply)
        self.assertEqual(self.llm.calls, [])
        self.assertEqual(self.fleet.robots["rover"].transport.sent[0]["cmd"], "parar")
        self.assertEqual(self.fleet.robots["brazo"].transport.sent[0]["cmd"], "parar")

    def test_setting_changes_prompt_and_persists(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state.json"
            brain = self.make({"content": "Hecho."}, state_path=state)
            brain.handle("humor al 10")
            brain.handle("hola")
            self.assertIn("humor 10%", self.llm.calls[0][0]["content"])
            self.assertEqual(Brain(FakeLLM(), Fleet(ROBOTS), state_path=state).personality.humor, 10)

    def test_tool_call_executes_and_result_goes_back(self):
        brain = self.make(
            tool_call(robot="rover", comando="avanzar", argumentos={"distancia_cm": 50}),
            {"content": "Rover avanzando medio metro."},
        )
        tokens = []
        reply = brain.handle("avanza medio metro", tokens.append)
        self.assertEqual(reply, "Rover avanzando medio metro.")
        self.assertEqual("".join(tokens).strip(), reply)
        self.assertEqual(self.fleet.robots["rover"].transport.sent[0]["args"], {"distancia_cm": 50})
        tool_message = self.llm.calls[1][-1]
        self.assertEqual(tool_message["role"], "tool")
        self.assertTrue(json.loads(tool_message["content"])["ok"])

    def test_invalid_tool_call_reports_error_to_model(self):
        brain = self.make(
            tool_call(robot="rover", comando="avanzar", argumentos={"distancia_cm": 9999}),
            {"content": "No puedo: el máximo son 300 centímetros."},
        )
        brain.handle("avanza cien metros")
        self.assertEqual(self.fleet.robots["rover"].transport.sent, [])
        error = json.loads(self.llm.calls[1][-1]["content"])
        self.assertFalse(error["ok"])
        self.assertIn("máximo", error["error"])

    def test_flattened_arguments(self):
        brain = self.make(tool_call(robot="rover", comando="girar", grados=90), {"content": "Girado."})
        brain.handle("gira a la derecha")
        self.assertEqual(self.fleet.robots["rover"].transport.sent[0]["args"], {"grados": 90})

    def test_inline_json_tool_call_is_not_shown(self):
        inline = json.dumps({"name": "comando_robot", "parameters": {"robot": "brazo", "comando": "pinza", "argumentos": {"accion": "abrir"}}})
        brain = self.make({"content": inline}, {"content": "Pinza abierta."})
        tokens = []
        brain.handle("abre la pinza", tokens.append)
        self.assertEqual("".join(tokens).strip(), "Pinza abierta.")
        self.assertEqual(self.fleet.robots["brazo"].transport.sent[0]["cmd"], "pinza")

    def test_tool_loop_is_bounded(self):
        looping = tool_call(robot="rover", comando="estado")
        brain = self.make(*[looping] * 10)
        reply = brain.handle("estado")
        self.assertIn("bucle", reply)
        self.assertEqual(len(self.llm.calls), 4)

    def test_llm_down_is_reported_and_stop_still_works(self):
        brain = self.make(LLMError("No puedo conectar con Ollama"))
        self.assertIn("no responde", brain.handle("hola"))
        self.assertEqual(brain.history, [])
        self.assertIn("Parada enviada", brain.handle("alto"))

    def test_history_is_trimmed_to_a_user_turn(self):
        brain = self.make(*[{"content": "ok"}] * 20, max_history=5)
        for i in range(20):
            brain.handle(f"mensaje {i}")
        self.assertLessEqual(len(brain.history), 5)
        self.assertEqual(brain.history[0]["role"], "user")


class FakeOllama(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if body["model"] == "ausente":
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b'{"error":"model not found"}')
            return
        self.send_response(200)
        self.end_headers()
        chunks = [
            {"message": {"role": "assistant", "content": "Hola, "}, "done": False},
            {"message": {"role": "assistant", "content": "Cooper."}, "done": False},
            {"message": {"content": "", "tool_calls": [{"function": {"name": "x", "arguments": {}}}]}, "done": True},
        ]
        for chunk in chunks:
            self.wfile.write(json.dumps(chunk).encode() + b"\n")

    def log_message(self, *_):
        pass


class OllamaClientTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), FakeOllama)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.host = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def test_streaming(self):
        tokens = []
        result = OllamaClient(self.host, "m").chat([], on_token=tokens.append)
        self.assertEqual(tokens, ["Hola, ", "Cooper."])
        self.assertEqual(result["content"], "Hola, Cooper.")
        self.assertEqual(len(result["tool_calls"]), 1)

    def test_missing_model(self):
        with self.assertRaisesRegex(LLMError, "ollama pull ausente"):
            OllamaClient(self.host, "ausente").chat([])

    def test_server_down(self):
        with self.assertRaisesRegex(LLMError, "No puedo conectar"):
            OllamaClient("http://127.0.0.1:9", "m").chat([])


if __name__ == "__main__":
    unittest.main()
