#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>

#include <conio.h>

#include <algorithm>
#include <cctype>
#include <cstdint>
#include <cstdio>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <map>
#include <memory>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
constexpr uint16_t kDefaultSmbusBase = 0x0B20;
constexpr uint8_t kOffsetSts = 0x00;
constexpr uint8_t kOffsetSlv = 0x01;
constexpr uint8_t kOffsetCnt = 0x02;
constexpr uint8_t kOffsetCmd = 0x03;
constexpr uint8_t kOffsetAddr = 0x04;
constexpr uint8_t kOffsetD0 = 0x05;
constexpr uint8_t kOffsetD1 = 0x06;
constexpr uint8_t kOffsetBlk = 0x07;

struct Options {
    uint16_t base = kDefaultSmbusBase;
    std::string output_path = "armoury_ui_capture_master.log";
    bool capture_block_payload = false;
    uint8_t payload_max_len = 16;
    bool segment_logs = false;
    bool decode = true;
    uint32_t interval_ms = 1;
    uint32_t duration_seconds = 0;
};

struct Snapshot {
    uint8_t sts = 0;
    uint8_t slv = 0;
    uint8_t cnt = 0;
    uint8_t cmd = 0;
    uint8_t addr_raw = 0;
    uint8_t d0 = 0;
    uint8_t d1 = 0;
    uint8_t safe_08 = 0;
    uint8_t safe_09 = 0;
    uint8_t safe_0a = 0;
    uint8_t safe_0b = 0;
    uint8_t safe_0c = 0;
    uint8_t safe_0d = 0;
    uint8_t safe_0e = 0;
    uint8_t safe_0f = 0;
};

struct CapturedPayload {
    std::vector<uint8_t> bytes;
    bool has_extra = false;
    uint8_t extra = 0;
};

struct Summary {
    uint64_t raw_events = 0;
    uint64_t aura_reads = 0;
    uint64_t aura_writes = 0;
    uint64_t block_writes = 0;
    std::map<std::string, uint64_t> block_writes_by_register;
    std::map<std::string, uint64_t> byte_writes_by_register_hint;
    std::set<std::string> selected_registers;
    std::vector<std::string> captured_payloads;
    std::map<std::string, uint64_t> segment_events;
};

using Inp32Fn = short(__stdcall*)(short port);

std::string windows_error_message(DWORD error_code) {
    char* buffer = nullptr;
    FormatMessageA(
        FORMAT_MESSAGE_ALLOCATE_BUFFER | FORMAT_MESSAGE_FROM_SYSTEM | FORMAT_MESSAGE_IGNORE_INSERTS,
        nullptr,
        error_code,
        0,
        reinterpret_cast<LPSTR>(&buffer),
        0,
        nullptr);
    std::string message = buffer != nullptr ? buffer : "unknown Windows error";
    if (buffer != nullptr) {
        LocalFree(buffer);
    }
    while (!message.empty() && (message.back() == '\r' || message.back() == '\n')) {
        message.pop_back();
    }
    return message;
}

std::string upper_copy(std::string value) {
    std::transform(value.begin(), value.end(), value.begin(), [](unsigned char ch) {
        return static_cast<char>(std::toupper(ch));
    });
    return value;
}

std::string hex2(uint8_t value) {
    std::ostringstream out;
    out << "0x" << std::uppercase << std::hex << std::setw(2) << std::setfill('0')
        << static_cast<int>(value);
    return out.str();
}

std::string hex4(uint16_t value) {
    std::ostringstream out;
    out << "0x" << std::uppercase << std::hex << std::setw(4) << std::setfill('0')
        << static_cast<int>(value);
    return out.str();
}

std::string hex_plain(uint8_t value) {
    std::ostringstream out;
    out << std::uppercase << std::hex << std::setw(2) << std::setfill('0')
        << static_cast<int>(value);
    return out.str();
}

uint16_t parse_hex16(std::string value) {
    if (value.rfind("0x", 0) == 0 || value.rfind("0X", 0) == 0) {
        value = value.substr(2);
    }
    if (value.empty() || value.size() > 4) {
        throw std::runtime_error("invalid hex value: " + value);
    }
    return static_cast<uint16_t>(std::stoul(value, nullptr, 16) & 0xFFFF);
}

uint8_t parse_u8(const std::string& value) {
    const unsigned long parsed = std::stoul(value, nullptr, 10);
    if (parsed > 255) {
        throw std::runtime_error("value out of range: " + value);
    }
    return static_cast<uint8_t>(parsed);
}

std::string timestamp_now() {
    SYSTEMTIME time = {};
    GetLocalTime(&time);
    char buffer[64] = {};
    sprintf_s(
        buffer,
        "%04u-%02u-%02u %02u:%02u:%02u.%03u",
        time.wYear,
        time.wMonth,
        time.wDay,
        time.wHour,
        time.wMinute,
        time.wSecond,
        time.wMilliseconds);
    return buffer;
}

void print_help() {
    std::cout
        << "sylphie_piix4_armoury_ui_capture - read-only Armoury UI SMBus capture\n\n"
        << "Usage:\n"
        << "  sylphie_piix4_armoury_ui_capture.exe 0B20 --output armoury_ui_capture_master.log --capture-block-payload\n"
        << "  sylphie_piix4_armoury_ui_capture.exe --base 0B20 [options]\n\n"
        << "Options:\n"
        << "  --base HEX                 SMBus base, default 0B20\n"
        << "  --output FILE              Master log path, default armoury_ui_capture_master.log\n"
        << "  --capture-block-payload    Read +0x07 only on ADDR=0x40 W CMD=0x03 events\n"
        << "  --payload-max-len N        Max block length to capture, default 16\n"
        << "  --segment-logs             Start a segment log on each marker key\n"
        << "  --no-decode                Disable Aura event decoder\n"
        << "  --duration-seconds N       Stop automatically after N seconds\n"
        << "  --help                     Show this help\n\n"
        << "Marker keys:\n"
        << "  1 SERVICE_STOPPED\n"
        << "  2 SERVICE_STARTED\n"
        << "  3 FIRST_LIGHT\n"
        << "  m MOUSE_COLOR_SELECTED\n"
        << "  o OK_CLICKED\n"
        << "  a APPLY_CLICKED\n"
        << "  w WHITE_SELECTED\n"
        << "  r RED_SELECTED\n"
        << "  g GREEN_SELECTED\n"
        << "  b BLUE_SELECTED\n"
        << "  f FIXED_MODE_SELECTED\n"
        << "  e EFFECT_MODE_SELECTED\n"
        << "  x OTHER\n"
        << "  q QUIT\n\n"
        << "Safety:\n"
        << "  Uses Inp32 only. It never writes and never calls Out32.\n"
        << "  It does not read +0x07 / SMBBLKDAT unless --capture-block-payload is passed.\n";
}

Options parse_args(int argc, char** argv) {
    Options options;
    bool consumed_positional_base = false;
    for (int i = 1; i < argc; ++i) {
        const std::string arg = argv[i];
        if (arg == "--help" || arg == "-h") {
            print_help();
            std::exit(0);
        }
        if (arg == "--base" && i + 1 < argc) {
            options.base = parse_hex16(argv[++i]);
            continue;
        }
        if (arg == "--output" && i + 1 < argc) {
            options.output_path = argv[++i];
            continue;
        }
        if (arg == "--capture-block-payload") {
            options.capture_block_payload = true;
            continue;
        }
        if (arg == "--payload-max-len" && i + 1 < argc) {
            options.payload_max_len = parse_u8(argv[++i]);
            if (options.payload_max_len == 0 || options.payload_max_len > 64) {
                throw std::runtime_error("--payload-max-len must be 1..64");
            }
            continue;
        }
        if (arg == "--segment-logs") {
            options.segment_logs = true;
            continue;
        }
        if (arg == "--no-decode") {
            options.decode = false;
            continue;
        }
        if (arg == "--interval-ms" && i + 1 < argc) {
            options.interval_ms = static_cast<uint32_t>(std::stoul(argv[++i]));
            if (options.interval_ms == 0) {
                options.interval_ms = 1;
            }
            continue;
        }
        if (arg == "--duration-seconds" && i + 1 < argc) {
            options.duration_seconds = static_cast<uint32_t>(std::stoul(argv[++i]));
            continue;
        }
        if (!arg.empty() && arg[0] != '-' && !consumed_positional_base) {
            options.base = parse_hex16(arg);
            consumed_positional_base = true;
            continue;
        }
        throw std::runtime_error("unknown argument: " + arg);
    }
    return options;
}

class ReadOnlyPorts {
public:
    explicit ReadOnlyPorts(uint16_t base) : base_(base) {
        library_ = LoadLibraryA("inpout32.dll");
        if (library_ == nullptr) {
            throw std::runtime_error("LoadLibraryA(inpout32.dll) failed: " + windows_error_message(GetLastError()));
        }
        inp32_ = reinterpret_cast<Inp32Fn>(GetProcAddress(library_, "Inp32"));
        if (inp32_ == nullptr) {
            throw std::runtime_error("GetProcAddress(Inp32) failed: " + windows_error_message(GetLastError()));
        }
    }

    ~ReadOnlyPorts() {
        if (library_ != nullptr) {
            FreeLibrary(library_);
        }
    }

    uint8_t read8(uint8_t offset) const {
        return static_cast<uint8_t>(inp32_(static_cast<short>(base_ + offset)) & 0xFF);
    }

private:
    uint16_t base_ = kDefaultSmbusBase;
    HMODULE library_ = nullptr;
    Inp32Fn inp32_ = nullptr;
};

Snapshot read_snapshot(const ReadOnlyPorts& ports) {
    Snapshot s;
    s.sts = ports.read8(kOffsetSts);
    s.slv = ports.read8(kOffsetSlv);
    s.cnt = ports.read8(kOffsetCnt);
    s.cmd = ports.read8(kOffsetCmd);
    s.addr_raw = ports.read8(kOffsetAddr);
    s.d0 = ports.read8(kOffsetD0);
    s.d1 = ports.read8(kOffsetD1);
    s.safe_08 = ports.read8(0x08);
    s.safe_09 = ports.read8(0x09);
    s.safe_0a = ports.read8(0x0A);
    s.safe_0b = ports.read8(0x0B);
    s.safe_0c = ports.read8(0x0C);
    s.safe_0d = ports.read8(0x0D);
    s.safe_0e = ports.read8(0x0E);
    s.safe_0f = ports.read8(0x0F);
    return s;
}

void append_if_changed(std::vector<std::string>& changes, const char* name, uint8_t before, uint8_t after) {
    if (before == after) {
        return;
    }
    std::ostringstream item;
    item << name << ":" << hex2(before) << "->" << hex2(after);
    changes.push_back(item.str());
}

std::vector<std::string> changed_fields(const Snapshot& before, const Snapshot& after) {
    std::vector<std::string> changes;
    append_if_changed(changes, "STS", before.sts, after.sts);
    append_if_changed(changes, "SLV", before.slv, after.slv);
    append_if_changed(changes, "CNT", before.cnt, after.cnt);
    append_if_changed(changes, "CMD", before.cmd, after.cmd);
    append_if_changed(changes, "ADDR_RAW", before.addr_raw, after.addr_raw);
    append_if_changed(changes, "D0", before.d0, after.d0);
    append_if_changed(changes, "D1", before.d1, after.d1);
    append_if_changed(changes, "+08", before.safe_08, after.safe_08);
    append_if_changed(changes, "+09", before.safe_09, after.safe_09);
    append_if_changed(changes, "+0A", before.safe_0a, after.safe_0a);
    append_if_changed(changes, "+0B", before.safe_0b, after.safe_0b);
    append_if_changed(changes, "+0C", before.safe_0c, after.safe_0c);
    append_if_changed(changes, "+0D", before.safe_0d, after.safe_0d);
    append_if_changed(changes, "+0E", before.safe_0e, after.safe_0e);
    append_if_changed(changes, "+0F", before.safe_0f, after.safe_0f);
    return changes;
}

std::string join_changes(const std::vector<std::string>& changes) {
    std::ostringstream out;
    for (size_t i = 0; i < changes.size(); ++i) {
        if (i != 0) {
            out << ",";
        }
        out << changes[i];
    }
    return out.str();
}

uint8_t addr7(uint8_t addr_raw) {
    return static_cast<uint8_t>((addr_raw >> 1) & 0x7F);
}

const char* rw_text(uint8_t addr_raw) {
    return (addr_raw & 0x01) != 0 ? "R" : "W";
}

std::string marker_for_key(int key) {
    switch (std::tolower(key)) {
    case '1':
        return "SERVICE_STOPPED";
    case '2':
        return "SERVICE_STARTED";
    case '3':
        return "FIRST_LIGHT";
    case 'm':
        return "MOUSE_COLOR_SELECTED";
    case 'o':
        return "OK_CLICKED";
    case 'a':
        return "APPLY_CLICKED";
    case 'w':
        return "WHITE_SELECTED";
    case 'r':
        return "RED_SELECTED";
    case 'g':
        return "GREEN_SELECTED";
    case 'b':
        return "BLUE_SELECTED";
    case 'f':
        return "FIXED_MODE_SELECTED";
    case 'e':
        return "EFFECT_MODE_SELECTED";
    case 'x':
        return "OTHER";
    default:
        return "";
    }
}

std::string sanitize_file_token(std::string value) {
    for (char& ch : value) {
        const bool ok = std::isalnum(static_cast<unsigned char>(ch)) || ch == '_' || ch == '-';
        if (!ok) {
            ch = '_';
        }
    }
    return value;
}

std::string segment_path_for(const std::string& output_path, uint32_t index, const std::string& marker) {
    const size_t slash = output_path.find_last_of("\\/");
    const size_t dot = output_path.find_last_of('.');
    const bool dot_after_slash = dot != std::string::npos && (slash == std::string::npos || dot > slash);
    const std::string prefix = dot_after_slash ? output_path.substr(0, dot) : output_path;
    const std::string suffix = dot_after_slash ? output_path.substr(dot) : ".log";
    std::ostringstream path;
    path << prefix << "_segment_" << std::setw(3) << std::setfill('0') << index << "_"
         << sanitize_file_token(marker) << suffix;
    return path.str();
}

class Logger {
public:
    explicit Logger(const Options& options) : options_(options), master_(options.output_path, std::ios::out | std::ios::app) {
        if (!master_) {
            throw std::runtime_error("could not open output log: " + options.output_path);
        }
    }

    void write(const std::string& line) {
        std::cout << line << "\n";
        master_ << line << "\n";
        master_.flush();
        if (segment_) {
            *segment_ << line << "\n";
            segment_->flush();
        }
    }

    void start_segment(const std::string& marker) {
        if (!options_.segment_logs) {
            return;
        }
        ++segment_index_;
        current_segment_ = marker;
        const std::string path = segment_path_for(options_.output_path, segment_index_, marker);
        segment_.reset(new std::ofstream(path, std::ios::out | std::ios::app));
        if (!*segment_) {
            throw std::runtime_error("could not open segment log: " + path);
        }
        write(timestamp_now() + " SEGMENT_START marker=" + marker + " path=" + path);
    }

    std::string current_segment() const {
        return current_segment_.empty() ? "unmarked" : current_segment_;
    }

private:
    const Options& options_;
    std::ofstream master_;
    std::unique_ptr<std::ofstream> segment_;
    uint32_t segment_index_ = 0;
    std::string current_segment_;
};

std::string raw_line(const Snapshot& s, uint64_t tick, const std::vector<std::string>& changes) {
    std::ostringstream line;
    line << timestamp_now()
         << " tick=" << tick
         << " STS=" << hex2(s.sts)
         << " SLV=" << hex2(s.slv)
         << " CNT=" << hex2(s.cnt)
         << " CMD=" << hex2(s.cmd)
         << " ADDR_RAW=" << hex2(s.addr_raw)
         << " ADDR7=" << hex2(addr7(s.addr_raw))
         << " RW=" << rw_text(s.addr_raw)
         << " D0=" << hex2(s.d0)
         << " D1=" << hex2(s.d1)
         << " changed=" << join_changes(changes);
    return line.str();
}

bool is_d1_hint(uint8_t value) {
    switch (value) {
    case 0x00:
    case 0x20:
    case 0x21:
    case 0x22:
    case 0x23:
    case 0x27:
    case 0xA0:
    case 0xF1:
        return true;
    default:
        return false;
    }
}

std::string register_text(bool valid, uint16_t value) {
    return valid ? hex4(value) : std::string("unknown");
}

CapturedPayload maybe_capture_block_payload(const ReadOnlyPorts& ports, const Snapshot& s, const Options& options) {
    CapturedPayload captured;
    if (!options.capture_block_payload) {
        return captured;
    }
    if (addr7(s.addr_raw) != 0x40 || (s.addr_raw & 0x01) != 0 || s.cmd != 0x03) {
        return captured;
    }
    if (s.d0 < 1 || s.d0 > options.payload_max_len) {
        return captured;
    }

    for (uint8_t i = 0; i < s.d0; ++i) {
        captured.bytes.push_back(ports.read8(kOffsetBlk));
    }
    captured.extra = ports.read8(kOffsetBlk);
    captured.has_extra = true;
    return captured;
}

std::string payload_reads_text(const CapturedPayload& payload) {
    std::ostringstream out;
    out << "payload_reads=";
    for (size_t i = 0; i < payload.bytes.size(); ++i) {
        if (i != 0) {
            out << " ";
        }
        out << hex_plain(payload.bytes[i]);
    }
    if (payload.has_extra) {
        out << " [extra=" << hex_plain(payload.extra) << "]";
    }
    return out.str();
}

std::string payload_key(const CapturedPayload& payload) {
    if (payload.bytes.empty() && !payload.has_extra) {
        return "";
    }
    return payload_reads_text(payload);
}

void decode_aura(
    Logger& log,
    Summary& summary,
    const Snapshot& s,
    uint16_t& selected_register,
    bool& selected_register_valid,
    const CapturedPayload& captured_payload) {
    if (addr7(s.addr_raw) != 0x40) {
        return;
    }

    if ((s.addr_raw & 0x01) != 0) {
        ++summary.aura_reads;
        std::ostringstream line;
        line << "  AURA read CMD=" << hex2(s.cmd)
             << " STS=" << hex2(s.sts)
             << " CNT=" << hex2(s.cnt)
             << " D0=" << hex2(s.d0)
             << " D1=" << hex2(s.d1);
        log.write(line.str());
        return;
    }

    ++summary.aura_writes;

    if (s.cmd == 0x00) {
        selected_register = static_cast<uint16_t>((static_cast<uint16_t>(s.d0) << 8) | s.d1);
        selected_register_valid = true;
        summary.selected_registers.insert(hex4(selected_register));
        log.write("  AURA select_register " + hex4(selected_register));
        return;
    }

    if (s.cmd == 0x01) {
        const bool has_hint = is_d1_hint(s.d1);
        const uint16_t hint_register = static_cast<uint16_t>(0x8000 | s.d1);
        std::string confidence = "selected";
        if (has_hint && (!selected_register_valid || hint_register != selected_register)) {
            confidence = "ambiguous";
        }

        std::ostringstream line;
        line << "  AURA byte_write value=" << hex2(s.d0)
             << " last_selected_register=" << register_text(selected_register_valid, selected_register);
        if (has_hint) {
            line << " d1_hint_register=" << hex4(hint_register);
        }
        line << " confidence=" << confidence;
        log.write(line.str());

        std::ostringstream key;
        key << "selected=" << register_text(selected_register_valid, selected_register);
        if (has_hint) {
            key << " hint=" << hex4(hint_register);
        }
        ++summary.byte_writes_by_register_hint[key.str()];
        return;
    }

    if (s.cmd == 0x03) {
        ++summary.block_writes;
        const std::string reg = register_text(selected_register_valid, selected_register);
        ++summary.block_writes_by_register[reg];
        std::ostringstream line;
        line << "  AURA block_write last_selected_register=" << reg
             << " len=" << static_cast<int>(s.d0);
        if (!captured_payload.bytes.empty() || captured_payload.has_extra) {
            const std::string payload = payload_reads_text(captured_payload);
            line << " " << payload;
            summary.captured_payloads.push_back(reg + " " + payload);
        }
        line << " confidence=" << (selected_register_valid ? "selected" : "unknown");
        log.write(line.str());
    }
}

void write_summary(Logger& log, const Summary& summary) {
    log.write("=== summary ===");
    log.write("total raw events=" + std::to_string(summary.raw_events));
    log.write("total ADDR=0x40 reads=" + std::to_string(summary.aura_reads));
    log.write("total ADDR=0x40 writes=" + std::to_string(summary.aura_writes));
    log.write("total block writes=" + std::to_string(summary.block_writes));

    log.write("block writes by selected_register:");
    for (const auto& item : summary.block_writes_by_register) {
        log.write("  " + item.first + " count=" + std::to_string(item.second));
    }

    log.write("byte writes by selected_register/d1_hint:");
    for (const auto& item : summary.byte_writes_by_register_hint) {
        log.write("  " + item.first + " count=" + std::to_string(item.second));
    }

    log.write("selected registers:");
    for (const auto& reg : summary.selected_registers) {
        log.write("  " + reg);
    }

    log.write("captured payloads:");
    for (const auto& payload : summary.captured_payloads) {
        log.write("  " + payload);
    }

    log.write("events by segment/marker:");
    for (const auto& item : summary.segment_events) {
        log.write("  " + item.first + " count=" + std::to_string(item.second));
    }
}
}

int main(int argc, char** argv) {
    try {
        const Options options = parse_args(argc, argv);
        ReadOnlyPorts ports(options.base);
        Logger log(options);
        Summary summary;

        log.write("=== sylphie_piix4_armoury_ui_capture start ===");
        log.write("base=" + hex4(options.base) + " output=" + options.output_path);
        log.write("safe_offsets=+0x00,+0x01,+0x02,+0x03,+0x04,+0x05,+0x06,+0x08..+0x0F");
        log.write(std::string("capture_block_payload=") + (options.capture_block_payload ? "true" : "false"));
        log.write("payload_max_len=" + std::to_string(static_cast<int>(options.payload_max_len)));
        log.write(std::string("segment_logs=") + (options.segment_logs ? "true" : "false"));
        log.write(std::string("decode=") + (options.decode ? "true" : "false"));
        log.write("duration_seconds=" + std::to_string(options.duration_seconds));
        if (options.capture_block_payload) {
            log.write("WARNING: --capture-block-payload reads +0x07 only for ADDR=0x40 W CMD=0x03 D0=1..payload_max_len; this is experimental/invasive.");
        }
        log.write("keys: 1 SERVICE_STOPPED, 2 SERVICE_STARTED, 3 FIRST_LIGHT, m MOUSE_COLOR_SELECTED, o OK_CLICKED, a APPLY_CLICKED, w WHITE_SELECTED, r RED_SELECTED, g GREEN_SELECTED, b BLUE_SELECTED, f FIXED_MODE_SELECTED, e EFFECT_MODE_SELECTED, x OTHER, q QUIT");

        Snapshot previous = read_snapshot(ports);
        uint16_t selected_register = 0;
        bool selected_register_valid = false;

        log.write(raw_line(previous, GetTickCount64(), {"initial"}));

        bool quit = false;
        const uint64_t deadline_tick =
            options.duration_seconds == 0 ? 0 : GetTickCount64() + (static_cast<uint64_t>(options.duration_seconds) * 1000);
        while (!quit) {
            if (deadline_tick != 0 && GetTickCount64() >= deadline_tick) {
                log.write(timestamp_now() + " MARKER AUTO_DURATION_STOP");
                break;
            }

            while (_kbhit()) {
                const int key = _getch();
                if (key == 'q' || key == 'Q') {
                    log.write(timestamp_now() + " MARKER QUIT");
                    quit = true;
                    break;
                }
                const std::string marker = marker_for_key(key);
                if (!marker.empty()) {
                    log.write(timestamp_now() + " MARKER " + marker);
                    log.start_segment(marker);
                }
            }
            if (quit) {
                break;
            }

            const Snapshot current = read_snapshot(ports);
            const auto changes = changed_fields(previous, current);
            if (!changes.empty()) {
                ++summary.raw_events;
                ++summary.segment_events[log.current_segment()];
                const CapturedPayload payload = maybe_capture_block_payload(ports, current, options);
                log.write(raw_line(current, GetTickCount64(), changes));
                if (options.decode) {
                    decode_aura(log, summary, current, selected_register, selected_register_valid, payload);
                }
                previous = current;
            }

            Sleep(options.interval_ms);
        }

        write_summary(log, summary);
        log.write("=== sylphie_piix4_armoury_ui_capture stop ===");
        return 0;
    } catch (const std::exception& ex) {
        std::cerr << "error: " << ex.what() << "\n";
        return 1;
    }
}
