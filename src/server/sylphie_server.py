from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
import uuid
from urllib.parse import urlparse

try:
    from agent_client import send_agent_command
except ImportError:
    send_agent_command = None


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
READ_TIMEOUT_SECONDS = 5
WRITE_TIMEOUT_SECONDS = 8
LOCK_WAIT_SECONDS = 2
RGB_RE = re.compile(r"^[0-9A-Fa-f]{6}$")
SCENE_RE = re.compile(r"^[A-Za-z0-9_-]+$")


class SylphieServer:
    def __init__(self, exe_path, host, port, use_agent=False):
        self.exe_path = Path(exe_path)
        self.host = host
        self.port = port
        self.use_agent = use_agent
        self.start_time = time.time()
        self.hardware_lock = threading.Lock()
        self.state_lock = threading.Lock()
        self.current_command = None
        self.last_command = None
        self.last_result = None
        self.last_rgb = None
        self.last_scene = None

    def exe_exists(self):
        return self.exe_path.is_file()

    def command_base(self):
        return [str(self.exe_path)]

    def run_backend(self, args, timeout_seconds=READ_TIMEOUT_SECONDS):
        if self.use_agent:
            agent_result = self.run_agent_backend(args, timeout_seconds=timeout_seconds)
            if agent_result is not None:
                return agent_result

        command = self.command_base() + args
        start = time.perf_counter()
        result = {
            "ok": False,
            "command": command,
            "stdout": "",
            "stderr": "",
            "exit_code": None,
            "duration_ms": 0,
        }

        if not self.exe_exists():
            result["stderr"] = "sylphie_rgb.exe not found: " + str(self.exe_path)
            result["error"] = result["stderr"]
            return result

        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                shell=False,
            )
        except subprocess.TimeoutExpired as exc:
            result["stderr"] = "command timed out after %d seconds" % timeout_seconds
            result["stdout"] = ensure_text(exc.stdout)
            result["exit_code"] = None
            result["error"] = result["stderr"]
            result["duration_ms"] = elapsed_ms(start)
            return result
        except OSError as exc:
            result["stderr"] = str(exc)
            result["error"] = result["stderr"]
            result["duration_ms"] = elapsed_ms(start)
            return result

        result["stdout"] = completed.stdout
        result["stderr"] = completed.stderr
        result["exit_code"] = completed.returncode
        result["ok"] = completed.returncode == 0
        result["duration_ms"] = elapsed_ms(start)
        if not result["ok"]:
            result["error"] = result["stderr"] or result["stdout"] or "backend command failed"
        return result

    def run_agent_backend(self, args, timeout_seconds=READ_TIMEOUT_SECONDS):
        if send_agent_command is None:
            return {
                "ok": False,
                "command": ["agent"] + args,
                "stdout": "",
                "stderr": "agent_client.py could not be imported",
                "exit_code": 1,
                "duration_ms": 0,
                "error": "agent_client.py could not be imported",
            }

        payload = cli_args_to_agent_payload(args)
        if payload is None:
            return None

        start = time.perf_counter()
        command = ["agent"] + args
        result = {
            "ok": False,
            "command": command,
            "stdout": "",
            "stderr": "",
            "exit_code": None,
            "duration_ms": 0,
        }

        try:
            response = send_agent_command(payload, timeout=timeout_seconds)
        except Exception as exc:
            result["stderr"] = str(exc)
            result["error"] = result["stderr"]
            result["exit_code"] = 1
            result["duration_ms"] = elapsed_ms(start)
            return result

        result["ok"] = bool(response.get("ok"))
        result["stdout"] = json.dumps(response, indent=2)
        result["stderr"] = "" if result["ok"] else str(response.get("error") or "")
        result["exit_code"] = 0 if result["ok"] else 1
        result["duration_ms"] = elapsed_ms(start)
        if not result["ok"]:
            result["error"] = response.get("error") or "agent command failed"
        return result

    def takeover_check(self):
        return self.run_backend(["takeover-check"], timeout_seconds=READ_TIMEOUT_SECONDS)

    def controller_conflict_response(self, takeover):
        exit_code = takeover.get("exit_code")
        if exit_code == 0:
            return None

        if exit_code in (10, 11):
            return (
                409,
                {
                    "ok": False,
                    "error": "controller conflict detected",
                    "suggestion": "Run takeover first",
                    "details": takeover,
                    "applied": False,
                },
            )

        return (
            500,
            {
                "ok": False,
                "error": "controller ownership check failed",
                "details": takeover,
                "applied": False,
            },
        )

    def run_hardware_command(self, args, rgb=None, scene=None, check_takeover=True):
        command = self.command_base() + args
        acquired = self.hardware_lock.acquire(timeout=LOCK_WAIT_SECONDS)
        if not acquired:
            return (
                409,
                {
                    "ok": False,
                    "error": "hardware busy",
                    "command": command,
                    "exit_code": None,
                    "stdout": "",
                    "stderr": "",
                    "duration_ms": 0,
                    "applied": False,
                },
            )

        try:
            with self.state_lock:
                self.current_command = command

            if check_takeover:
                takeover = self.takeover_check()
                conflict = self.controller_conflict_response(takeover)
                if conflict is not None:
                    with self.state_lock:
                        self.current_command = None
                        self.last_command = command
                        self.last_result = conflict[1]
                    return conflict

            result = self.run_backend(args, timeout_seconds=WRITE_TIMEOUT_SECONDS)
            result["applied"] = result["ok"] and result["exit_code"] == 0
            if not result["ok"] and "error" not in result:
                result["error"] = result["stderr"] or result["stdout"] or "backend command failed"

            with self.state_lock:
                self.current_command = None
                self.last_command = command
                self.last_result = result
                if result["applied"]:
                    if rgb is not None:
                        self.last_rgb = rgb
                        self.last_scene = None
                    if scene is not None:
                        self.last_scene = scene
                    if scene == "off":
                        self.last_rgb = "000000"

            return (200 if result["ok"] else 500, result)
        finally:
            with self.state_lock:
                if self.current_command == command:
                    self.current_command = None
            self.hardware_lock.release()

    def state(self):
        with self.state_lock:
            return {
                "ok": True,
                "running": self.current_command is not None,
                "current_command": command_to_text(self.current_command),
                "last_command": command_to_text(self.last_command),
                "last_result": self.last_result,
                "last_rgb": self.last_rgb,
                "last_scene": self.last_scene,
                "server_pid": os.getpid(),
                "exe": str(self.exe_path),
            }

    def debug_config(self, static_dir):
        state = self.state()
        return {
            "ok": True,
            "host": self.host,
            "port": self.port,
            "exe": str(self.exe_path),
            "use_agent": self.use_agent,
            "static_dir": str(static_dir),
            "working_directory": os.getcwd(),
            "server_pid": os.getpid(),
            "python_version": sys.version,
            "running": state["running"],
            "current_command": state["current_command"],
        }


def command_to_text(command):
    if not command:
        return None
    return " ".join(str(part) for part in command)


def ensure_text(value):
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def elapsed_ms(start):
    return int((time.perf_counter() - start) * 1000)


def cli_args_to_agent_payload(args):
    if not args:
        return None

    payload = {"id": str(uuid.uuid4())}
    command = args[0]
    if command in ("doctor", "off", "recover"):
        if len(args) != 1:
            return None
        payload["cmd"] = command
        return payload
    if command == "takeover-check":
        if len(args) != 1:
            return None
        payload["cmd"] = "takeover_check"
        return payload
    if command == "bus-status":
        if len(args) != 1:
            return None
        payload["cmd"] = "bus_status"
        return payload
    if command == "set" and len(args) == 2:
        payload["cmd"] = "set"
        payload["rgb"] = args[1]
        return payload
    if command == "scene" and len(args) == 2:
        payload["cmd"] = "scene"
        payload["name"] = args[1]
        return payload
    if command == "recover-set" and len(args) == 2:
        payload["cmd"] = "recover_set"
        payload["rgb"] = args[1]
        return payload
    return None


def file_mtime(path):
    try:
        return Path(path).stat().st_mtime
    except OSError:
        return None


def detect_asus_processes(doctor_output):
    if (
        "no common ASUS/Aura lighting processes detected" in doctor_output
        or "no known controller ownership conflicts detected" in doctor_output
    ):
        return []

    names = [
        "LightingService",
        "ArmouryCrate",
        "ArmouryCrate.Service",
        "ArmouryCrate.UserSessionHelper",
        "ArmourySocketServer",
        "ArmourySwAgent",
        "ArmouryHtmlDebugServer",
        "asus_framework",
        "AsusCertService",
        "Aura",
        "OpenRGB",
        "OpenAuraSDK",
    ]
    found = []
    for line in doctor_output.splitlines():
        for name in names:
            if name.lower() in line.lower() and ("pid=" in line.lower() or "rule=" in line.lower()):
                found.append(name)
    found = sorted(set(found))
    return found


def resolve_exe_path(value):
    if value:
        return Path(value).expanduser().resolve()

    env_value = os.environ.get("SYLPHIE_RGB_EXE")
    if env_value:
        return Path(env_value).expanduser().resolve()

    server_dir = Path(__file__).resolve().parent
    return (server_dir / ".." / ".." / "bin" / "sylphie_rgb.exe").resolve()


def json_bytes(payload):
    return json.dumps(payload, indent=2).encode("utf-8")


def read_json_body(handler):
    length_text = handler.headers.get("Content-Length", "0")
    try:
        length = int(length_text)
    except ValueError:
        raise ValueError("invalid Content-Length")

    if length <= 0:
        return {}
    if length > 4096:
        raise ValueError("request body too large")

    raw = handler.rfile.read(length)
    try:
        return json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("invalid JSON body: " + str(exc))


def normalize_rgb(value):
    if not isinstance(value, str):
        raise ValueError("rgb must be a string")

    rgb = value.strip()
    if rgb.startswith("#"):
        rgb = rgb[1:]
    if not RGB_RE.match(rgb):
        raise ValueError("rgb must be exactly 6 hex characters")
    return rgb.upper()


def validate_scene_name(value):
    if not isinstance(value, str):
        raise ValueError("name must be a string")
    name = value.strip()
    if not SCENE_RE.match(name):
        raise ValueError("name may only contain letters, numbers, hyphen, and underscore")
    return name


def make_handler(server_state):
    static_dir = Path(__file__).resolve().parent / "static"

    class Handler(SimpleHTTPRequestHandler):
        server_version = "SylphieHTTP/0.1"

        def log_message(self, fmt, *args):
            sys.stdout.write("%s - %s\n" % (self.address_string(), fmt % args))

        def send_json(self, status, payload):
            body = json_bytes(payload)
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def send_static_file(self, path):
            if path == "/":
                file_path = static_dir / "index.html"
            elif path.startswith("/static/"):
                relative = path[len("/static/") :]
                file_path = (static_dir / relative).resolve()
                if static_dir.resolve() not in file_path.parents and file_path != static_dir.resolve():
                    self.send_error(403)
                    return
            else:
                self.send_error(404)
                return

            if not file_path.is_file():
                self.send_error(404)
                return

            suffix = file_path.suffix.lower()
            content_type = {
                ".html": "text/html; charset=utf-8",
                ".js": "application/javascript; charset=utf-8",
                ".css": "text/css; charset=utf-8",
            }.get(suffix, "application/octet-stream")

            body = file_path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = urlparse(self.path).path
            if path == "/api/health":
                doctor = server_state.run_backend(["doctor"])
                takeover = server_state.run_backend(["takeover-check"])
                bus_status = server_state.run_backend(["bus-status"])
                doctor_output = (doctor.get("stdout") or "") + "\n" + (doctor.get("stderr") or "")
                takeover_output = (takeover.get("stdout") or "") + "\n" + (takeover.get("stderr") or "")
                conflicts = sorted(set(detect_asus_processes(doctor_output) + detect_asus_processes(takeover_output)))
                self.send_json(
                    200,
                    {
                        "ok": server_state.exe_exists() and doctor["ok"],
                        "server_pid": os.getpid(),
                        "server_start_time": server_state.start_time,
                        "exe": str(server_state.exe_path),
                        "use_agent": server_state.use_agent,
                        "exe_exists": server_state.exe_exists(),
                        "exe_modified_time": file_mtime(server_state.exe_path),
                        "doctor": doctor,
                        "takeover_check": takeover,
                        "bus_status": bus_status,
                        "conflicting_processes": conflicts,
                        "asus_processes": conflicts,
                    },
                )
                return

            if path == "/api/scenes":
                scenes = server_state.run_backend(["scenes"])
                self.send_json(
                    200 if scenes["ok"] else 500,
                    {
                        "ok": scenes["ok"],
                        "raw": scenes["stdout"],
                        "stderr": scenes["stderr"],
                        "exit_code": scenes["exit_code"],
                    },
                )
                return

            if path == "/api/state":
                self.send_json(200, server_state.state())
                return

            if path == "/api/bus-status":
                bus_status = server_state.run_backend(["bus-status"])
                self.send_json(200 if bus_status["ok"] else 500, bus_status)
                return

            if path == "/api/debug/config":
                self.send_json(200, server_state.debug_config(static_dir))
                return

            if path == "/" or path.startswith("/static/"):
                self.send_static_file(path)
                return

            self.send_json(404, {"ok": False, "error": "not found"})

        def do_POST(self):
            path = urlparse(self.path).path
            try:
                body = read_json_body(self)
            except ValueError as exc:
                self.send_json(400, {"ok": False, "error": str(exc)})
                return

            try:
                if path == "/api/set":
                    rgb = normalize_rgb(body.get("rgb"))
                    status, result = server_state.run_hardware_command(["set", rgb], rgb=rgb)
                elif path == "/api/scene":
                    name = validate_scene_name(body.get("name"))
                    status, result = server_state.run_hardware_command(["scene", name], scene=name)
                elif path == "/api/off":
                    status, result = server_state.run_hardware_command(["off"], rgb="000000", scene="off")
                elif path == "/api/recover":
                    status, result = server_state.run_hardware_command(["recover"], check_takeover=False)
                elif path == "/api/recover-set":
                    rgb = normalize_rgb(body.get("rgb"))
                    status, result = server_state.run_hardware_command(["recover-set", rgb], rgb=rgb, check_takeover=False)
                elif path == "/api/takeover-check":
                    result = server_state.run_backend(["takeover-check"], timeout_seconds=READ_TIMEOUT_SECONDS)
                    status = 200 if result["ok"] or result["exit_code"] in (10, 11) else 500
                elif path == "/api/takeover":
                    execute = bool(body.get("execute", False))
                    include_core = bool(body.get("include_armoury_core", False))
                    accepted = bool(body.get("accept", False))
                    args = ["takeover"]
                    if execute:
                        args.append("--execute")
                        if accepted:
                            args.append("--i-accept-stopping-lighting-services")
                    else:
                        args.append("--dry-run")
                    if include_core:
                        args.append("--include-armoury-core")
                    status, result = server_state.run_hardware_command(args, check_takeover=False)
                elif path == "/api/restore-services":
                    status, result = server_state.run_hardware_command(["restore-services"], check_takeover=False)
                else:
                    self.send_json(404, {"ok": False, "error": "not found"})
                    return
            except ValueError as exc:
                self.send_json(400, {"ok": False, "error": str(exc)})
                return

            self.send_json(status, result)

    return Handler


def parse_args():
    parser = argparse.ArgumentParser(description="Sylphie Home Lab local HTTP API")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", default=DEFAULT_PORT, type=int)
    parser.add_argument("--exe", default=None)
    return parser.parse_args()


def main():
    args = parse_args()
    exe_path = resolve_exe_path(args.exe)
    use_agent = os.environ.get("SYLPHIE_USE_AGENT") == "1"
    server_state = SylphieServer(exe_path, args.host, args.port, use_agent=use_agent)

    if args.host != DEFAULT_HOST:
        print("WARNING: binding to non-localhost host %s" % args.host)

    handler = make_handler(server_state)
    httpd = ThreadingHTTPServer((args.host, args.port), handler)
    print("Sylphie server listening on http://%s:%d" % (args.host, args.port))
    print("Using sylphie_rgb.exe: %s" % exe_path)
    if use_agent:
        print("Using Sylphie hardware agent via named pipe")
    httpd.serve_forever()


if __name__ == "__main__":
    main()
