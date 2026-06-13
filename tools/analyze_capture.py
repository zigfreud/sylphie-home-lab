#!/usr/bin/env python3
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timedelta
import json
from pathlib import Path
import re
import sys


SELECT_RE = re.compile(r"AURA select_register (0x[0-9A-Fa-f]{4})")
BLOCK_RE = re.compile(r"AURA block_write last_selected_register=(\S+) len=(\d+)(.*)")
PAYLOAD_RE = re.compile(r"payload_reads=([0-9A-Fa-f ]+)(?: \[extra=([0-9A-Fa-f]{2})\])?")
BYTE_RE = re.compile(
    r"AURA byte_write value=(0x[0-9A-Fa-f]{2}) last_selected_register=(\S+)"
    r"(?: d1_hint_register=(0x[0-9A-Fa-f]{4}))?(?: confidence=(\S+))?"
)
READ_RE = re.compile(r"AURA read CMD=(0x[0-9A-Fa-f]{2})")
TIMESTAMP_RE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:\.\d{3})?)")
RECENT_SELECTS_RE = re.compile(r"recent_selects=(\[[^\]]*\])")
CONFIDENCE_RE = re.compile(r"confidence=(\S+)")

WATCH_REGISTERS = {
    "0X8020",
    "0X8021",
    "0X8022",
    "0X8023",
    "0X8025",
    "0X8027",
    "0X80A0",
    "0X80B0",
    "0X80F1",
    "0X8101",
}

TIMELINE_KEYS = [
    "CAPTURE_START",
    "STACK_ALREADY_STOPPED_AT_CAPTURE_START",
    "RED_STUCK_STATE",
    "COLOR_PICKER_CHANGED_RED",
    "COLOR_PICKER_CHANGED_GREEN",
    "COLOR_PICKER_CHANGED_BLUE",
    "MOUSE_COLOR_SELECTED_GREEN",
    "COLOR_VISUALLY_CHANGED",
    "POPUP_OK_CLICKED",
    "SERVICE_STARTED",
    "ARMOURY_LAUNCHED",
    "FIRST_LIGHT",
    "OK_CLICKED",
]


def read_text(path):
    return Path(path).read_text(encoding="utf-8", errors="replace").splitlines()


def parse_timestamp(value):
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            pass
    return None


def timestamp_text(value):
    if value is None:
        return "unknown"
    return value.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def line_timestamp(line):
    match = TIMESTAMP_RE.match(line)
    return parse_timestamp(match.group(1)) if match else None


def marker_name(line):
    if "MARKER " in line:
        return line.split("MARKER ", 1)[1].split(" note=", 1)[0].strip().upper()
    if "CAPTURE_START_SNAPSHOT" in line:
        return "CAPTURE_START_SNAPSHOT"
    if "CAPTURE_START" in line:
        return "CAPTURE_START"
    return None


def nearby_marker_log(path):
    path = Path(path)
    candidates = []
    name = path.name
    if name.endswith("_master.log"):
        candidates.append(path.with_name(name.replace("_master.log", "_markers.log")))
        candidates.append(path.with_name("markers_" + name.split("_", 2)[-1].replace("_master.log", ".log")))
    return [p for p in candidates if p.is_file()]


def register_matches_watch(item):
    return {item.get("selected"), item.get("hint")}.intersection(WATCH_REGISTERS)


def in_window(item, start, end):
    ts = item.get("timestamp")
    return ts is not None and start is not None and end is not None and start <= ts <= end


def format_block(item):
    payload = f" payload={item['payload']}" if item.get("payload") else ""
    extra = f" extra={item['extra']}" if item.get("extra") else ""
    recent = f" recent_selects={item['recent_selects']}" if item.get("recent_selects") else ""
    confidence = f" confidence={item['confidence']}" if item.get("confidence") else ""
    return f"{timestamp_text(item.get('timestamp'))} {item['register']} len={item['len']}{payload}{extra}{recent}{confidence}"


def format_byte(item):
    hint = f" hint={item['hint']}" if item.get("hint") else ""
    confidence = f" confidence={item['confidence']}" if item.get("confidence") else ""
    return f"{timestamp_text(item.get('timestamp'))} value={item['value']} selected={item['selected']}{hint}{confidence}"


def format_read(item):
    return f"{timestamp_text(item.get('timestamp'))} CMD={item['cmd']}"


def select_window(events, start, end):
    return [item for item in events if in_window(item, start, end)]


def select_watched_bytes(events, start, end):
    return [item for item in events if in_window(item, start, end) and register_matches_watch(item)]


def first_marker(marker_times, *names):
    for name in names:
        values = marker_times.get(name)
        if values:
            return values[0]
    return None


def load_logs(master_paths, marker_paths):
    lines = []
    marker_lines = []
    marker_files = []
    for raw in master_paths:
        path = Path(raw)
        if path.is_dir():
            for item in sorted(path.glob("*.log")):
                lines.extend(read_text(item))
            continue
        lines.extend(read_text(path))
        for marker in nearby_marker_log(path):
            marker_files.append(marker.resolve())
    for marker_path in marker_paths:
        marker_files.append(Path(marker_path).resolve())
    for marker in sorted(set(marker_files)):
        marker_lines.extend(read_text(marker))
    return lines, marker_lines


def analyze(master_paths, marker_paths=None):
    marker_paths = marker_paths or []
    lines, marker_lines = load_logs(master_paths, marker_paths)
    selected_registers = Counter()
    block_writes = []
    byte_writes = []
    reads = []
    payloads = []
    markers = []
    marker_times = defaultdict(list)
    timeline = defaultdict(list)
    current_ts = None
    current_select = None

    for line in lines:
        ts = line_timestamp(line)
        if ts:
            current_ts = ts

        select_match = SELECT_RE.search(line)
        if select_match:
            current_select = select_match.group(1).upper()
            selected_registers[current_select] += 1

        read_match = READ_RE.search(line)
        if read_match:
            cmd = read_match.group(1).upper()
            if cmd in ("0X81", "0X90"):
                reads.append({"timestamp": current_ts, "cmd": cmd, "line": line})

        block_match = BLOCK_RE.search(line)
        if block_match:
            reg = block_match.group(1).upper()
            length = int(block_match.group(2), 10)
            tail = block_match.group(3)
            payload_match = PAYLOAD_RE.search(tail)
            recent_match = RECENT_SELECTS_RE.search(tail)
            confidence_match = CONFIDENCE_RE.search(tail)
            payload = payload_match.group(1).strip().upper() if payload_match else None
            extra = payload_match.group(2).upper() if payload_match and payload_match.group(2) else None
            item = {
                "timestamp": current_ts,
                "register": reg,
                "len": length,
                "payload": payload,
                "extra": extra,
                "recent_selects": recent_match.group(1) if recent_match else None,
                "confidence": confidence_match.group(1) if confidence_match else ("selected" if reg != "UNKNOWN" else "unknown"),
                "line": line,
            }
            block_writes.append(item)
            if payload:
                payloads.append(item)

        byte_match = BYTE_RE.search(line)
        if byte_match:
            value = byte_match.group(1).upper()
            selected = byte_match.group(2).upper()
            hint = (byte_match.group(3) or "").upper()
            confidence = byte_match.group(4)
            if not confidence:
                confidence = "ambiguous" if hint and hint != selected else "selected"
            byte_writes.append(
                {
                    "timestamp": current_ts,
                    "value": value,
                    "selected": selected,
                    "hint": hint,
                    "confidence": confidence,
                    "line": line,
                }
            )

        if "MARKER " in line or "CAPTURE_START" in line:
            marker_lines.append(line)

    for line in marker_lines:
        if "MARKER " not in line and "CAPTURE_START" not in line:
            continue
        ts = line_timestamp(line)
        name = marker_name(line)
        markers.append(line)
        if name and ts:
            marker_times[name].append(ts)
        for key in TIMELINE_KEYS:
            if key in line:
                timeline[key].append(timestamp_text(ts))

    picker_green = first_marker(marker_times, "COLOR_PICKER_CHANGED_GREEN", "MOUSE_COLOR_SELECTED_GREEN")
    visual_change = first_marker(marker_times, "COLOR_VISUALLY_CHANGED")
    popup_ok = first_marker(marker_times, "POPUP_OK_CLICKED", "OK_CLICKED")
    windows = {}
    if picker_green:
        windows["10s_before_color_picker_changed_green"] = (picker_green - timedelta(seconds=10), picker_green)
    if picker_green and visual_change:
        windows["color_picker_changed_green_to_visual_change"] = (picker_green, visual_change)
    if visual_change:
        windows["5s_after_visual_change"] = (visual_change, visual_change + timedelta(seconds=5))
    if visual_change and popup_ok:
        windows["visual_change_to_popup_ok"] = (visual_change, popup_ok)

    window_results = {}
    for name, (start, end) in windows.items():
        window_results[name] = {
            "start": timestamp_text(start),
            "end": timestamp_text(end),
            "block_writes": select_window(block_writes, start, end),
            "watched_byte_writes": select_watched_bytes(byte_writes, start, end),
            "reads_81_90": select_window(reads, start, end),
        }

    transition_blocks = window_results.get("color_picker_changed_green_to_visual_change", {}).get("block_writes", [])
    transition_bytes = window_results.get("color_picker_changed_green_to_visual_change", {}).get("watched_byte_writes", [])
    before_visual_blocks = []
    if visual_change:
        before_visual_blocks = [item for item in block_writes if item.get("timestamp") and item["timestamp"] <= visual_change][-5:]
    before_visual_bytes = []
    if visual_change:
        before_visual_bytes = [item for item in byte_writes if item.get("timestamp") and item["timestamp"] <= visual_change and register_matches_watch(item)][-8:]

    return {
        "selected_registers": dict(selected_registers),
        "block_writes": block_writes,
        "payloads": payloads,
        "watched_byte_writes": [item for item in byte_writes if register_matches_watch(item)],
        "reads_81_90": reads,
        "timeline": {key: timeline.get(key, []) for key in TIMELINE_KEYS},
        "markers": markers,
        "red_stuck_to_green": {
            "markers_complete": bool(picker_green and visual_change),
            "color_picker_changed_green": timestamp_text(picker_green),
            "color_visually_changed": timestamp_text(visual_change),
            "popup_ok_clicked": timestamp_text(popup_ok),
            "windows": window_results,
            "candidate_transition_block_writes": transition_blocks,
            "candidate_mode_commit_byte_writes": transition_bytes,
            "immediately_before_visual_change": {
                "block_writes": before_visual_blocks,
                "watched_byte_writes": before_visual_bytes,
            },
        },
        "comparison": {
            "known_good_direct_path": [
                "0x8020=0x01",
                "0x80A0=0x01",
                "block 0x8101 RGB payload R G B",
                "0x80A0=0x01",
            ],
            "known_armoury_ui_rgb_path": [
                "0x80F1 block payload RGB was observed in prior UI capture",
            ],
        },
        "conclusion": build_conclusion(transition_blocks, transition_bytes, visual_change),
    }


def build_conclusion(transition_blocks, transition_bytes, visual_change):
    clear_block = [item for item in transition_blocks if item.get("payload")]
    if visual_change and clear_block:
        next_test = "Review transition block writes and adjacent byte writes before any microtest; do not implement recover-full yet."
    elif visual_change and transition_bytes:
        next_test = "Recapture with high-rate enabled again; current data has candidate mode/commit byte writes but no transition block payload."
    else:
        next_test = "Repeat RED_STUCK_TO_GREEN_CAPTURE; markers or transition writes are insufficient."
    return {
        "candidate transition block writes": [format_block(item) for item in transition_blocks],
        "candidate mode/commit byte writes": [format_byte(item) for item in transition_bytes],
        "recommended next microtest": next_test,
        "do not implement recover-full yet": True,
    }


def write_red_stuck_summary(result, summary_dir):
    summary_dir = Path(summary_dir)
    summary_dir.mkdir(parents=True, exist_ok=True)
    path = summary_dir / (datetime.now().strftime("%Y%m%d") + "_red_stuck_to_green_summary.md")
    red = result["red_stuck_to_green"]
    lines = [
        "# RED_STUCK_TO_GREEN Capture Summary",
        "",
        "Raw captures remain local under `research/captures/` and are not committed.",
        "",
        "## Timeline",
        "",
    ]
    for key in ("RED_STUCK_STATE", "COLOR_PICKER_CHANGED_GREEN", "MOUSE_COLOR_SELECTED_GREEN", "COLOR_VISUALLY_CHANGED", "POPUP_OK_CLICKED"):
        values = result["timeline"].get(key) or []
        lines.append(f"- {key}: {', '.join(values) if values else 'not observed'}")

    lines += [
        "",
        "## Analysis Windows",
        "",
    ]
    for name, window in red["windows"].items():
        lines.append(f"### {name}")
        lines.append("")
        lines.append(f"- start: `{window['start']}`")
        lines.append(f"- end: `{window['end']}`")
        lines.append("")
        lines.append("Block writes:")
        if not window["block_writes"]:
            lines.append("- none")
        for item in window["block_writes"]:
            lines.append(f"- `{format_block(item)}`")
        lines.append("")
        lines.append("Watched byte writes:")
        if not window["watched_byte_writes"]:
            lines.append("- none")
        for item in window["watched_byte_writes"]:
            lines.append(f"- `{format_byte(item)}`")
        lines.append("")
        lines.append("Reads CMD=0x81/0x90:")
        if not window["reads_81_90"]:
            lines.append("- none")
        for item in window["reads_81_90"]:
            lines.append(f"- `{format_read(item)}`")
        lines.append("")

    lines += [
        "## All Block Writes CMD=0x03",
        "",
    ]
    if not result["block_writes"]:
        lines.append("- none")
    for item in result["block_writes"]:
        lines.append(f"- `{format_block(item)}`")
    lines += [
        "",
        "## All Watched Byte Writes",
        "",
    ]
    if not result["watched_byte_writes"]:
        lines.append("- none")
    for item in result["watched_byte_writes"]:
        lines.append(f"- `{format_byte(item)}`")
    lines += [
        "",
        "## Reads CMD=0x81 / CMD=0x90",
        "",
    ]
    if not result["reads_81_90"]:
        lines.append("- none")
    for item in result["reads_81_90"]:
        lines.append(f"- `{format_read(item)}`")
    lines += [
        "",
        "## Selected Register History",
        "",
    ]
    if not result["selected_registers"]:
        lines.append("- none")
    for reg, count in sorted(result["selected_registers"].items()):
        lines.append(f"- `{reg}` count={count}")
    lines.append("")

    lines += [
        "## Immediately Before COLOR_VISUALLY_CHANGED",
        "",
        "Block writes:",
    ]
    for item in red["immediately_before_visual_change"]["block_writes"]:
        lines.append(f"- `{format_block(item)}`")
    if not red["immediately_before_visual_change"]["block_writes"]:
        lines.append("- none")
    lines.append("")
    lines.append("Watched byte writes:")
    for item in red["immediately_before_visual_change"]["watched_byte_writes"]:
        lines.append(f"- `{format_byte(item)}`")
    if not red["immediately_before_visual_change"]["watched_byte_writes"]:
        lines.append("- none")

    lines += [
        "",
        "## Comparison",
        "",
        "Known good direct path:",
    ]
    for item in result["comparison"]["known_good_direct_path"]:
        lines.append(f"- `{item}`")
    lines.append("")
    lines.append("Known Armoury UI RGB path:")
    for item in result["comparison"]["known_armoury_ui_rgb_path"]:
        lines.append(f"- `{item}`")

    lines += [
        "",
        "## Conclusion",
        "",
    ]
    conclusion = result["conclusion"]
    lines.append("Candidate transition block writes:")
    if not conclusion["candidate transition block writes"]:
        lines.append("- none")
    for item in conclusion["candidate transition block writes"]:
        lines.append(f"- `{item}`")
    lines.append("")
    lines.append("Candidate mode/commit byte writes:")
    if not conclusion["candidate mode/commit byte writes"]:
        lines.append("- none")
    for item in conclusion["candidate mode/commit byte writes"]:
        lines.append(f"- `{item}`")
    lines.append("")
    lines.append(f"- recommended next microtest: {conclusion['recommended next microtest']}")
    lines.append("- do not implement recover-full yet: true")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def print_report(result, summary_path=None):
    print("# Sylphie Capture Analysis")
    print("")
    if summary_path:
        print(f"- sanitized_summary: {summary_path}")
        print("")
    print("## Timeline")
    for key, values in result["timeline"].items():
        print(f"- {key}: {', '.join(values) if values else 'not observed'}")
    print("")
    print("## Selected Registers")
    for reg, count in sorted(result["selected_registers"].items()):
        print(f"- {reg}: {count}")
    print("")
    print("## RED_STUCK_TO_GREEN Windows")
    for name, window in result["red_stuck_to_green"]["windows"].items():
        print(f"- {name}: {window['start']} -> {window['end']}")
        print("  block writes:")
        if not window["block_writes"]:
            print("  - none")
        for item in window["block_writes"]:
            print(f"  - {format_block(item)}")
        print("  watched byte writes:")
        if not window["watched_byte_writes"]:
            print("  - none")
        for item in window["watched_byte_writes"]:
            print(f"  - {format_byte(item)}")
    print("")
    print("## Conclusion")
    for key, value in result["conclusion"].items():
        if isinstance(value, list):
            print(f"- {key}:")
            if not value:
                print("  - none")
            for item in value:
                print(f"  - {item}")
        else:
            print(f"- {key}: {value}")


def json_safe(value):
    if isinstance(value, datetime):
        return timestamp_text(value)
    raise TypeError(f"object of type {type(value).__name__} is not JSON serializable")


def main():
    parser = argparse.ArgumentParser(description="Analyze Sylphie SMBus capture logs")
    parser.add_argument("logs", nargs="+", help="Master capture log path(s)")
    parser.add_argument("--markers", action="append", default=[], help="Marker log path")
    parser.add_argument("--json", action="store_true", help="Print JSON only")
    parser.add_argument("--write-red-stuck-summary", action="store_true", help="Write docs/research red stuck to green summary")
    parser.add_argument("--summary-dir", default="docs/research", help="Summary output directory")
    args = parser.parse_args()

    result = analyze(args.logs, marker_paths=args.markers)
    summary_path = None
    if args.write_red_stuck_summary:
        summary_path = write_red_stuck_summary(result, args.summary_dir)
        result["sanitized_summary"] = str(summary_path)

    if args.json:
        print(json.dumps(result, indent=2, default=json_safe))
        return 0

    print_report(result, summary_path=summary_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
