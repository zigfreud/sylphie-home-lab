import json
import os
import time
from pathlib import Path


DEFAULT_PIPE = r"\\.\pipe\sylphie-hw"


def send_agent_command(payload, pipe_name=None, timeout=5.0):
    pipe = pipe_name or os.environ.get("SYLPHIE_AGENT_PIPE") or DEFAULT_PIPE
    request = json.dumps(payload, separators=(",", ":")).encode("utf-8") + b"\n"
    deadline = time.monotonic() + timeout
    last_error = None

    while time.monotonic() < deadline:
        try:
            with open(Path(pipe), "r+b", buffering=0) as handle:
                handle.write(request)
                response = bytearray()
                while time.monotonic() < deadline:
                    chunk = handle.read(1)
                    if not chunk:
                        break
                    if chunk == b"\n":
                        return json.loads(response.decode("utf-8"))
                    if chunk != b"\r":
                        response.extend(chunk)
                raise TimeoutError("timed out waiting for agent response")
        except FileNotFoundError as exc:
            last_error = exc
            time.sleep(0.1)
        except OSError as exc:
            last_error = exc
            time.sleep(0.1)

    raise TimeoutError("agent pipe unavailable: %s" % last_error)
