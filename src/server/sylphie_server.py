from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import urlparse


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
COMMAND_TIMEOUT_SECONDS = 5
RGB_RE = re.compile(r"^[0-9A-Fa-f]{6}$")
SCENE_RE = re.compile(r"^[A-Za-z0-9_-]+$")


class SylphieServer:
    def __init__(self, exe_path):
        self.exe_path = Path(exe_path)

    def exe_exists(self):
        return self.exe_path.is_file()

    def command_base(self):
        return [str(self.exe_path)]

    def run_backend(self, args):
        command = self.command_base() + args
        result = {
            "ok": False,
            "command": command,
            "stdout": "",
            "stderr": "",
            "exit_code": None,
        }

        if not self.exe_exists():
            result["stderr"] = "sylphie_rgb.exe not found: " + str(self.exe_path)
            return result

        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=COMMAND_TIMEOUT_SECONDS,
                shell=False,
            )
        except subprocess.TimeoutExpired as exc:
            result["stderr"] = "command timed out after 5 seconds"
            result["stdout"] = ensure_text(exc.stdout)
            result["exit_code"] = None
            return result
        except OSError as exc:
            result["stderr"] = str(exc)
            return result

        result["stdout"] = completed.stdout
        result["stderr"] = completed.stderr
        result["exit_code"] = completed.returncode
        result["ok"] = completed.returncode == 0
        return result


def ensure_text(value):
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


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
                self.send_json(
                    200,
                    {
                        "ok": server_state.exe_exists() and doctor["ok"],
                        "exe": str(server_state.exe_path),
                        "doctor": doctor,
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
                    result = server_state.run_backend(["set", rgb])
                elif path == "/api/scene":
                    name = validate_scene_name(body.get("name"))
                    result = server_state.run_backend(["scene", name])
                elif path == "/api/off":
                    result = server_state.run_backend(["off"])
                else:
                    self.send_json(404, {"ok": False, "error": "not found"})
                    return
            except ValueError as exc:
                self.send_json(400, {"ok": False, "error": str(exc)})
                return

            self.send_json(200 if result["ok"] else 500, result)

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
    server_state = SylphieServer(exe_path)

    if args.host != DEFAULT_HOST:
        print("WARNING: binding to non-localhost host %s" % args.host)

    handler = make_handler(server_state)
    httpd = ThreadingHTTPServer((args.host, args.port), handler)
    print("Sylphie server listening on http://%s:%d" % (args.host, args.port))
    print("Using sylphie_rgb.exe: %s" % exe_path)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
