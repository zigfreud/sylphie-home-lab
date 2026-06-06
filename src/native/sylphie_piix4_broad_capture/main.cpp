#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>

#include <conio.h>

#include <cstdint>
#include <cstdio>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
constexpr uint16_t kSmbusBase = 0x0B20;
constexpr uint8_t kOffsetSts = 0x00;
constexpr uint8_t kOffsetSlv = 0x01;
constexpr uint8_t kOffsetCnt = 0x02;
constexpr uint8_t kOffsetCmd = 0x03;
constexpr uint8_t kOffsetAddr = 0x04;
constexpr uint8_t kOffsetD0 = 0x05;
constexpr uint8_t kOffsetD1 = 0x06;
constexpr uint8_t kOffsetBlk = 0x07;

struct Options {
    bool capture_block_payload = false;
    uint32_t interval_ms = 1;
    std::string output_path = "broad_capture_master.log";
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
        << "sylphie_piix4_broad_capture - read-only PIIX4 SMBus broad capture\n\n"
        << "Usage:\n"
        << "  sylphie_piix4_broad_capture.exe [--interval-ms N] [--output broad_capture_master.log]\n"
        << "  sylphie_piix4_broad_capture.exe --capture-block-payload [--interval-ms N]\n\n"
        << "Keys while capturing:\n"
        << "  1 SERVICE_STOPPED\n"
        << "  2 SERVICE_STARTED\n"
        << "  3 FIRST_LIGHT\n"
        << "  4 WHITE\n"
        << "  5 RED\n"
        << "  6 GREEN\n"
        << "  7 BLUE\n"
        << "  8 OTHER\n"
        << "  q QUIT\n\n"
        << "Safety:\n"
        << "  This tool never calls Out32 and performs no writes.\n"
        << "  It does not read +0x07 / SMBBLKDAT unless --capture-block-payload is passed.\n";
}

Options parse_args(int argc, char** argv) {
    Options options;
    for (int i = 1; i < argc; ++i) {
        const std::string arg = argv[i];
        if (arg == "--help" || arg == "-h") {
            print_help();
            std::exit(0);
        }
        if (arg == "--capture-block-payload") {
            options.capture_block_payload = true;
            continue;
        }
        if (arg == "--interval-ms" && i + 1 < argc) {
            options.interval_ms = static_cast<uint32_t>(std::stoul(argv[++i]));
            if (options.interval_ms == 0) {
                options.interval_ms = 1;
            }
            continue;
        }
        if (arg == "--output" && i + 1 < argc) {
            options.output_path = argv[++i];
            continue;
        }
        throw std::runtime_error("unknown argument: " + arg);
    }
    return options;
}

class ReadOnlyPorts {
public:
    ReadOnlyPorts() {
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
        return static_cast<uint8_t>(inp32_(static_cast<short>(kSmbusBase + offset)) & 0xFF);
    }

private:
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

const char* rw_text(uint8_t addr_raw) {
    return (addr_raw & 0x01) != 0 ? "R" : "W";
}

uint8_t addr7(uint8_t addr_raw) {
    return static_cast<uint8_t>((addr_raw >> 1) & 0x7F);
}

std::string marker_for_key(int key) {
    switch (key) {
    case '1':
        return "SERVICE_STOPPED";
    case '2':
        return "SERVICE_STARTED";
    case '3':
        return "FIRST_LIGHT";
    case '4':
        return "WHITE";
    case '5':
        return "RED";
    case '6':
        return "GREEN";
    case '7':
        return "BLUE";
    case '8':
        return "OTHER";
    default:
        return "";
    }
}

void write_line(std::ofstream& log, const std::string& line) {
    std::cout << line << "\n";
    log << line << "\n";
    log.flush();
}

void log_snapshot(
    std::ofstream& log,
    const Snapshot& s,
    uint64_t tick,
    const std::vector<std::string>& changes) {
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
    write_line(log, line.str());
}

std::vector<uint8_t> maybe_capture_block_payload(const ReadOnlyPorts& ports, const Snapshot& s, bool enabled) {
    if (!enabled) {
        return {};
    }
    if (addr7(s.addr_raw) != 0x40 || (s.addr_raw & 0x01) != 0 || s.cmd != 0x03 || s.d0 < 1 || s.d0 > 16) {
        return {};
    }

    std::vector<uint8_t> bytes;
    const uint8_t count = static_cast<uint8_t>(s.d0 + 1);
    for (uint8_t i = 0; i < count; ++i) {
        bytes.push_back(ports.read8(kOffsetBlk));
    }
    return bytes;
}

std::string payload_text(const std::vector<uint8_t>& payload) {
    std::ostringstream out;
    for (size_t i = 0; i < payload.size(); ++i) {
        if (i != 0) {
            out << " ";
        }
        out << hex2(payload[i]);
    }
    return out.str();
}

void decode_aura(
    std::ofstream& log,
    const Snapshot& s,
    uint16_t& selected_register,
    bool& selected_register_valid,
    const std::vector<uint8_t>& captured_payload) {
    if (addr7(s.addr_raw) != 0x40 || (s.addr_raw & 0x01) != 0) {
        return;
    }

    if (s.cmd == 0x00) {
        selected_register = static_cast<uint16_t>((static_cast<uint16_t>(s.d0) << 8) | s.d1);
        selected_register_valid = true;
        write_line(log, "  AURA select_register " + hex4(selected_register));
        return;
    }

    if (s.cmd == 0x01) {
        std::ostringstream line;
        line << "  AURA byte_write selected_register="
             << (selected_register_valid ? hex4(selected_register) : std::string("unknown"))
             << " value=" << hex2(s.d0);
        write_line(log, line.str());
        return;
    }

    if (s.cmd == 0x03) {
        std::ostringstream line;
        line << "  AURA block_write selected_register="
             << (selected_register_valid ? hex4(selected_register) : std::string("unknown"))
             << " len=" << hex2(s.d0);
        if (!captured_payload.empty()) {
            line << " captured_payload=" << payload_text(captured_payload);
        }
        write_line(log, line.str());
    }
}
}

int main(int argc, char** argv) {
    try {
        const Options options = parse_args(argc, argv);
        ReadOnlyPorts ports;

        std::ofstream log(options.output_path, std::ios::out | std::ios::app);
        if (!log) {
            throw std::runtime_error("could not open output log: " + options.output_path);
        }

        write_line(log, "=== sylphie_piix4_broad_capture start ===");
        write_line(log, "base=0x0B20 output=" + options.output_path);
        write_line(log, "safe_offsets=+0x00,+0x01,+0x02,+0x03,+0x04,+0x05,+0x06,+0x08..+0x0F");
        write_line(log, std::string("capture_block_payload=") + (options.capture_block_payload ? "true" : "false"));
        if (options.capture_block_payload) {
            write_line(log, "WARNING: --capture-block-payload reads +0x07 only for ADDR=0x40 W CMD=0x03 D0=1..16; this is invasive/experimental.");
        }
        write_line(log, "keys: 1 SERVICE_STOPPED, 2 SERVICE_STARTED, 3 FIRST_LIGHT, 4 WHITE, 5 RED, 6 GREEN, 7 BLUE, 8 OTHER, q QUIT");

        Snapshot previous = read_snapshot(ports);
        uint16_t selected_register = 0;
        bool selected_register_valid = false;
        uint64_t sample = 0;

        log_snapshot(log, previous, GetTickCount64(), {"initial"});

        bool quit = false;
        while (!quit) {
            while (_kbhit()) {
                const int key = _getch();
                if (key == 'q' || key == 'Q') {
                    write_line(log, timestamp_now() + " MARKER QUIT");
                    quit = true;
                    break;
                }
                const std::string marker = marker_for_key(key);
                if (!marker.empty()) {
                    write_line(log, timestamp_now() + " MARKER " + marker);
                }
            }
            if (quit) {
                break;
            }

            const Snapshot current = read_snapshot(ports);
            const auto changes = changed_fields(previous, current);
            if (!changes.empty()) {
                const auto payload = maybe_capture_block_payload(ports, current, options.capture_block_payload);
                log_snapshot(log, current, GetTickCount64(), changes);
                decode_aura(log, current, selected_register, selected_register_valid, payload);
                previous = current;
            }

            ++sample;
            (void)sample;
            Sleep(options.interval_ms);
        }

        write_line(log, "=== sylphie_piix4_broad_capture stop ===");
        return 0;
    } catch (const std::exception& ex) {
        std::cerr << "error: " << ex.what() << "\n";
        return 1;
    }
}
