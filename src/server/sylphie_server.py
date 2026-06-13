from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import argparse
import json
import locale
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
    "Aura Wallpaper Service",
    "ArmouryCrateService",
    "Armoury Crate Service",
    "ArmouryCrate.Service",
    "asComSvc",
    "ASUS Com Service",
    "AsusCertService",
    "asus",
    "asusm",
    "AsusROGLSLService",
    "OpenRGB",
    "OpenAuraSDK",
]

KNOWN_PROCESSES = [
    "ArmouryCrate",
    "ArmouryCrate.Service",
    "ArmouryCrate.UserSessionHelper",
    "ArmourySocketServer",
    "ArmourySwAgent",
    "ArmouryHtmlDebugServer",
    "asus_framework",
    "AuraWallpaperService",
    "Aura Wallpaper Service",
    "LightingService",
    "OpenRGB",
    "OpenAuraSDK",
]

TIER1_SERVICE_NAMES = {
    "lightingservice",
    "aura wallpaper service",
}

TIER1_PROCESS_NAMES = {
    "lightingservice",
    "aurawallpaperservice",
    "aura wallpaper service",
    "armourysocketserver",
    "armouryswagent",
    "armouryhtmldebugserver",
    "openrgb",
    "openaurasdk",
}

TIER2_SERVICE_NAMES = {
    "armourycrateservice",
    "armoury crate service",
    "armourycrate.service",
    "ascomsvc",
    "asus com service",
}

TIER2_PROCESS_NAMES = {
    "armourycrate",
    "armourycrate.service",
    "armourycrate.usersessionhelper",
    "asus_framework",
}

NEVER_STOP_SERVICE_NAMES = {
    "asuscertservice",
}

IGNORED_SERVICE_NAMES = {
    "asus",
    "asusm",
    "asusroglslservice",
}

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
    "Aura Wallpaper Service",
    "ArmouryCrateService",
    "Armoury Crate Service",
    "ArmouryCrate.Service",
    "asComSvc",
    "ASUS Com Service",
    "AsusCertService",
    "asus",
    "asusm",
    "AsusROGLSLService",
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
    "ArmouryCrate.Service",
    "ArmouryCrate.UserSessionHelper",
    "ArmourySocketServer",
    "ArmourySwAgent",
    "ArmouryHtmlDebugServer",
    "asus_framework",
    "LightingService",
    "AuraWallpaperService",
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
        if not self.exe_exists():
            result = {
                "ok": False,
                "command": command,
                "stdout": "",
                "stderr": "sylphie_rgb.exe not found: " + str(self.exe_path),
                "exit_code": None,
                "duration_ms": 0,
            }
            result["error"] = result["stderr"]
            self.log_command({"kind": "backend", "result": summarize_for_log(result)})
            return result
        result = run_subprocess(command, timeout_seconds=timeout_seconds)
        if not result["ok"] and result.get("error") == "command failed":
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
        result["stdout"] = json.dumps(response, indent=2, ensure_ascii=True)
        result["stderr"] = "" if result["ok"] else str(response.get("error") or "")
        result["exit_code"] = 0 if result["ok"] else 1
        result["duration_ms"] = elapsed_ms(start)
        if response.get("_pipe_encoding_used"):
            result["pipe_encoding_used"] = response.get("_pipe_encoding_used")
        if response.get("_pipe_decode_note"):
            result["output_encoding_note"] = response.get("_pipe_decode_note")
        if response.get("_pipe_decode_warning"):
            result["output_encoding_warning"] = response.get("_pipe_decode_warning")
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
                        "bus_write_ok": False,
                        "visual_state": "unknown",
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
                        "bus_write_ok": False,
                        "visual_state": "unknown",
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
                    "bus_write_ok": False,
                    "visual_state": "unknown",
                },
            )
        return (
            500,
            {
                "ok": False,
                "error": "controller ownership check failed",
                "details": takeover,
                "applied": False,
                "bus_write_ok": False,
                "visual_state": "unknown",
            },
        )

    def run_hardware_command(self, args, rgb=None, scene=None, check_takeover=True, allow_sanity=False):
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
                        "bus_write_ok": False,
                        "visual_state": "unknown",
                    },
                )

        try:
            with self.state_lock:
                self.current_command = command

            ownership = self.ownership_status()
            if not ownership.get("write_allowed") and not (allow_sanity and ownership.get("sanity_write_allowed")):
                result = {
                    "ok": False,
                    "error": "RGB writes are blocked unless Current owner is Sylphie Verified",
                    "ownership": ownership,
                    "command": command,
                    "exit_code": None,
                    "stdout": "",
                    "stderr": "",
                    "duration_ms": 0,
                    "applied": False,
                    "bus_write_ok": False,
                    "visual_state": "unknown",
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
            result["bus_write_ok"] = result["ok"] and result["exit_code"] == 0
            result["visual_state"] = "unknown"
            result["applied"] = False
            if not result["ok"] and "error" not in result:
                result["error"] = result["stderr"] or result["stdout"] or "backend command failed"

            with self.state_lock:
                self.current_command = None
                self.last_command = command
                self.last_result = result
                if result["bus_write_ok"]:
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
        command = powershell_file_command(str(script), extra_args)
        result = run_subprocess(command, timeout_seconds=timeout_seconds)
        if not result["ok"] and result.get("error") == "command failed":
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
        result = run_subprocess(command, timeout_seconds=timeout_seconds)
        result["message"] = "Elevated script requested. Re-run status after UAC/action completes."
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
        result = self.run_json_lifecycle_script("agent-task-control", ["-Action", "status"], timeout_seconds=10)
        pipe_responding = bool(result.get("pipe_responding") or result.get("agent_ping"))
        if pipe_responding:
            status = self.run_agent_payload({"id": str(uuid.uuid4()), "cmd": "status"}, timeout_seconds=2, command=["agent", "status"])
            result["agent_status"] = status
            state = status.get("response", {}).get("state") if status.get("ok") else None
            if state:
                result["elevated"] = bool(state.get("is_elevated"))
                result["agent_state"] = state
                result["agent_owner_status"] = state.get("current_owner_status")
                result["current_owner_status"] = state.get("current_owner_status")
                result["blocking_conflicts"] = state.get("blocking_conflicts") or []
                result["warnings"] = state.get("warnings") or []
                result["command_count"] = state.get("command_count")
                result["failure_count"] = state.get("failure_count")
                result["agent_process_running"] = True
                result["running"] = True
        return result

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
        ownership_marker = read_ownership_marker(self.project_root)
        derived = derive_ownership_mode(capture_running, agent_status, probe, ownership_marker.get("mode", "unknown"))
        derived.setdefault("sanity_write_allowed", False)
        derived.setdefault("claim_available", False)
        if derived.get("claim_available"):
            claim_bus_status = self.run_agent_payload({"id": str(uuid.uuid4()), "cmd": "bus_status"}, timeout_seconds=5, command=["agent", "bus_status"])
            derived["claim_bus_status"] = claim_bus_status
            if not claim_bus_status.get("ok"):
                derived["claim_available"] = False
                derived.setdefault("reasons", []).append("bus_status failed; clean ownership claim is unavailable")
        return {
            "ok": probe.get("ok", False),
            **derived,
            "owner": derived["mode"],
            "capture_running": capture_running,
            "agent_status": agent_status,
            "agent_task": task_status,
            "ownership_marker": ownership_marker,
            "probe": probe,
        }

    def run_ownership_action(self, action, disable_autostart=False, launch_armoury=False, include_armoury_core=False):
        if action == "return-to-armoury":
            args = []
            if disable_autostart:
                args.append("-DisableAutostart")
            if launch_armoury:
                args.append("-LaunchArmoury")
            result = self.run_elevated_lifecycle_script("return-to-armoury", args, kind="ownership-return-to-armoury")
            if result.get("ok"):
                write_ownership_marker(self.project_root, "armoury", "return-to-armoury requested")
            return result
        if action == "takeover-for-sylphie":
            args = []
            if include_armoury_core:
                args.append("-IncludeArmouryCore")
            return self.run_elevated_lifecycle_script("takeover-for-sylphie", args, kind="ownership-takeover-for-sylphie")
        return {"ok": False, "error": "unknown ownership action"}

    def claim_clean_ownership(self):
        agent_status = self.run_agent_payload({"id": str(uuid.uuid4()), "cmd": "status"}, timeout_seconds=2, command=["agent", "status"])
        probe = ownership_probe_snapshot()
        details = ownership_clean_details(agent_status, probe)
        agent_state = (agent_status.get("response") or {}).get("state") or {}
        if not agent_status.get("ok"):
            return 409, {"ok": False, "error": "Sylphie agent is not responding", "agent_status": agent_status, "ownership_clean": details}
        if not bool(agent_state.get("is_elevated")):
            return 409, {"ok": False, "error": "Sylphie agent is not elevated", "agent_status": agent_status, "ownership_clean": details}
        if not details["clean"]:
            return 409, {
                "ok": False,
                "error": "ownership is not clean",
                "ownership_clean": details,
                "message": "Claim clean ownership requires no tier1 blockers and no Armoury core running.",
            }
        bus_status = self.run_agent_payload({"id": str(uuid.uuid4()), "cmd": "bus_status"}, timeout_seconds=5, command=["agent", "bus_status"])
        if not bus_status.get("ok"):
            return 409, {
                "ok": False,
                "error": "bus_status failed; ownership was not claimed",
                "bus_status": bus_status,
                "ownership_clean": details,
            }
        write_ownership_marker(self.project_root, "sylphie_candidate", "user claimed already-clean ownership")
        return 200, {
            "ok": True,
            "mode": "sylphie_candidate",
            "ownership_candidate": True,
            "write_allowed": False,
            "sanity_write_allowed": True,
            "message": "Ownership is clean. Run direct sanity test to verify visual control.",
            "bus_status": bus_status,
            "ownership_clean": details,
        }

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
        result = run_subprocess(command, timeout_seconds=8)
        result["action"] = action
        result["log"] = str(log_path)
        result["message"] = "Elevated audio/reactive action requested. Re-run health after UAC/action completes."
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
        result = run_subprocess(command, timeout_seconds=8)
        result["message"] = "Elevated cold-start capture window requested. The dashboard/server may stop during the workflow."
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
        result = run_subprocess(command, timeout_seconds=8)
        result["message"] = "Elevated Armoury stack start requested. Add FIRST_LIGHT marker manually when LEDs return."
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
        result = run_subprocess(command, timeout_seconds=15)
        if not result["ok"]:
            result["error"] = result["stderr"] or result["stdout"] or "capture analysis failed"
        return (200 if result["ok"] else 500), result


def command_to_text(command):
    if not command:
        return None
    return " ".join(str(part) for part in command)


def robust_decode_bytes(value):
    if value is None:
        return {"text": "", "encoding_used": "none", "fallback_used": False, "replacement_used": False}
    if isinstance(value, str):
        return {"text": value, "encoding_used": "str", "fallback_used": False, "replacement_used": False}
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
            return {
                "text": value.decode(encoding),
                "encoding_used": encoding,
                "fallback_used": normalized not in ("utf-8", "utf8", "utf-8-sig"),
                "replacement_used": False,
            }
        except (UnicodeDecodeError, LookupError):
            continue
    return {
        "text": value.decode("utf-8", errors="replace"),
        "encoding_used": "utf-8-replace",
        "fallback_used": True,
        "replacement_used": True,
    }


def attach_decoded_output(result, stdout_bytes=None, stderr_bytes=None):
    stdout = robust_decode_bytes(stdout_bytes)
    stderr = robust_decode_bytes(stderr_bytes)
    result["stdout"] = stdout["text"]
    result["stderr"] = stderr["text"]
    result["stdout_encoding"] = stdout["encoding_used"]
    result["stderr_encoding"] = stderr["encoding_used"]
    result["output_encoding"] = {
        "stdout": {key: stdout[key] for key in ("encoding_used", "fallback_used", "replacement_used")},
        "stderr": {key: stderr[key] for key in ("encoding_used", "fallback_used", "replacement_used")},
    }
    if stdout["replacement_used"] or stderr["replacement_used"]:
        result["output_encoding_warning"] = "Command output encoding error. Output was decoded with replacement characters."
    elif stdout["fallback_used"] or stderr["fallback_used"]:
        result["output_encoding_note"] = "Command output was decoded with a fallback encoding."
    return result


def run_subprocess(command, timeout_seconds, shell=False):
    start = time.perf_counter()
    result = {
        "ok": False,
        "command": command,
        "stdout": "",
        "stderr": "",
        "exit_code": None,
        "duration_ms": 0,
    }
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            timeout=timeout_seconds,
            shell=shell,
        )
    except subprocess.TimeoutExpired as exc:
        attach_decoded_output(result, exc.stdout, exc.stderr)
        result["stderr"] = (result["stderr"] + "\n" if result["stderr"] else "") + "command timed out after %d seconds" % timeout_seconds
        result["error"] = result.get("output_encoding_warning") or result["stderr"]
        result["duration_ms"] = elapsed_ms(start)
        return result
    except OSError as exc:
        result["stderr"] = str(exc)
        result["error"] = result["stderr"]
        result["duration_ms"] = elapsed_ms(start)
        return result

    attach_decoded_output(result, completed.stdout, completed.stderr)
    result["exit_code"] = completed.returncode
    result["ok"] = completed.returncode == 0
    result["duration_ms"] = elapsed_ms(start)
    if not result["ok"]:
        result["error"] = result.get("output_encoding_warning") or result["stderr"] or result["stdout"] or "command failed"
    return result


def ensure_text(value):
    if value is None:
        return ""
    if isinstance(value, bytes):
        return robust_decode_bytes(value)["text"]
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


def powershell_invocation_arg(value):
    text = str(value)
    if re.match(r"^-[A-Za-z][A-Za-z0-9-]*$", text):
        return text
    return powershell_quote_arg(text)


POWERSHELL_UTF8_PRELUDE = (
    "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false); "
    "$OutputEncoding = [System.Text.UTF8Encoding]::new($false); "
)


def powershell_inline_command(script):
    return [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        POWERSHELL_UTF8_PRELUDE + "\n" + script,
    ]


def powershell_file_command(script, args=None):
    invocation = "& " + powershell_quote_arg(script)
    for arg in list(args or []):
        invocation += " " + powershell_invocation_arg(arg)
    return powershell_inline_command(invocation)


def elevated_powershell_command(working_directory, script_args):
    script_args = list(script_args)
    if "-File" in script_args:
        index = script_args.index("-File")
        if index + 1 < len(script_args):
            script = script_args[index + 1]
            file_args = script_args[index + 2 :]
            invocation = "& " + powershell_quote_arg(script)
            for arg in file_args:
                invocation += " " + powershell_invocation_arg(arg)
            script_args = script_args[:index] + ["-Command", POWERSHELL_UTF8_PRELUDE + "\n" + invocation]
    elif "-Command" in script_args:
        index = script_args.index("-Command")
        if index + 1 < len(script_args):
            script_args[index + 1] = POWERSHELL_UTF8_PRELUDE + "\n" + script_args[index + 1]
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
    decoded = robust_decode_bytes(data)
    payload = {
        "ok": True,
        "path": str(path),
        "text": "\n".join(decoded["text"].splitlines()[-lines:]),
        "encoding_used": decoded["encoding_used"],
    }
    if decoded["replacement_used"]:
        payload["output_encoding_warning"] = "Command output encoding error. Output was decoded with replacement characters."
    elif decoded["fallback_used"]:
        payload["output_encoding_note"] = "Command output was decoded with a fallback encoding."
    return payload


def run_powershell_json(script, timeout_seconds, parse_error_label, empty_payload):
    command = powershell_inline_command(script)
    result = run_subprocess(command, timeout_seconds=timeout_seconds)
    if not result.get("ok"):
        payload = {"ok": False, "error": result.get("error") or result.get("stderr") or result.get("stdout") or "PowerShell command failed", **empty_payload}
        payload["command_result"] = summarize_for_log(result)
        return payload
    try:
        payload = json.loads(result.get("stdout") or "{}")
    except json.JSONDecodeError as exc:
        payload = {"ok": False, "error": parse_error_label + ": " + str(exc), "raw": result.get("stdout", ""), **empty_payload}
        payload["command_result"] = summarize_for_log(result)
        return payload
    if not isinstance(payload, dict):
        payload = {"ok": False, "error": parse_error_label + ": JSON root is not an object", "raw": result.get("stdout", ""), **empty_payload}
        payload["command_result"] = summarize_for_log(result)
        return payload
    payload["ok"] = True
    payload["command_result"] = summarize_for_log(result)
    return payload


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
    return run_powershell_json(script, 15, "snapshot JSON parse failed", {"services": [], "processes": []})


def ownership_probe_snapshot():
    process_list = ",".join(json.dumps(name) for name in OWNERSHIP_PROCESS_NAMES)
    service_list = ",".join(json.dumps(name) for name in KNOWN_SERVICES)
    script = f"""
$serviceNames = @({service_list})
$processNames = @({process_list})
$allServices = @(Get-CimInstance Win32_Service -ErrorAction SilentlyContinue)
$services = @()
$seenServices = @{{}}
foreach ($name in $serviceNames) {{
  $matches = @($allServices | Where-Object {{ $_.Name -eq $name -or $_.DisplayName -eq $name }})
  if ($matches.Count -gt 0) {{
    foreach ($svc in $matches) {{
      if ($seenServices.ContainsKey($svc.Name)) {{ continue }}
      $seenServices[$svc.Name] = $true
      $services += [pscustomobject]@{{
        name = $svc.Name
        display_name = $svc.DisplayName
        query = $name
        exists = $true
        state = $svc.State
        status = $svc.Status
        start_mode = $svc.StartMode
        process_id = $svc.ProcessId
        account = $svc.StartName
        path = $svc.PathName
      }}
    }}
  }} else {{
    $services += [pscustomobject]@{{
      name = $name
      display_name = $null
      query = $name
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
$lighting = $services | Where-Object {{ $_.name -eq "LightingService" }} | Select-Object -First 1
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
      exists = $lighting.exists
      state = $lighting.State
      status = $lighting.Status
      process_id = $lighting.process_id
      account = $lighting.account
      path = $lighting.path
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
  services = $services
  processes = $processes
}} | ConvertTo-Json -Depth 6
"""
    return run_powershell_json(script, 8, "ownership JSON parse failed", {"services": [], "processes": []})


def ownership_marker_path(project_root):
    return Path(project_root) / ".sylphie" / "ownership_mode.json"


def read_ownership_marker(project_root):
    path = ownership_marker_path(project_root)
    if not path.is_file():
        return {"mode": "unknown"}
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {"mode": "unknown"}
    if not isinstance(payload, dict):
        return {"mode": "unknown"}
    return payload


def write_ownership_marker(project_root, mode, reason):
    path = ownership_marker_path(project_root)
    try:
        ensure_dir(path.parent)
        with path.open("w", encoding="utf-8") as handle:
            json.dump({"mode": mode, "reason": reason, "updated_at": time.time()}, handle, separators=(",", ":"))
    except OSError:
        pass


def service_running(item):
    if not item or not item.get("exists"):
        return False
    state = str(item.get("state") or "").lower()
    try:
        pid = int(item.get("process_id") or item.get("pid") or 0)
    except (TypeError, ValueError):
        pid = 0
    return state == "running" or pid > 0


def takeover_last_result(payload):
    response = (payload or {}).get("response") or {}
    state = response.get("state") or {}
    return state.get("last_result") or response.get("last_result") or response or payload or {}


def takeover_made_changes(payload):
    result = takeover_last_result(payload)
    stopped = result.get("stopped_services") or []
    killed = result.get("terminated_process_pids") or []
    reports = result.get("reports") or []
    meaningful_reports = [
        item for item in reports
        if "Ownership already clean; no stop actions required." not in str(item)
    ]
    return bool(stopped or killed or meaningful_reports)


def ownership_clean_details(agent_status, probe):
    agent_response = agent_status.get("response") or {}
    agent_state = agent_response.get("state") or {}
    agent_blockers = agent_state.get("blocking_conflicts") or []
    tier1_services = running_service_labels(probe, TIER1_SERVICE_NAMES)
    tier2_services = running_service_labels(probe, TIER2_SERVICE_NAMES)
    tier1_processes = blocking_owner_processes_when_agent_offline(probe)
    tier2_processes = warning_only_armoury_processes(probe)
    blocking = list(agent_blockers) + tier1_services + tier1_processes
    core_running = tier2_services + tier2_processes
    return {
        "clean": not blocking and not core_running,
        "blocking": blocking,
        "tier1_services": tier1_services,
        "tier1_processes": tier1_processes,
        "tier2_services": tier2_services,
        "tier2_processes": tier2_processes,
        "core_running": core_running,
    }


def mark_takeover_result(project_root, payload, include_armoury_core, agent_status=None, probe=None):
    if not payload.get("ok"):
        return payload
    result = takeover_last_result(payload)
    manual = result.get("manual_action_required") or []
    if manual:
        payload["ownership_marker_written"] = False
        payload["ownership_message"] = "Takeover cannot complete automatically because some blocking conflicts require manual action"
        return payload
    if not takeover_made_changes(payload):
        details = ownership_clean_details(agent_status or {}, probe or {})
        result["stopped_services"] = result.get("stopped_services") or []
        result["terminated_process_pids"] = result.get("terminated_process_pids") or []
        result["reports"] = result.get("reports") or []
        if details["clean"]:
            if "Ownership already clean; no stop actions required." not in result["reports"]:
                result["reports"].append("Ownership already clean; no stop actions required.")
            result["takeover_completeness"] = "already_clean"
            result["ownership_candidate"] = True
            write_ownership_marker(project_root, "sylphie_candidate", "takeover execute found ownership already clean")
            payload["ownership_marker_written"] = True
            payload["ownership_mode"] = "sylphie_candidate"
            payload["ownership_candidate"] = True
            payload["takeover_completeness"] = "already_clean"
            payload["ownership_message"] = "No changes required; ownership already clean. Run direct sanity test to verify visual control."
        else:
            write_ownership_marker(project_root, "takeover_noop", "takeover execute made no changes and blockers remain")
            payload["ownership_marker_written"] = True
            payload["ownership_mode"] = "takeover_noop"
            payload["takeover_completeness"] = "no_changes_blocked"
            if details["core_running"]:
                payload["ownership_message"] = "Takeover made no changes and Armoury core still running."
            else:
                payload["ownership_message"] = "Takeover made no changes and blockers remain."
            payload["ownership_blockers_after_noop"] = details
        return payload
    mode = "sylphie_candidate" if include_armoury_core else "soft_takeover"
    write_ownership_marker(project_root, mode, "takeover execute changed ownership candidates")
    payload["ownership_marker_written"] = True
    payload["ownership_mode"] = mode
    return payload


def process_base_names(probe):
    return sorted({str(item.get("base_name") or item.get("name") or "").lower() for item in (probe.get("processes") or [])})


def running_service_names(probe):
    running = set()
    for item in probe.get("services") or []:
        if not service_running(item):
            continue
        name = str(item.get("name") or "").lower()
        display_name = str(item.get("display_name") or "").lower()
        if name:
            running.add(name)
        if display_name:
            running.add(display_name)
    return running


def running_service_labels(probe, name_set):
    labels = []
    for item in probe.get("services") or []:
        if not service_running(item):
            continue
        name = str(item.get("name") or "")
        display_name = str(item.get("display_name") or "")
        if name.lower() in name_set or display_name.lower() in name_set:
            labels.append(name if not display_name else f"{name} ({display_name})")
    return sorted(set(labels))


def warning_only_armoury_processes(probe):
    names = process_base_names(probe)
    return [name for name in names if name in TIER2_PROCESS_NAMES]


def blocking_owner_processes_when_agent_offline(probe):
    names = process_base_names(probe)
    return [name for name in names if name in TIER1_PROCESS_NAMES]


def takeover_marker_mode(marker_mode):
    marker = str(marker_mode or "unknown").lower()
    aliases = {
        "sylphie": "sylphie_candidate",
        "sylphie-candidate": "sylphie_candidate",
        "sylphie_candidate": "sylphie_candidate",
        "sylphie-verified": "sylphie_verified",
        "sylphie_verified": "sylphie_verified",
        "soft-takeover": "soft_takeover",
        "soft_takeover": "soft_takeover",
        "takeover-noop": "takeover_noop",
        "takeover_noop": "takeover_noop",
    }
    return aliases.get(marker, marker)


def derive_ownership_mode(capture_running, agent_status, probe, marker_mode):
    reasons = []
    marker = takeover_marker_mode(marker_mode)
    agent_running = bool(agent_status.get("ok"))
    agent_response = agent_status.get("response") or {}
    agent_state = agent_response.get("state") or {}
    agent_elevated = bool(agent_state.get("is_elevated"))
    agent_owner_status = str(agent_state.get("current_owner_status") or "unknown")
    agent_blockers = agent_state.get("blocking_conflicts") or []
    agent_warnings = agent_state.get("warnings") or []
    lighting = probe.get("lighting_service") or {}
    lighting_running = service_running(lighting)
    running_services = running_service_names(probe)
    tier1_services = running_service_labels(probe, TIER1_SERVICE_NAMES)
    tier2_services = running_service_labels(probe, TIER2_SERVICE_NAMES)
    ignored_services = running_service_labels(probe, IGNORED_SERVICE_NAMES)
    offline_blocking_processes = blocking_owner_processes_when_agent_offline(probe)
    warning_processes = warning_only_armoury_processes(probe)
    informational_processes = []

    if capture_running:
        reasons.append("research capture is running")
        if agent_running:
            reasons.append("Sylphie agent is also running during capture")
            return {
                "mode": "conflict",
                "reasons": reasons,
                "write_allowed": False,
                "blocking_conflicts": ["Sylphie agent is running during research capture"],
                "warnings": agent_warnings,
                "informational_processes": informational_processes,
            }
        return {
            "mode": "research",
            "reasons": reasons,
            "write_allowed": False,
            "blocking_conflicts": [],
            "warnings": [],
            "informational_processes": informational_processes,
        }

    if agent_running:
        reasons.append("Sylphie agent is responding")
        if not agent_elevated:
            reasons.append("Sylphie agent is not elevated")
            return {
                "mode": "conflict",
                "reasons": reasons,
                "write_allowed": False,
                "blocking_conflicts": ["Sylphie agent is not elevated"],
                "warnings": agent_warnings,
                "informational_processes": informational_processes,
            }
        if agent_blockers:
            reasons.append("Blocking conflicts reported by agent")
            return {
                "mode": "conflict",
                "reasons": reasons,
                "write_allowed": False,
                "blocking_conflicts": agent_blockers,
                "warnings": agent_warnings,
                "informational_processes": informational_processes,
            }
        if tier1_services or offline_blocking_processes:
            if tier1_services:
                reasons.append("Tier1 lighting services running: " + ", ".join(tier1_services))
            if offline_blocking_processes:
                reasons.append("Tier1 lighting processes running: " + ", ".join(offline_blocking_processes))
            return {
                "mode": "conflict",
                "reasons": reasons,
                "write_allowed": False,
                "blocking_conflicts": tier1_services + offline_blocking_processes,
                "warnings": agent_warnings,
                "informational_processes": ignored_services,
            }
        if agent_warnings:
            reasons.append("Warning-only Armoury processes detected: " + "; ".join(agent_warnings))
        if tier2_services:
            reasons.append("Armoury core services still running: " + ", ".join(tier2_services))
        if warning_processes:
            reasons.append("Warning-only Armoury processes detected: " + ", ".join(warning_processes))
            informational_processes = warning_processes
        if ignored_services:
            informational_processes = sorted(set(informational_processes + ignored_services))
        if any("ArmouryCrate.exe" in item or "ArmouryCrate " in item for item in agent_warnings):
            reasons.append("Armoury UI is still open.")
        tier2_running = bool(tier2_services or warning_processes)
        claim_available = agent_elevated and not tier2_running and not tier1_services and not offline_blocking_processes and not agent_blockers
        if marker == "takeover_noop" and tier2_running:
            reasons.extend([
                "Takeover made no changes and Armoury core still running",
                "RGB writes remain blocked until full takeover or manual override",
            ])
            mode = "takeover-noop"
            write_allowed = False
            sanity_write_allowed = False
        elif marker == "takeover_noop":
            reasons.extend([
                "No changes required; ownership already clean.",
                "Ownership is clean. Run direct sanity test to verify visual control.",
            ])
            mode = "ready-clean"
            write_allowed = False
            sanity_write_allowed = False
        elif tier2_running:
            mode = "soft-takeover" if marker in {"soft_takeover", "sylphie_candidate", "sylphie_verified"} else "ready-warning"
            write_allowed = False
            sanity_write_allowed = False
        elif marker == "sylphie_verified":
            mode = "sylphie-verified"
            write_allowed = True
            sanity_write_allowed = True
        elif marker in {"sylphie_candidate", "soft_takeover"}:
            mode = "sylphie-candidate"
            write_allowed = False
            sanity_write_allowed = True
            reasons.append("Ownership is clean. Run direct sanity test to verify visual control.")
        else:
            mode = "ready-clean" if claim_available else ("ready-warning" if agent_owner_status == "warning" else "ready")
            write_allowed = False
            sanity_write_allowed = False
            if claim_available:
                reasons.append("Ownership is clean. Claim clean ownership to start direct sanity verification.")
        if not write_allowed and marker not in {"takeover_noop", "soft_takeover", "sylphie_candidate"}:
            reasons.append("Takeover for Sylphie has not completed in this session")
        return {
            "mode": mode,
            "reasons": reasons,
            "write_allowed": write_allowed,
            "sanity_write_allowed": sanity_write_allowed,
            "claim_available": claim_available,
            "blocking_conflicts": [],
            "warnings": sorted(set(agent_warnings + tier2_services + warning_processes)),
            "informational_processes": informational_processes,
        }

    if lighting_running or tier1_services or offline_blocking_processes or warning_processes or tier2_services:
        if lighting_running or tier1_services:
            reasons.append("Tier1 lighting services running: " + ", ".join(tier1_services or ["LightingService"]))
        if offline_blocking_processes:
            reasons.append("Armoury owner processes detected: " + ", ".join(offline_blocking_processes))
        if tier2_services:
            reasons.append("Armoury core services running: " + ", ".join(tier2_services))
        if warning_processes:
            reasons.append("Warning-only Armoury processes detected: " + ", ".join(warning_processes))
        return {
            "mode": "armoury",
            "reasons": reasons,
            "write_allowed": False,
            "blocking_conflicts": [],
            "warnings": sorted(set(tier2_services + warning_processes)),
            "informational_processes": ignored_services,
        }

    reasons.append("no clear Armoury or Sylphie owner detected")
    return {
        "mode": "unknown",
        "reasons": reasons,
        "write_allowed": False,
        "blocking_conflicts": [],
        "warnings": [],
        "informational_processes": [],
    }


def armoury_health_snapshot():
    service_list = ",".join(json.dumps(name) for name in ARMOURY_HEALTH_SERVICES)
    pattern_list = ",".join(json.dumps(name) for name in ARMOURY_HEALTH_PROCESS_PATTERNS)
    script = f"""
$serviceNames = @({service_list})
$processPatterns = @({pattern_list})
$allServices = @(Get-CimInstance Win32_Service -ErrorAction SilentlyContinue)
$services = @()
$seenServices = @{{}}
foreach ($name in $serviceNames) {{
  $matches = @($allServices | Where-Object {{ $_.Name -eq $name -or $_.DisplayName -eq $name }})
  if ($matches.Count -gt 0) {{
    foreach ($svc in $matches) {{
    if ($seenServices.ContainsKey($svc.Name)) {{ continue }}
    $seenServices[$svc.Name] = $true
    $services += [pscustomobject]@{{
      name = $svc.Name
      display_name = $svc.DisplayName
      query = $name
      exists = $true
      state = $svc.State
      status = $svc.Status
      start_mode = $svc.StartMode
      process_id = $svc.ProcessId
      account = $svc.StartName
      path = $svc.PathName
    }}
    }}
  }} else {{
    $services += [pscustomobject]@{{
      name = $name
      display_name = $null
      query = $name
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
      parent_pid = $_.ParentProcessId
      matched_rules = $matches
      executable_path = $_.ExecutablePath
      command_line = $_.CommandLine
    }}
  }}
}}
$processGroups = @()
$processes | Group-Object -Property base_name | ForEach-Object {{
  $items = @($_.Group)
  $first = $items[0]
  $processGroups += [pscustomobject]@{{
    base_name = $_.Name
    name = $first.name
    count = $items.Count
    example_path = $first.executable_path
    parent_pids = @($items | ForEach-Object {{ $_.parent_pid }} | Sort-Object -Unique)
    pids_sample = @($items | ForEach-Object {{ $_.pid }} | Select-Object -First 5)
    matched_rules = @($items | ForEach-Object {{ $_.matched_rules }} | Sort-Object -Unique)
    is_logitech_download_assistant = ($_.Name -like "logi_download_assistant*")
  }}
}}
$logiStorm = @($processes | Where-Object {{ $_.base_name -like "logi_download_assistant*" }})
[pscustomobject]@{{
  ok = $true
  captured_at = (Get-Date).ToString("o")
  warning = "Music mode depends on Armoury addons/audio pipeline, not only SMBus RGB."
  services = $services
  process_patterns = $processPatterns
  process_groups = $processGroups
  processes = $processes
  logi_download_assistant_count = $logiStorm.Count
  logi_download_assistant_storm = $logiStorm.Count -gt 3
}} | ConvertTo-Json -Depth 8
"""
    return run_powershell_json(script, 15, "Armoury health JSON parse failed", {"services": [], "processes": []})


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
      parent_pid = $_.ParentProcessId
      matched_rules = $matches
      executable_path = $_.ExecutablePath
      command_line = $_.CommandLine
    }}
  }}
}}
$processGroups = @()
$processes | Group-Object -Property base_name | ForEach-Object {{
  $items = @($_.Group)
  $first = $items[0]
  $processGroups += [pscustomobject]@{{
    base_name = $_.Name
    name = $first.name
    count = $items.Count
    example_path = $first.executable_path
    parent_pids = @($items | ForEach-Object {{ $_.parent_pid }} | Sort-Object -Unique)
    pids_sample = @($items | ForEach-Object {{ $_.pid }} | Select-Object -First 5)
    matched_rules = @($items | ForEach-Object {{ $_.matched_rules }} | Sort-Object -Unique)
    is_logitech_download_assistant = ($_.Name -like "logi_download_assistant*")
  }}
}}
$logiStorm = @($processes | Where-Object {{ $_.base_name -like "logi_download_assistant*" }})
[pscustomobject]@{{
  ok = $true
  captured_at = (Get-Date).ToString("o")
  warning = "Music mode depends on Armoury/audio capture pipeline, not only SMBus RGB control."
  services = $services
  process_patterns = $processPatterns
  process_groups = $processGroups
  processes = $processes
  logi_download_assistant_count = $logiStorm.Count
  logi_download_assistant_storm = $logiStorm.Count -gt 3
}} | ConvertTo-Json -Depth 8
"""
    return run_powershell_json(script, 15, "audio/reactive JSON parse failed", {"services": [], "processes": []})


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
        "stop-logitech-lamparray-temporary": """
  $svc = Get-Service -Name "logi_lamparray_service" -ErrorAction SilentlyContinue
  if ($null -eq $svc) {
    Write-SylphieAudioReactiveLog "logi_lamparray_service not found"
  } else {
    Write-SylphieAudioReactiveLog "Stopping logi_lamparray_service without changing StartupType"
    Stop-Service -Name "logi_lamparray_service" -Force -ErrorAction SilentlyContinue
  }
  Get-Process -Name "logi_download_assistant*" -ErrorAction SilentlyContinue | ForEach-Object {
    Write-SylphieAudioReactiveLog ("Killing " + $_.ProcessName + " pid=" + $_.Id)
    Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
  }
""",
        "set-logitech-lamparray-manual": """
  $svc = Get-Service -Name "logi_lamparray_service" -ErrorAction SilentlyContinue
  if ($null -eq $svc) {
    Write-SylphieAudioReactiveLog "logi_lamparray_service not found"
  } else {
    Write-SylphieAudioReactiveLog "Setting logi_lamparray_service StartupType=Manual and stopping it"
    Set-Service -Name "logi_lamparray_service" -StartupType Manual
    Stop-Service -Name "logi_lamparray_service" -Force -ErrorAction SilentlyContinue
  }
  Get-Process -Name "logi_download_assistant*" -ErrorAction SilentlyContinue | ForEach-Object {
    Write-SylphieAudioReactiveLog ("Killing " + $_.ProcessName + " pid=" + $_.Id)
    Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
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
                elif path == "/api/sanity/set":
                    rgb = normalize_rgb(body.get("rgb"))
                    status, result = server_state.run_hardware_command(["set", rgb], rgb=rgb, allow_sanity=True)
                elif path == "/api/sanity/off":
                    status, result = server_state.run_hardware_command(["off"], rgb="000000", scene="off", allow_sanity=True)
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
                    include_armoury_core = bool(body.get("include_armoury_core", False))
                    payload = {
                        "id": str(uuid.uuid4()),
                        "cmd": "takeover_execute",
                        "i_accept_stopping_lighting_services": bool(body.get("i_accept_stopping_lighting_services", False)),
                        "include_armoury_core": include_armoury_core,
                    }
                    result = server_state.run_agent_payload(payload, timeout_seconds=20, command=["agent", "takeover_execute"])
                    post_status = server_state.run_agent_payload({"id": str(uuid.uuid4()), "cmd": "status"}, timeout_seconds=2, command=["agent", "status"])
                    post_probe = ownership_probe_snapshot()
                    result = mark_takeover_result(server_state.project_root, result, include_armoury_core, post_status, post_probe)
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
                    result = server_state.run_ownership_action(
                        "takeover-for-sylphie",
                        include_armoury_core=bool(body.get("include_armoury_core", False)),
                    )
                    status = 200 if result["ok"] else 500
                elif path == "/api/ownership/mark-verified":
                    write_ownership_marker(server_state.project_root, "sylphie_verified", "direct RGB sanity test visually confirmed")
                    result = {"ok": True, "mode": "sylphie_verified"}
                    status = 200
                elif path == "/api/ownership/claim-clean":
                    status, result = server_state.claim_clean_ownership()
                elif path == "/api/diagnostics/audio-reactive/restart-lighting":
                    status, result = server_state.run_audio_reactive_action("restart-lighting-service")
                elif path == "/api/diagnostics/audio-reactive/restart-windows-audio":
                    status, result = server_state.run_audio_reactive_action("restart-windows-audio")
                elif path == "/api/diagnostics/audio-reactive/restore-logitech-lamparray":
                    status, result = server_state.run_audio_reactive_action("restore-logitech-lamparray")
                elif path == "/api/diagnostics/audio-reactive/stop-logitech-lamparray-temporary":
                    status, result = server_state.run_audio_reactive_action("stop-logitech-lamparray-temporary")
                elif path == "/api/diagnostics/audio-reactive/set-logitech-lamparray-manual":
                    status, result = server_state.run_audio_reactive_action("set-logitech-lamparray-manual")
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
                        include_armoury_core = bool(body.get("include_armoury_core", False))
                        payload = {
                            "id": str(uuid.uuid4()),
                            "cmd": "takeover_execute",
                            "i_accept_stopping_lighting_services": bool(body.get("accept", False)),
                            "include_armoury_core": include_armoury_core,
                        }
                        result = server_state.run_agent_payload(payload, timeout_seconds=20, command=["agent", "takeover_execute"])
                        post_status = server_state.run_agent_payload({"id": str(uuid.uuid4()), "cmd": "status"}, timeout_seconds=2, command=["agent", "status"])
                        post_probe = ownership_probe_snapshot()
                        result = mark_takeover_result(server_state.project_root, result, include_armoury_core, post_status, post_probe)
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
