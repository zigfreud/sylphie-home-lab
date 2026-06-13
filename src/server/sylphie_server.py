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
from urllib.parse import parse_qs, urlparse

try:
    from agent_client import send_agent_command
except ImportError:
    send_agent_command = None


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
DEFAULT_PIPE = r"\\.\pipe\sylphie-hw"
READ_TIMEOUT_SECONDS = 5
WRITE_TIMEOUT_SECONDS = 8
LOCK_WAIT_SECONDS = 2
RGB_RE = re.compile(r"^[0-9A-Fa-f]{6}$")
SCENE_RE = re.compile(r"^[A-Za-z0-9_-]+$")
MARKER_RE = re.compile(r"^[A-Z0-9_ -]{1,64}$")

KNOWN_SERVICES = [
    "LightingService",
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

KNOWN_PROCESSES = [
    "ArmouryCrate",
    "ArmouryCrate.UserSessionHelper",
    "ArmourySocketServer",
    "ArmourySwAgent",
    "ArmouryHtmlDebugServer",
    "asus_framework",
    "AuraWallpaperService",
    "Aura Wallpaper Service",
    "LightingService",
    "Aura",
    "OpenRGB",
    "OpenAuraSDK",
]

AUDIO_REACTIVE_SERVICES = [
    "Audiosrv",
    "AudioEndpointBuilder",
    "LightingService",
    "logi_lamparray_service",
]

AUDIO_REACTIVE_PROCESS_PATTERNS = [
    "Armoury*",
    "LightingService",
    "asus_framework",
    "Realtek*",
    "Nahimic*",
    "Sonic*",
    "Audio*",
    "Logi*",
    "LGHUB*",
]

ARMOURY_HEALTH_SERVICES = [
    "LightingService",
    "AsusCertService",
    "Audiosrv",
    "AudioEndpointBuilder",
    "logi_lamparray_service",
]

ARMOURY_HEALTH_PROCESS_PATTERNS = [
    "ArmouryCrate",
    "ArmouryCrate.UserSessionHelper",
    "ArmourySocketServer",
    "ArmourySwAgent",
    "ArmouryHtmlDebugServer",
    "asus_framework",
    "AuraWallpaperService",
    "Aura Wallpaper Service",
    "logi_download_assistant*",
]

OWNERSHIP_PROCESS_NAMES = [
    "ArmouryCrate",
    "ArmouryCrate.UserSessionHelper",
    "ArmourySocketServer",
    "ArmourySwAgent",
    "ArmouryHtmlDebugServer",
    "asus_framework",
    "LightingService",
    "Aura",
    "OpenRGB",
    "OpenAuraSDK",
]

DEFAULT_CAPTURE_FOCUS_REGISTERS = "8000,8020,80A0,80F1,8022,8023"
STUCK_TRANSITION_FOCUS_REGISTERS = "8020,8021,8022,8023,8025,8027,80A0,80B0,80F1,8101"

SCRIPT_WHITELIST = {
    "start-agent": "scripts/start_agent.ps1",
    "start-agent-now": "scripts/start_agent_now.ps1",
    "stop-agent": "scripts/stop_agent.ps1",
    "status-agent": "scripts/status_agent.ps1",
    "agent-task-control": "scripts/agent_task_control.ps1",
    "start-sylphie": "scripts/start_sylphie.ps1",
    "stop-sylphie": "scripts/stop_sylphie.ps1",
    "return-to-armoury": "scripts/return_to_armoury.ps1",
    "takeover-for-sylphie": "scripts/takeover_for_sylphie.ps1",
    "armoury-action": "scripts/armoury_action.ps1",
}

LOG_WHITELIST = {
    "agent": "logs/agent.log",
    "server": "logs/server.log",
    "commands": "logs/commands.jsonl",
}


class SylphieServer:
    def __init__(self, exe_path, host, port, use_agent=False):
        self.project_root = Path(__file__).resolve().parents[2]
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
        self.capture_lock = threading.Lock()
        self.capture_process = None
        self.capture_type = None
        self.capture_log = None
        self.capture_marker_log = None
        ensure_dir(self.project_root / "logs")

    def exe_exists(self):
        return self.exe_path.is_file()

    def command_base(self):
        return [str(self.exe_path)]

    def log_command(self, event):
        event = dict(event)
        event.setdefault("timestamp", time.time())
        path = self.project_root / "logs" / "commands.jsonl"
        try:
            ensure_dir(path.parent)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event, separators=(",", ":")) + "\n")
        except OSError:
            pass

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
            self.log_command({"kind": "backend", "result": summarize_for_log(result)})
            return result
        except OSError as exc:
            result["stderr"] = str(exc)
            result["error"] = result["stderr"]
            result["duration_ms"] = elapsed_ms(start)
            self.log_command({"kind": "backend", "result": summarize_for_log(result)})
            return result

        result["stdout"] = completed.stdout
        result["stderr"] = completed.stderr
        result["exit_code"] = completed.returncode
        result["ok"] = completed.returncode == 0
        result["duration_ms"] = elapsed_ms(start)
        if not result["ok"]:
            result["error"] = result["stderr"] or result["stdout"] or "backend command failed"
        self.log_command({"kind": "backend", "result": summarize_for_log(result)})
        return result

    def run_agent_backend(self, args, timeout_seconds=READ_TIMEOUT_SECONDS):
        payload = cli_args_to_agent_payload(args)
        if payload is None:
            return None
        return self.run_agent_payload(payload, timeout_seconds=timeout_seconds, command=["agent"] + args)

    def run_agent_payload(self, payload, timeout_seconds=READ_TIMEOUT_SECONDS, command=None):
        command = command or ["agent", payload.get("cmd")]
        start = time.perf_counter()
        result = {
            "ok": False,
            "command": command,
            "stdout": "",
            "stderr": "",
            "exit_code": None,
            "duration_ms": 0,
            "response": None,
        }
        if send_agent_command is None:
            result["stderr"] = "agent_client.py could not be imported"
            result["error"] = result["stderr"]
            result["exit_code"] = 1
            return result

        try:
            response = send_agent_command(payload, timeout=timeout_seconds)
        except Exception as exc:
            result["stderr"] = str(exc)
            result["error"] = result["stderr"]
            result["exit_code"] = 1
            result["duration_ms"] = elapsed_ms(start)
            self.log_command({"kind": "agent", "result": summarize_for_log(result)})
            return result

        result["response"] = response
        result["ok"] = bool(response.get("ok"))
        result["stdout"] = json.dumps(response, indent=2)
        result["stderr"] = "" if result["ok"] else str(response.get("error") or "")
        result["exit_code"] = 0 if result["ok"] else 1
        result["duration_ms"] = elapsed_ms(start)
        if not result["ok"]:
            result["error"] = response.get("error") or "agent command failed"
        self.log_command({"kind": "agent", "result": summarize_for_log(result)})
        return result

    def takeover_check(self):
        return self.run_backend(["takeover-check"], timeout_seconds=READ_TIMEOUT_SECONDS)

    def controller_conflict_response(self, takeover):
        if takeover.get("response"):
            state = takeover["response"].get("state") or {}
            blockers = state.get("blocking_conflicts") or []
            if not blockers:
                if takeover.get("ok"):
                    return None
            if blockers:
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
            if takeover.get("response", {}).get("cmd") == "takeover_check" and takeover.get("response", {}).get("error"):
                return (
                    500,
                    {
                        "ok": False,
                        "error": "controller ownership check failed",
                        "details": takeover,
                        "applied": False,
                    },
                )

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
        command = (["agent"] + args) if self.use_agent else (self.command_base() + args)
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

            ownership = self.ownership_status()
            if ownership.get("mode") != "sylphie":
                result = {
                    "ok": False,
                    "error": "RGB writes are blocked unless Current owner is Sylphie",
                    "ownership": ownership,
                    "command": command,
                    "exit_code": None,
                    "stdout": "",
                    "stderr": "",
                    "duration_ms": 0,
                    "applied": False,
                }
                with self.state_lock:
                    self.current_command = None
                    self.last_command = command
                    self.last_result = result
                return 409, result

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

    def run_lifecycle_script(self, script_key, extra_args=None, timeout_seconds=15):
        rel = SCRIPT_WHITELIST[script_key]
        script = (self.project_root / rel).resolve()
        command = [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
        ] + list(extra_args or [])
        start = time.perf_counter()
        result = {"ok": False, "command": command, "stdout": "", "stderr": "", "exit_code": None, "duration_ms": 0}
        try:
            completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout_seconds, shell=False)
        except subprocess.TimeoutExpired as exc:
            result["stdout"] = ensure_text(exc.stdout)
            result["stderr"] = "script timed out after %d seconds" % timeout_seconds
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
            result["error"] = result["stderr"] or result["stdout"] or "script failed"
        self.log_command({"kind": "lifecycle", "result": summarize_for_log(result)})
        return result

    def run_elevated_lifecycle_script(self, script_key, extra_args=None, timeout_seconds=8, kind="elevated-lifecycle"):
        rel = SCRIPT_WHITELIST[script_key]
        script = (self.project_root / rel).resolve()
        script_args = [
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
        ] + list(extra_args or [])
        command = elevated_powershell_command(self.project_root, script_args)
        start = time.perf_counter()
        try:
            completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout_seconds, shell=False)
        except subprocess.TimeoutExpired as exc:
            return {
                "ok": False,
                "error": "timed out while launching elevated script",
                "stdout": ensure_text(exc.stdout),
                "stderr": ensure_text(exc.stderr),
                "command": command,
                "duration_ms": elapsed_ms(start),
            }
        except OSError as exc:
            return {"ok": False, "error": str(exc), "command": command, "duration_ms": elapsed_ms(start)}

        result = {
            "ok": completed.returncode == 0,
            "command": command,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "exit_code": completed.returncode,
            "duration_ms": elapsed_ms(start),
            "message": "Elevated script requested. Re-run status after UAC/action completes.",
        }
        if not result["ok"]:
            result["error"] = result["stderr"] or result["stdout"] or "elevated script launch failed"
        self.log_command({"kind": kind, "result": summarize_for_log(result)})
        return result

    def run_json_lifecycle_script(self, script_key, extra_args=None, timeout_seconds=10):
        result = self.run_lifecycle_script(script_key, extra_args=extra_args, timeout_seconds=timeout_seconds)
        if not result.get("ok"):
            return result
        try:
            parsed = json.loads(result.get("stdout") or "{}")
        except json.JSONDecodeError as exc:
            result["ok"] = False
            result["error"] = "script JSON parse failed: " + str(exc)
            return result
        parsed["script"] = summarize_for_log(result)
        return parsed

    def lifecycle_status(self):
        result = self.run_lifecycle_script("status-agent", timeout_seconds=8)
        result["agent_ping"] = self.run_agent_payload({"id": str(uuid.uuid4()), "cmd": "ping"}, timeout_seconds=2, command=["agent", "ping"])
        return result

    def agent_task_status(self):
        return self.run_json_lifecycle_script("agent-task-control", ["-Action", "status"], timeout_seconds=10)

    def run_agent_task_action(self, action, enable_autostart=False, stop_agent=False):
        args = ["-Action", action]
        if enable_autostart:
            args.append("-EnableAutostart")
        if stop_agent:
            args.append("-StopAgent")
        return self.run_elevated_lifecycle_script("agent-task-control", args, kind="agent-task-control")

    def ownership_status(self):
        with self.capture_lock:
            capture_running = self.capture_process is not None and self.capture_process.poll() is None
        agent_status = self.run_agent_payload({"id": str(uuid.uuid4()), "cmd": "status"}, timeout_seconds=2, command=["agent", "status"])
        task_status = self.agent_task_status()
        probe = ownership_probe_snapshot()
        mode, reasons = derive_ownership_mode(capture_running, agent_status, probe)
        return {
            "ok": probe.get("ok", False),
            "mode": mode,
            "owner": mode,
            "reasons": reasons,
            "write_allowed": mode == "sylphie",
            "capture_running": capture_running,
            "agent_status": agent_status,
            "agent_task": task_status,
            "probe": probe,
        }

    def run_ownership_action(self, action, disable_autostart=False, launch_armoury=False):
        if action == "return-to-armoury":
            args = []
            if disable_autostart:
                args.append("-DisableAutostart")
            if launch_armoury:
                args.append("-LaunchArmoury")
            return self.run_elevated_lifecycle_script("return-to-armoury", args, kind="ownership-return-to-armoury")
        if action == "takeover-for-sylphie":
            return self.run_elevated_lifecycle_script("takeover-for-sylphie", [], kind="ownership-takeover-for-sylphie")
        return {"ok": False, "error": "unknown ownership action"}

    def armoury_health(self):
        return armoury_health_snapshot()

    def run_armoury_action(self, action):
        return self.run_elevated_lifecycle_script("armoury-action", ["-Action", action], kind="armoury-action")

    def audio_reactive_health(self):
        return audio_reactive_health_snapshot()

    def run_audio_reactive_action(self, action):
        script = audio_reactive_action_script(action, self.project_root)
        if script is None:
            return 400, {"ok": False, "error": "unknown audio/reactive action"}

        log_path = self.project_root / "logs" / "audio_reactive_actions.log"
        ensure_dir(log_path.parent)
        command = elevated_powershell_command(
            self.project_root,
            ["-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        )
        start = time.perf_counter()
        try:
            completed = subprocess.run(command, capture_output=True, text=True, timeout=8, shell=False)
        except subprocess.TimeoutExpired as exc:
            return 500, {
                "ok": False,
                "error": "timed out while launching elevated audio/reactive action",
                "stdout": ensure_text(exc.stdout),
                "stderr": ensure_text(exc.stderr),
                "command": command,
            }
        except OSError as exc:
            return 500, {"ok": False, "error": str(exc), "command": command}

        result = {
            "ok": completed.returncode == 0,
            "action": action,
            "command": command,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "exit_code": completed.returncode,
            "duration_ms": elapsed_ms(start),
            "log": str(log_path),
            "message": "Elevated audio/reactive action requested. Re-run health after UAC/action completes.",
        }
        if not result["ok"]:
            result["error"] = result["stderr"] or result["stdout"] or "audio/reactive action launch failed"
        self.log_command({"kind": "audio-reactive-action", "result": summarize_for_log(result)})
        return (200 if result["ok"] else 500), result

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
            "agent_pipe": os.environ.get("SYLPHIE_AGENT_PIPE") or DEFAULT_PIPE,
            "static_dir": str(static_dir),
            "working_directory": os.getcwd(),
            "server_pid": os.getpid(),
            "python_version": sys.version,
            "running": state["running"],
            "current_command": state["current_command"],
        }

    def start_capture(self, capture_type, capture_block_payload=True, stack_already_stopped=False, high_rate=False, priority_high=False, scenario=None):
        with self.capture_lock:
            if self.capture_process is not None and self.capture_process.poll() is None:
                return 409, {"ok": False, "error": "capture already running", **self.capture_status_locked()}

            capture_dir = self.project_root / "research" / "captures"
            ensure_dir(capture_dir)
            stamp = time.strftime("%Y%m%d_%H%M%S")
            marker_log = capture_dir / f"markers_{stamp}.log"

            if capture_type == "armoury-ui":
                exe = self.project_root / "bin" / "sylphie_piix4_armoury_ui_capture.exe"
                log_path = capture_dir / f"armoury_ui_{stamp}_master.log"
                command = [str(exe), "--base", "0B20", "--output", str(log_path), "--segment-logs"]
                if capture_block_payload:
                    command.append("--capture-block-payload")
                if high_rate:
                    focus_registers = STUCK_TRANSITION_FOCUS_REGISTERS if str(scenario or "").upper() == "RED_STUCK_TO_GREEN_CAPTURE" else DEFAULT_CAPTURE_FOCUS_REGISTERS
                    command += ["--high-rate", "--focus-addr", "40", "--focus-registers", focus_registers]
                if priority_high:
                    command.append("--priority-high")
            elif capture_type == "broad":
                exe = self.project_root / "bin" / "sylphie_piix4_broad_capture.exe"
                log_path = capture_dir / f"broad_{stamp}_master.log"
                command = [str(exe), "--output", str(log_path)]
                if capture_block_payload:
                    command.append("--capture-block-payload")
            else:
                return 400, {"ok": False, "error": "capture type must be broad or armoury-ui"}

            if not exe.is_file():
                return 500, {"ok": False, "error": "capture executable not found", "exe": str(exe)}

            try:
                process = subprocess.Popen(command, cwd=str(self.project_root), shell=False)
            except OSError as exc:
                return 500, {"ok": False, "error": str(exc), "command": command}

            self.capture_process = process
            self.capture_type = capture_type
            self.capture_log = log_path
            self.capture_marker_log = marker_log
            append_line(marker_log, f"{timestamp_text()} CAPTURE_START type={capture_type}")
            if scenario:
                append_line(marker_log, f"{timestamp_text()} MARKER SCENARIO_{str(scenario).strip().upper()}")
            snapshot = capture_stack_snapshot()
            append_line(marker_log, f"{timestamp_text()} CAPTURE_START_SNAPSHOT {json.dumps(snapshot, separators=(',', ':'))}")
            if stack_already_stopped:
                append_line(marker_log, f"{timestamp_text()} MARKER STACK_ALREADY_STOPPED_AT_CAPTURE_START")
            payload = {"ok": True, "command": command, **self.capture_status_locked()}
            payload["stack_already_stopped"] = bool(stack_already_stopped)
            payload["scenario"] = scenario
            payload["capture_start_snapshot"] = snapshot
            self.log_command({"kind": "capture-start", "result": payload})
            return 200, payload

    def start_cold_start_capture(self, mode):
        if mode not in ("gui-cold-launch", "service-only"):
            return 400, {"ok": False, "error": "mode must be gui-cold-launch or service-only"}

        script = (self.project_root / "scripts" / "capture_armoury_cold_start.ps1").resolve()
        if not script.is_file():
            return 500, {"ok": False, "error": "cold-start capture script not found", "script": str(script)}

        script_args = [
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
            "-Mode",
            mode,
        ]
        command = elevated_powershell_command(self.project_root, script_args)
        start = time.perf_counter()
        try:
            completed = subprocess.run(command, capture_output=True, text=True, timeout=8, shell=False)
        except subprocess.TimeoutExpired as exc:
            return 500, {
                "ok": False,
                "error": "timed out while launching elevated cold-start capture",
                "stdout": ensure_text(exc.stdout),
                "stderr": ensure_text(exc.stderr),
                "command": command,
            }
        except OSError as exc:
            return 500, {"ok": False, "error": str(exc), "command": command}

        result = {
            "ok": completed.returncode == 0,
            "command": command,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "exit_code": completed.returncode,
            "duration_ms": elapsed_ms(start),
            "message": "Elevated cold-start capture window requested. The dashboard/server may stop during the workflow.",
        }
        if not result["ok"]:
            result["error"] = result["stderr"] or result["stdout"] or "failed to launch elevated cold-start capture"
        self.log_command({"kind": "capture-cold-start", "result": summarize_for_log(result)})
        return (200 if result["ok"] else 500), result

    def start_armoury_stack_for_capture(self, mode):
        if mode not in ("gui-cold-launch", "service-only"):
            return 400, {"ok": False, "error": "mode must be gui-cold-launch or service-only"}
        with self.capture_lock:
            if self.capture_process is None or self.capture_process.poll() is not None:
                return 409, {"ok": False, "error": "no capture running"}
            marker_log = self.capture_marker_log

        script = (self.project_root / "scripts" / "start_armoury_stack.ps1").resolve()
        if not script.is_file():
            return 500, {"ok": False, "error": "start Armoury stack script not found", "script": str(script)}
        script_args = [
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
            "-Mode",
            mode,
            "-MarkerLog",
            str(marker_log),
        ]
        command = elevated_powershell_command(self.project_root, script_args)
        start = time.perf_counter()
        try:
            completed = subprocess.run(command, capture_output=True, text=True, timeout=8, shell=False)
        except subprocess.TimeoutExpired as exc:
            return 500, {
                "ok": False,
                "error": "timed out while launching elevated Armoury stack start",
                "stdout": ensure_text(exc.stdout),
                "stderr": ensure_text(exc.stderr),
                "command": command,
            }
        except OSError as exc:
            return 500, {"ok": False, "error": str(exc), "command": command}
        result = {
            "ok": completed.returncode == 0,
            "command": command,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "exit_code": completed.returncode,
            "duration_ms": elapsed_ms(start),
            "message": "Elevated Armoury stack start requested. Add FIRST_LIGHT marker manually when LEDs return.",
        }
        if not result["ok"]:
            result["error"] = result["stderr"] or result["stdout"] or "failed to launch Armoury stack start"
        self.log_command({"kind": "capture-start-stack", "result": summarize_for_log(result)})
        return (200 if result["ok"] else 500), result

    def capture_marker(self, marker):
        marker = marker.strip().upper()
        if not MARKER_RE.match(marker):
            return 400, {"ok": False, "error": "invalid marker"}
        with self.capture_lock:
            if self.capture_process is None or self.capture_process.poll() is not None:
                return 409, {"ok": False, "error": "no capture running"}
            append_line(self.capture_marker_log, f"{timestamp_text()} MARKER {marker}")
            return 200, {"ok": True, "marker": marker, **self.capture_status_locked()}

    def stop_capture(self):
        with self.capture_lock:
            if self.capture_process is None:
                return 200, {"ok": True, "stopped": False, "message": "no capture process tracked"}
            process = self.capture_process
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)
            append_line(self.capture_marker_log, f"{timestamp_text()} CAPTURE_STOP exit_code={process.returncode}")
            payload = {"ok": True, "stopped": True, **self.capture_status_locked()}
            self.capture_process = None
            return 200, payload

    def capture_status(self):
        with self.capture_lock:
            return {"ok": True, **self.capture_status_locked()}

    def capture_status_locked(self):
        running = self.capture_process is not None and self.capture_process.poll() is None
        return {
            "running": running,
            "pid": self.capture_process.pid if self.capture_process is not None else None,
            "type": self.capture_type,
            "log": str(self.capture_log) if self.capture_log else None,
            "marker_log": str(self.capture_marker_log) if self.capture_marker_log else None,
            "exit_code": self.capture_process.poll() if self.capture_process is not None else None,
        }

    def analyze_capture(self):
        script = self.project_root / "tools" / "analyze_capture.py"
        if not script.is_file():
            return 500, {"ok": False, "error": "analyzer not found", "script": str(script)}
        with self.capture_lock:
            log_path = self.capture_log
        if log_path is None:
            captures = list_captures(self.project_root)
            if not captures:
                return 404, {"ok": False, "error": "no capture log found"}
            log_path = Path(captures[0]["path"])
        command = [sys.executable, str(script), str(log_path), "--write-red-stuck-summary", "--summary-dir", str(self.project_root / "docs" / "research")]
        with self.capture_lock:
            marker_log = self.capture_marker_log
        if marker_log:
            command += ["--markers", str(marker_log)]
        start = time.perf_counter()
        try:
            completed = subprocess.run(command, capture_output=True, text=True, timeout=15, shell=False)
        except subprocess.TimeoutExpired as exc:
            return 500, {
                "ok": False,
                "error": "capture analysis timed out",
                "stdout": ensure_text(exc.stdout),
                "stderr": ensure_text(exc.stderr),
                "command": command,
            }
        except OSError as exc:
            return 500, {"ok": False, "error": str(exc), "command": command}
        result = {
            "ok": completed.returncode == 0,
            "command": command,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "exit_code": completed.returncode,
            "duration_ms": elapsed_ms(start),
        }
        if not result["ok"]:
            result["error"] = result["stderr"] or result["stdout"] or "capture analysis failed"
        return (200 if result["ok"] else 500), result


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


def ensure_dir(path):
    Path(path).mkdir(parents=True, exist_ok=True)


def timestamp_text():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def append_line(path, text):
    ensure_dir(Path(path).parent)
    with Path(path).open("a", encoding="utf-8") as handle:
        handle.write(text + "\n")


def powershell_quote_arg(value):
    return "'" + str(value).replace("'", "''") + "'"


def elevated_powershell_command(working_directory, script_args):
    argument_array = "@(" + ",".join(powershell_quote_arg(arg) for arg in script_args) + ")"
    command_text = (
        "Start-Process "
        "-FilePath 'powershell.exe' "
        "-Verb RunAs "
        "-WorkingDirectory "
        + powershell_quote_arg(working_directory)
        + " -ArgumentList "
        + argument_array
    )
    return [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        command_text,
    ]


def summarize_for_log(result):
    copy = dict(result)
    for key in ("stdout", "stderr"):
        if isinstance(copy.get(key), str) and len(copy[key]) > 500:
            copy[key] = copy[key][:500] + "... truncated ..."
    return copy


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
    if length > 65536:
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


def parse_lines(query, default=200):
    try:
        lines = int(query.get("lines", [str(default)])[0])
    except ValueError:
        lines = default
    return max(1, min(lines, 1000))


def tail_file(path, lines=200, max_bytes=256 * 1024):
    path = Path(path)
    if not path.is_file():
        return {"ok": False, "error": "file not found", "path": str(path), "text": ""}
    with path.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        size = handle.tell()
        handle.seek(max(0, size - max_bytes))
        data = handle.read()
    text = data.decode("utf-8", errors="replace")
    return {"ok": True, "path": str(path), "text": "\n".join(text.splitlines()[-lines:])}


def list_captures(project_root):
    capture_dir = project_root / "research" / "captures"
    if not capture_dir.is_dir():
        return []
    files = sorted(capture_dir.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    return [{"name": p.name, "path": str(p), "modified_time": p.stat().st_mtime, "size": p.stat().st_size} for p in files[:100]]


def capture_stack_snapshot():
    service_list = ",".join(json.dumps(name) for name in KNOWN_SERVICES)
    process_list = ",".join(json.dumps(name) for name in KNOWN_PROCESSES)
    script = f"""
$serviceNames = @({service_list})
$processNames = @({process_list})
$services = @()
foreach ($name in $serviceNames) {{
  $svc = Get-CimInstance Win32_Service -Filter ("Name='{{0}}'" -f $name.Replace("'", "''")) -ErrorAction SilentlyContinue
  if ($null -ne $svc) {{
    $services += [pscustomobject]@{{
      name = $svc.Name
      state = $svc.State
      start_mode = $svc.StartMode
      process_id = $svc.ProcessId
      account = $svc.StartName
    }}
  }} else {{
    $services += [pscustomobject]@{{
      name = $name
      state = "not_found"
      start_mode = $null
      process_id = $null
      account = $null
    }}
  }}
}}
$processes = @()
foreach ($name in $processNames) {{
  Get-CimInstance Win32_Process -Filter ("Name='{{0}}.exe'" -f $name.Replace("'", "''")) -ErrorAction SilentlyContinue | ForEach-Object {{
    $processes += [pscustomobject]@{{
      name = $_.Name
      pid = $_.ProcessId
      command_line = $_.CommandLine
    }}
  }}
}}
[pscustomobject]@{{
  captured_at = (Get-Date).ToString("o")
  services = $services
  processes = $processes
}} | ConvertTo-Json -Depth 6
"""
    command = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script]
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=15, shell=False, encoding="utf-8", errors="replace")
    except Exception as exc:
        return {"ok": False, "error": str(exc), "services": [], "processes": []}
    if completed.returncode != 0:
        return {"ok": False, "error": completed.stderr or completed.stdout, "services": [], "processes": []}
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        return {"ok": False, "error": "snapshot JSON parse failed: " + str(exc), "raw": completed.stdout, "services": [], "processes": []}
    payload["ok"] = True
    return payload


def ownership_probe_snapshot():
    process_list = ",".join(json.dumps(name) for name in OWNERSHIP_PROCESS_NAMES)
    script = f"""
$processNames = @({process_list})
$lighting = Get-CimInstance Win32_Service -Filter "Name='LightingService'" -ErrorAction SilentlyContinue
$processes = @()
foreach ($name in $processNames) {{
  Get-CimInstance Win32_Process -Filter ("Name='{{0}}.exe'" -f $name.Replace("'", "''")) -ErrorAction SilentlyContinue | ForEach-Object {{
    $processes += [pscustomobject]@{{
      name = $_.Name
      pid = $_.ProcessId
      base_name = [System.IO.Path]::GetFileNameWithoutExtension($_.Name)
    }}
  }}
}}
[pscustomobject]@{{
  ok = $true
  captured_at = (Get-Date).ToString("o")
  lighting_service = $(if ($null -ne $lighting) {{
    [pscustomobject]@{{
      exists = $true
      state = $lighting.State
      status = $lighting.Status
      process_id = $lighting.ProcessId
      account = $lighting.StartName
      path = $lighting.PathName
    }}
  }} else {{
    [pscustomobject]@{{
      exists = $false
      state = "not_found"
      status = "not_found"
      process_id = $null
      account = $null
      path = $null
    }}
  }})
  processes = $processes
}} | ConvertTo-Json -Depth 6
"""
    command = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script]
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=8, shell=False, encoding="utf-8", errors="replace")
    except Exception as exc:
        return {"ok": False, "error": str(exc), "processes": []}
    if completed.returncode != 0:
        return {"ok": False, "error": completed.stderr or completed.stdout, "processes": []}
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        return {"ok": False, "error": "ownership JSON parse failed: " + str(exc), "raw": completed.stdout, "processes": []}
    payload["ok"] = True
    return payload


def derive_ownership_mode(capture_running, agent_status, probe):
    reasons = []
    agent_running = bool(agent_status.get("ok"))
    agent_response = agent_status.get("response") or {}
    agent_state = agent_response.get("state") or {}
    agent_elevated = bool(agent_state.get("is_elevated"))
    lighting = probe.get("lighting_service") or {}
    lighting_running = str(lighting.get("state") or "").lower() == "running"
    processes = probe.get("processes") or []
    process_names = {str(item.get("base_name") or item.get("name") or "").lower() for item in processes}
    armoury_processes = [
        name for name in process_names
        if name in {
            "armourycrate",
            "armourycrate.usersessionhelper",
            "armourysocketserver",
            "armouryswagent",
            "armouryhtmldebugserver",
            "asus_framework",
            "aurawallpaperservice",
            "aura wallpaper service",
            "lightingservice",
            "aura",
            "openrgb",
            "openaurasdk",
        }
    ]

    if capture_running:
        reasons.append("research capture is running")
        if agent_running:
            reasons.append("Sylphie agent is also running during capture")
            return "conflict", reasons
        return "research", reasons

    if agent_running:
        reasons.append("Sylphie agent is responding")
        if not agent_elevated:
            reasons.append("Sylphie agent is not elevated")
            return "conflict", reasons
        if lighting_running or armoury_processes:
            if lighting_running:
                reasons.append("LightingService is running")
            if armoury_processes:
                reasons.append("Armoury/Aura process detected: " + ", ".join(sorted(armoury_processes)))
            return "conflict", reasons
        return "sylphie", reasons

    if lighting_running or armoury_processes:
        if lighting_running:
            reasons.append("LightingService is running")
        if armoury_processes:
            reasons.append("Armoury/Aura process detected: " + ", ".join(sorted(armoury_processes)))
        return "armoury", reasons

    reasons.append("no clear Armoury or Sylphie owner detected")
    return "unknown", reasons


def armoury_health_snapshot():
    service_list = ",".join(json.dumps(name) for name in ARMOURY_HEALTH_SERVICES)
    pattern_list = ",".join(json.dumps(name) for name in ARMOURY_HEALTH_PROCESS_PATTERNS)
    script = f"""
$serviceNames = @({service_list})
$processPatterns = @({pattern_list})
$services = @()
foreach ($name in $serviceNames) {{
  $svc = Get-CimInstance Win32_Service -Filter ("Name='{{0}}'" -f $name.Replace("'", "''")) -ErrorAction SilentlyContinue
  if ($null -ne $svc) {{
    $services += [pscustomobject]@{{
      name = $svc.Name
      display_name = $svc.DisplayName
      exists = $true
      state = $svc.State
      status = $svc.Status
      start_mode = $svc.StartMode
      process_id = $svc.ProcessId
      account = $svc.StartName
      path = $svc.PathName
    }}
  }} else {{
    $services += [pscustomobject]@{{
      name = $name
      display_name = $null
      exists = $false
      state = "not_found"
      status = "not_found"
      start_mode = $null
      process_id = $null
      account = $null
      path = $null
    }}
  }}
}}
$processes = @()
Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | ForEach-Object {{
  $baseName = [System.IO.Path]::GetFileNameWithoutExtension($_.Name)
  $matches = @()
  foreach ($pattern in $processPatterns) {{
    if ($baseName -like $pattern) {{
      $matches += $pattern
    }}
  }}
  if ($matches.Count -gt 0) {{
    $processes += [pscustomobject]@{{
      name = $_.Name
      base_name = $baseName
      pid = $_.ProcessId
      matched_rules = $matches
      executable_path = $_.ExecutablePath
      command_line = $_.CommandLine
    }}
  }}
}}
$logiStorm = @($processes | Where-Object {{ $_.base_name -like "logi_download_assistant*" }})
[pscustomobject]@{{
  ok = $true
  captured_at = (Get-Date).ToString("o")
  warning = "Music mode depends on Armoury addons/audio pipeline, not only SMBus RGB."
  services = $services
  process_patterns = $processPatterns
  processes = $processes
  logi_download_assistant_count = $logiStorm.Count
  logi_download_assistant_storm = $logiStorm.Count -gt 3
}} | ConvertTo-Json -Depth 6
"""
    command = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script]
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=15, shell=False, encoding="utf-8", errors="replace")
    except Exception as exc:
        return {"ok": False, "error": str(exc), "services": [], "processes": []}
    if completed.returncode != 0:
        return {"ok": False, "error": completed.stderr or completed.stdout, "services": [], "processes": []}
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        return {"ok": False, "error": "Armoury health JSON parse failed: " + str(exc), "raw": completed.stdout, "services": [], "processes": []}
    payload["ok"] = True
    return payload


def audio_reactive_health_snapshot():
    service_list = ",".join(json.dumps(name) for name in AUDIO_REACTIVE_SERVICES)
    pattern_list = ",".join(json.dumps(name) for name in AUDIO_REACTIVE_PROCESS_PATTERNS)
    script = f"""
$serviceNames = @({service_list})
$optionalServiceNames = @("logi_lamparray_service")
$processPatterns = @({pattern_list})
$services = @()
foreach ($name in $serviceNames) {{
  $svc = Get-CimInstance Win32_Service -Filter ("Name='{{0}}'" -f $name.Replace("'", "''")) -ErrorAction SilentlyContinue
  $optional = $optionalServiceNames -contains $name
  if ($null -ne $svc) {{
    $services += [pscustomobject]@{{
      name = $svc.Name
      display_name = $svc.DisplayName
      exists = $true
      optional = $optional
      state = $svc.State
      status = $svc.Status
      start_mode = $svc.StartMode
      process_id = $svc.ProcessId
      account = $svc.StartName
    }}
  }} else {{
    $services += [pscustomobject]@{{
      name = $name
      display_name = $null
      exists = $false
      optional = $optional
      state = "not_found"
      status = "not_found"
      start_mode = $null
      process_id = $null
      account = $null
    }}
  }}
}}
$processes = @()
Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | ForEach-Object {{
  $baseName = [System.IO.Path]::GetFileNameWithoutExtension($_.Name)
  $matches = @()
  foreach ($pattern in $processPatterns) {{
    if ($baseName -like $pattern) {{
      $matches += $pattern
    }}
  }}
  if ($matches.Count -gt 0) {{
    $processes += [pscustomobject]@{{
      name = $_.Name
      base_name = $baseName
      pid = $_.ProcessId
      matched_rules = $matches
      executable_path = $_.ExecutablePath
      command_line = $_.CommandLine
    }}
  }}
}}
[pscustomobject]@{{
  ok = $true
  captured_at = (Get-Date).ToString("o")
  warning = "Music mode depends on Armoury/audio capture pipeline, not only SMBus RGB control."
  services = $services
  process_patterns = $processPatterns
  processes = $processes
}} | ConvertTo-Json -Depth 6
"""
    command = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script]
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=15, shell=False, encoding="utf-8", errors="replace")
    except Exception as exc:
        return {"ok": False, "error": str(exc), "services": [], "processes": []}
    if completed.returncode != 0:
        return {"ok": False, "error": completed.stderr or completed.stdout, "services": [], "processes": []}
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        return {"ok": False, "error": "audio/reactive JSON parse failed: " + str(exc), "raw": completed.stdout, "services": [], "processes": []}
    payload["ok"] = True
    return payload


def audio_reactive_action_script(action, project_root):
    log_path = Path(project_root) / "logs" / "audio_reactive_actions.log"
    prelude = f"""
$ErrorActionPreference = "Stop"
$LogPath = {powershell_quote_arg(log_path)}
function Write-SylphieAudioReactiveLog([string]$Message) {{
  $line = ("{{0}} {{1}}" -f (Get-Date).ToString("o"), $Message)
  Add-Content -LiteralPath $LogPath -Value $line
  Write-Host $Message
}}
Write-SylphieAudioReactiveLog "action={action} started"
try {{
"""
    epilogue = f"""
  Write-SylphieAudioReactiveLog "action={action} completed"
}} catch {{
  Write-SylphieAudioReactiveLog ("action={action} ERROR " + $_.Exception.Message)
  exit 1
}}
"""
    scripts = {
        "restart-lighting-service": """
  $svc = Get-Service -Name "LightingService" -ErrorAction SilentlyContinue
  if ($null -eq $svc) {
    Write-SylphieAudioReactiveLog "LightingService not found"
  } else {
    Write-SylphieAudioReactiveLog "Restarting LightingService"
    Restart-Service -Name "LightingService" -Force
    $state = (Get-Service -Name "LightingService").Status
    Write-SylphieAudioReactiveLog ("LightingService status=" + $state)
  }
""",
        "restart-windows-audio": """
  Write-SylphieAudioReactiveLog "Restarting Windows audio services"
  $audio = Get-Service -Name "Audiosrv" -ErrorAction SilentlyContinue
  if ($null -ne $audio -and $audio.Status -ne "Stopped") {
    Stop-Service -Name "Audiosrv" -Force
    Write-SylphieAudioReactiveLog "Audiosrv stopped"
  }
  $endpoint = Get-Service -Name "AudioEndpointBuilder" -ErrorAction SilentlyContinue
  if ($null -ne $endpoint -and $endpoint.Status -ne "Stopped") {
    Stop-Service -Name "AudioEndpointBuilder" -Force
    Write-SylphieAudioReactiveLog "AudioEndpointBuilder stopped"
  }
  Start-Service -Name "AudioEndpointBuilder"
  Write-SylphieAudioReactiveLog "AudioEndpointBuilder started"
  Start-Service -Name "Audiosrv"
  Write-SylphieAudioReactiveLog "Audiosrv started"
""",
        "restore-logitech-lamparray": """
  $svc = Get-Service -Name "logi_lamparray_service" -ErrorAction SilentlyContinue
  if ($null -eq $svc) {
    Write-SylphieAudioReactiveLog "logi_lamparray_service not found"
  } else {
    Write-SylphieAudioReactiveLog "Restoring logi_lamparray_service startup and state"
    Set-Service -Name "logi_lamparray_service" -StartupType Automatic
    Start-Service -Name "logi_lamparray_service"
    $state = (Get-Service -Name "logi_lamparray_service").Status
    Write-SylphieAudioReactiveLog ("logi_lamparray_service status=" + $state)
  }
""",
    }
    body = scripts.get(action)
    if body is None:
        return None
    return prelude + body + epilogue


def make_handler(server_state):
    static_dir = Path(__file__).resolve().parent / "static"

    class Handler(SimpleHTTPRequestHandler):
        server_version = "SylphieHTTP/0.2"

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
            parsed = urlparse(self.path)
            path = parsed.path
            query = parse_qs(parsed.query)

            if path == "/api/health":
                doctor = server_state.run_backend(["doctor"])
                agent_status = server_state.run_agent_payload({"id": str(uuid.uuid4()), "cmd": "status"}, timeout_seconds=2, command=["agent", "status"])
                takeover = server_state.run_agent_payload({"id": str(uuid.uuid4()), "cmd": "takeover_check"}, timeout_seconds=3, command=["agent", "takeover_check"])
                bus_status = server_state.run_backend(["bus-status"])
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
                        "agent_status": agent_status,
                        "takeover_check": takeover,
                        "bus_status": bus_status,
                    },
                )
                return

            if path == "/api/scenes":
                scenes = server_state.run_backend(["scenes"])
                self.send_json(200 if scenes["ok"] else 500, {"ok": scenes["ok"], "raw": scenes["stdout"], "stderr": scenes["stderr"], "exit_code": scenes["exit_code"]})
                return

            if path == "/api/state":
                self.send_json(200, server_state.state())
                return

            if path == "/api/debug/config":
                self.send_json(200, server_state.debug_config(static_dir))
                return

            if path == "/api/agent/status":
                result = server_state.run_agent_payload({"id": str(uuid.uuid4()), "cmd": "status"}, timeout_seconds=3, command=["agent", "status"])
                self.send_json(200 if result["ok"] else 503, result)
                return

            if path == "/api/lifecycle/status":
                result = server_state.lifecycle_status()
                self.send_json(200 if result["ok"] else 503, result)
                return

            if path == "/api/ownership/status":
                result = server_state.ownership_status()
                self.send_json(200 if result.get("ok") else 503, result)
                return

            if path == "/api/agent/task/status":
                result = server_state.agent_task_status()
                self.send_json(200 if result.get("ok") else 503, result)
                return

            if path == "/api/services/status":
                result = server_state.run_agent_payload({"id": str(uuid.uuid4()), "cmd": "service_status"}, timeout_seconds=5, command=["agent", "service_status"])
                self.send_json(200 if result["ok"] else 503, result)
                return

            if path == "/api/diagnostics/audio-reactive-health":
                result = server_state.audio_reactive_health()
                self.send_json(200 if result.get("ok") else 500, result)
                return

            if path == "/api/diagnostics/armoury-health":
                result = server_state.armoury_health()
                self.send_json(200 if result.get("ok") else 500, result)
                return

            if path == "/api/capture/status":
                self.send_json(200, server_state.capture_status())
                return

            if path == "/api/capture/tail":
                status = server_state.capture_status()
                log = status.get("log")
                if not log:
                    self.send_json(404, {"ok": False, "error": "no capture log tracked"})
                    return
                self.send_json(200, tail_file(log, parse_lines(query)))
                return

            if path == "/api/capture/list":
                self.send_json(200, {"ok": True, "captures": list_captures(server_state.project_root)})
                return

            if path == "/api/capture/snapshot":
                self.send_json(200, {"ok": True, "snapshot": capture_stack_snapshot()})
                return

            if path == "/api/logs/tail":
                name = query.get("name", [""])[0]
                if name not in LOG_WHITELIST:
                    self.send_json(400, {"ok": False, "error": "unknown log name"})
                    return
                self.send_json(200, tail_file(server_state.project_root / LOG_WHITELIST[name], parse_lines(query)))
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
                elif path == "/api/bus-status":
                    result = server_state.run_backend(["bus-status"])
                    status = 200 if result["ok"] else 500
                elif path == "/api/agent/ping":
                    result = server_state.run_agent_payload({"id": str(uuid.uuid4()), "cmd": "ping"}, timeout_seconds=2, command=["agent", "ping"])
                    status = 200 if result["ok"] else 503
                elif path == "/api/agent/recover":
                    status, result = server_state.run_hardware_command(["recover"], check_takeover=False)
                elif path == "/api/agent/recover-set":
                    rgb = normalize_rgb(body.get("rgb"))
                    status, result = server_state.run_hardware_command(["recover-set", rgb], rgb=rgb, check_takeover=False)
                elif path == "/api/agent/set":
                    rgb = normalize_rgb(body.get("rgb"))
                    status, result = server_state.run_hardware_command(["set", rgb], rgb=rgb)
                elif path == "/api/agent/off":
                    status, result = server_state.run_hardware_command(["off"], rgb="000000", scene="off")
                elif path == "/api/agent/bus-status":
                    result = server_state.run_agent_payload({"id": str(uuid.uuid4()), "cmd": "bus_status"}, timeout_seconds=5, command=["agent", "bus_status"])
                    status = 200 if result["ok"] else 503
                elif path == "/api/agent/takeover-check" or path == "/api/takeover-check":
                    result = server_state.run_agent_payload({"id": str(uuid.uuid4()), "cmd": "takeover_check"}, timeout_seconds=5, command=["agent", "takeover_check"])
                    status = 200 if result["ok"] else 409
                elif path == "/api/agent/takeover-dry-run" or path == "/api/services/takeover/dry-run":
                    payload = {"id": str(uuid.uuid4()), "cmd": "takeover_dry_run", "include_armoury_core": bool(body.get("include_armoury_core", False))}
                    result = server_state.run_agent_payload(payload, timeout_seconds=5, command=["agent", "takeover_dry_run"])
                    status = 200 if result["ok"] else 503
                elif path == "/api/agent/takeover-execute" or path == "/api/services/takeover/execute":
                    payload = {
                        "id": str(uuid.uuid4()),
                        "cmd": "takeover_execute",
                        "i_accept_stopping_lighting_services": bool(body.get("i_accept_stopping_lighting_services", False)),
                        "include_armoury_core": bool(body.get("include_armoury_core", False)),
                    }
                    result = server_state.run_agent_payload(payload, timeout_seconds=20, command=["agent", "takeover_execute"])
                    status = 200 if result["ok"] else 500
                elif path == "/api/agent/restore-services" or path == "/api/services/restore" or path == "/api/restore-services":
                    result = server_state.run_agent_payload({"id": str(uuid.uuid4()), "cmd": "restore_services"}, timeout_seconds=10, command=["agent", "restore_services"])
                    status = 200 if result["ok"] else 503
                elif path == "/api/agent/task/install":
                    result = server_state.run_agent_task_action("install", enable_autostart=bool(body.get("enable_autostart", False)))
                    status = 200 if result["ok"] else 500
                elif path == "/api/agent/task/enable-autostart":
                    result = server_state.run_agent_task_action("enable")
                    status = 200 if result["ok"] else 500
                elif path == "/api/agent/task/disable-autostart":
                    result = server_state.run_agent_task_action("disable")
                    status = 200 if result["ok"] else 500
                elif path == "/api/agent/task/uninstall":
                    result = server_state.run_agent_task_action("uninstall", stop_agent=bool(body.get("stop_agent", False)))
                    status = 200 if result["ok"] else 500
                elif path == "/api/agent/task/start-now":
                    result = server_state.run_agent_task_action("start-now")
                    status = 200 if result["ok"] else 500
                elif path == "/api/agent/task/stop":
                    result = server_state.run_agent_task_action("stop")
                    status = 200 if result["ok"] else 500
                elif path == "/api/ownership/return-to-armoury":
                    result = server_state.run_ownership_action(
                        "return-to-armoury",
                        disable_autostart=bool(body.get("disable_autostart", False)),
                        launch_armoury=bool(body.get("launch_armoury", False)),
                    )
                    status = 200 if result["ok"] else 500
                elif path == "/api/ownership/takeover-for-sylphie":
                    result = server_state.run_ownership_action("takeover-for-sylphie")
                    status = 200 if result["ok"] else 500
                elif path == "/api/diagnostics/audio-reactive/restart-lighting":
                    status, result = server_state.run_audio_reactive_action("restart-lighting-service")
                elif path == "/api/diagnostics/audio-reactive/restart-windows-audio":
                    status, result = server_state.run_audio_reactive_action("restart-windows-audio")
                elif path == "/api/diagnostics/audio-reactive/restore-logitech-lamparray":
                    status, result = server_state.run_audio_reactive_action("restore-logitech-lamparray")
                elif path == "/api/diagnostics/armoury/restart-lighting":
                    result = server_state.run_armoury_action("restart-lighting")
                    status = 200 if result["ok"] else 500
                elif path == "/api/diagnostics/armoury/restart-stack":
                    result = server_state.run_armoury_action("restart-stack")
                    status = 200 if result["ok"] else 500
                elif path == "/api/diagnostics/armoury/restore-logitech-lamparray":
                    result = server_state.run_armoury_action("restore-logitech-lamparray")
                    status = 200 if result["ok"] else 500
                elif path == "/api/takeover":
                    execute = bool(body.get("execute", False))
                    if execute:
                        payload = {
                            "id": str(uuid.uuid4()),
                            "cmd": "takeover_execute",
                            "i_accept_stopping_lighting_services": bool(body.get("accept", False)),
                            "include_armoury_core": bool(body.get("include_armoury_core", False)),
                        }
                        result = server_state.run_agent_payload(payload, timeout_seconds=20, command=["agent", "takeover_execute"])
                    else:
                        payload = {"id": str(uuid.uuid4()), "cmd": "takeover_dry_run", "include_armoury_core": bool(body.get("include_armoury_core", False))}
                        result = server_state.run_agent_payload(payload, timeout_seconds=5, command=["agent", "takeover_dry_run"])
                    status = 200 if result["ok"] else 500
                elif path == "/api/lifecycle/start-agent":
                    result = server_state.run_lifecycle_script("start-agent", timeout_seconds=15)
                    status = 200 if result["ok"] else 500
                elif path == "/api/lifecycle/stop-agent":
                    result = server_state.run_lifecycle_script("stop-agent", timeout_seconds=15)
                    status = 200 if result["ok"] else 500
                elif path == "/api/lifecycle/restart-agent":
                    stop = server_state.run_lifecycle_script("stop-agent", timeout_seconds=15)
                    start = server_state.run_lifecycle_script("start-agent", timeout_seconds=15)
                    result = {"ok": stop["ok"] and start["ok"], "stop": stop, "start": start, "command": ["restart-agent"]}
                    status = 200 if result["ok"] else 500
                elif path == "/api/capture/start":
                    capture_type = body.get("type")
                    status, result = server_state.start_capture(
                        capture_type,
                        capture_block_payload=bool(body.get("capture_block_payload", True)),
                        stack_already_stopped=bool(body.get("stack_already_stopped", False)),
                        high_rate=bool(body.get("high_rate", False)),
                        priority_high=bool(body.get("priority_high", False)),
                        scenario=body.get("scenario"),
                    )
                elif path == "/api/capture/cold-start":
                    status, result = server_state.start_cold_start_capture(str(body.get("mode", "gui-cold-launch")))
                elif path == "/api/capture/start-stack":
                    status, result = server_state.start_armoury_stack_for_capture(str(body.get("mode", "gui-cold-launch")))
                elif path == "/api/capture/analyze":
                    status, result = server_state.analyze_capture()
                elif path == "/api/capture/marker":
                    status, result = server_state.capture_marker(str(body.get("marker", "")))
                elif path == "/api/capture/stop":
                    status, result = server_state.stop_capture()
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
    use_agent = os.environ.get("SYLPHIE_USE_AGENT", "1") != "0"
    server_state = SylphieServer(exe_path, args.host, args.port, use_agent=use_agent)

    if args.host != DEFAULT_HOST:
        print("WARNING: binding to non-localhost host %s is not recommended" % args.host)

    handler = make_handler(server_state)
    httpd = ThreadingHTTPServer((args.host, args.port), handler)
    print("Sylphie server listening on http://%s:%d" % (args.host, args.port))
    print("Using sylphie_rgb.exe: %s" % exe_path)
    print("Server PID: %s" % os.getpid())
    if use_agent:
        print("Using Sylphie hardware agent via named pipe")
    httpd.serve_forever()


if __name__ == "__main__":
    main()
