import json
import locale
import os
import time
from pathlib import Path


DEFAULT_PIPE = r"\\.\pipe\sylphie-hw"


def robust_decode_bytes(value):
    candidates = ["utf-8", "utf-8-sig", locale.getpreferredencoding(False), "cp1252", "latin-1"]
    tried = []
    for encoding in candidates:
        if not encoding:
            continue
        normalized = encoding.lower()
        if normalized in tried:
            continue
        tried.append(normalized)
        try:
            return value.decode(encoding), encoding, normalized not in ("utf-8", "utf8", "utf-8-sig"), False
        except (UnicodeDecodeError, LookupError):
            continue
    return value.decode("utf-8", errors="replace"), "utf-8-replace", True, True


def send_agent_command(payload, pipe_name=None, timeout=5.0):
    pipe = pipe_name or os.environ.get("SYLPHIE_AGENT_PIPE") or DEFAULT_PIPE
    request = json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("utf-8") + b"\n"
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
                        text, encoding_used, fallback_used, replacement_used = robust_decode_bytes(bytes(response))
                        payload = json.loads(text)
                        if isinstance(payload, dict):
                            payload["_pipe_encoding_used"] = encoding_used
                            if replacement_used:
                                payload["_pipe_decode_warning"] = "Command output encoding error. Output was decoded with replacement characters."
                            elif fallback_used:
                                payload["_pipe_decode_note"] = "Agent pipe output was decoded with a fallback encoding."
                        return payload
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
