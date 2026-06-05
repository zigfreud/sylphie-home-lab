#include "aura_ene.hpp"
#include "color.hpp"
#include "piix4_smbus.hpp"
#include "process_check.hpp"

#include <algorithm>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#include <tlhelp32.h>
#include <winsvc.h>

namespace {
constexpr int kExitOk = 0;
constexpr int kExitRuntimeError = 1;
constexpr int kExitUsage = 2;
constexpr int kExitTakeoverConflict = 10;
constexpr int kExitSmbusBusy = 11;

struct Scene {
    const char* name;
    RgbColor color;
    const char* description;
};

const Scene kScenes[] = {
    {"focus", {0xFF, 0xFF, 0xFF}, "strong neutral white"},
    {"movie", {0x20, 0x20, 0x60}, "visible dark blue-purple bias light"},
    {"night", {0x30, 0x00, 0x00}, "low red above visibility threshold"},
    {"reading", {0xFF, 0xC0, 0x80}, "warm reading light"},
    {"cyberpunk", {0xFF, 0x00, 0x80}, "magenta accent"},
    {"deepblue", {0x00, 0x00, 0xFF}, "full blue"},
    {"red", {0xFF, 0x00, 0x00}, "full red"},
    {"green", {0x00, 0xFF, 0x00}, "full green"},
    {"blue", {0x00, 0x00, 0xFF}, "full blue"},
    {"white", {0xFF, 0xFF, 0xFF}, "full white"},
    {"off", {0x00, 0x00, 0x00}, "direct RGB off"},
};

const Scene kCalibrationSteps[] = {
    {"red", {0xFF, 0x00, 0x00}, "full red"},
    {"green", {0x00, 0xFF, 0x00}, "full green"},
    {"blue", {0x00, 0x00, 0xFF}, "full blue"},
    {"white", {0xFF, 0xFF, 0xFF}, "full white"},
    {"movie", {0x20, 0x20, 0x60}, "visible dark blue-purple bias light"},
    {"night", {0x30, 0x00, 0x00}, "low red above visibility threshold"},
    {"off", {0x00, 0x00, 0x00}, "direct RGB off"},
};

enum class TakeoverTier {
    Tier1,
    Tier2WarnOnly,
    NeverStop,
};

struct TakeoverRule {
    const char* name;
    bool service;
    bool process;
    TakeoverTier tier;
};

struct TakeoverTarget {
    std::string name;
    bool service = false;
    bool process = false;
    TakeoverTier tier = TakeoverTier::Tier1;
    bool allowed_to_stop = false;
    std::vector<unsigned long> pids;
    bool service_exists = false;
    bool service_running = false;
};

const TakeoverRule kTakeoverRules[] = {
    {"LightingService", true, true, TakeoverTier::Tier1},
    {"ArmourySocketServer", true, true, TakeoverTier::Tier1},
    {"ArmourySwAgent", true, true, TakeoverTier::Tier1},
    {"ArmouryHtmlDebugServer", true, true, TakeoverTier::Tier1},
    {"Aura", true, true, TakeoverTier::Tier1},
    {"OpenRGB", false, true, TakeoverTier::Tier1},
    {"OpenAuraSDK", false, true, TakeoverTier::Tier1},
    {"ArmouryCrate.Service", true, true, TakeoverTier::Tier2WarnOnly},
    {"ArmouryCrate.UserSessionHelper", true, true, TakeoverTier::Tier2WarnOnly},
    {"asus_framework", true, true, TakeoverTier::Tier2WarnOnly},
    {"AsusCertService", true, true, TakeoverTier::NeverStop},
};

std::string hex_byte(uint8_t value) {
    std::ostringstream oss;
    oss << std::uppercase << std::hex << std::setw(2) << std::setfill('0') << static_cast<int>(value);
    return oss.str();
}

std::string hex_word(uint16_t value) {
    std::ostringstream oss;
    oss << "0x" << std::uppercase << std::hex << std::setw(4) << std::setfill('0') << static_cast<int>(value);
    return oss.str();
}

std::string hex_offset(uint8_t value) {
    std::ostringstream oss;
    oss << "+0x" << std::uppercase << std::hex << std::setw(2) << std::setfill('0') << static_cast<int>(value);
    return oss.str();
}

std::string lower_ascii(std::string value) {
    std::transform(value.begin(), value.end(), value.begin(), [](unsigned char ch) {
        if (ch >= 'A' && ch <= 'Z') {
            return static_cast<char>(ch - 'A' + 'a');
        }
        return static_cast<char>(ch);
    });
    return value;
}

std::string strip_exe_suffix(const std::string& value) {
    const std::string lower = lower_ascii(value);
    if (lower.size() > 4 && lower.substr(lower.size() - 4) == ".exe") {
        return value.substr(0, value.size() - 4);
    }
    return value;
}

std::string json_escape(const std::string& value) {
    std::ostringstream out;
    for (char c : value) {
        switch (c) {
        case '"':
            out << "\\\"";
            break;
        case '\\':
            out << "\\\\";
            break;
        case '\n':
            out << "\\n";
            break;
        case '\r':
            out << "\\r";
            break;
        case '\t':
            out << "\\t";
            break;
        default:
            out << c;
            break;
        }
    }
    return out.str();
}

std::string parent_directory(const std::string& path) {
    const size_t pos = path.find_last_of("\\/");
    if (pos == std::string::npos) {
        return ".";
    }
    return path.substr(0, pos);
}

std::string project_root_directory() {
    const std::string exe_dir = executable_directory();
    const std::string exe_dir_lower = lower_ascii(exe_dir);
    if (exe_dir_lower.size() >= 4 && exe_dir_lower.substr(exe_dir_lower.size() - 4) == "\\bin") {
        return parent_directory(exe_dir);
    }
    if (exe_dir_lower.size() >= 4 && exe_dir_lower.substr(exe_dir_lower.size() - 4) == "/bin") {
        return parent_directory(exe_dir);
    }
    return ".";
}

std::string takeover_state_path() {
    const std::string root = project_root_directory();
    CreateDirectoryA((root + "\\.sylphie").c_str(), nullptr);
    return root + "\\.sylphie\\takeover_state.json";
}

void print_help() {
    std::cout
        << "sylphie_rgb.exe - Sylphie native RGB CLI for ASUS PRIME B450M-GAMING/BR\n\n"
        << "Usage:\n"
        << "  sylphie_rgb.exe set RRGGBB [--dry-run] [--verbose]\n"
        << "  sylphie_rgb.exe off [--dry-run] [--verbose]\n"
        << "  sylphie_rgb.exe scene <name> [--dry-run] [--verbose]\n"
        << "  sylphie_rgb.exe scenes\n"
        << "  sylphie_rgb.exe calibrate --dry-run\n"
        << "  sylphie_rgb.exe bus-status\n"
        << "  sylphie_rgb.exe takeover-check\n"
        << "  sylphie_rgb.exe takeover --dry-run [--include-armoury-core]\n"
        << "  sylphie_rgb.exe takeover --execute --i-accept-stopping-lighting-services [--include-armoury-core]\n"
        << "  sylphie_rgb.exe restore-services\n"
        << "  sylphie_rgb.exe recover [--verbose]\n"
        << "  sylphie_rgb.exe recover-set RRGGBB [--verbose]\n"
        << "  sylphie_rgb.exe doctor\n"
        << "  sylphie_rgb.exe --help\n\n"
        << "Notes:\n"
        << "  set/off/scene use Aura direct RGB register 0x8101 with payload order R G B.\n"
        << "  off writes RGB 000000 through the same direct RGB path.\n"
        << "  scene off uses the same direct RGB path as off.\n"
        << "  inpout32.dll must be next to sylphie_rgb.exe or loadable by Windows.\n";
}

bool take_flag(std::vector<std::string>& args, const std::string& flag) {
    for (auto it = args.begin(); it != args.end(); ++it) {
        if (*it == flag) {
            args.erase(it);
            return true;
        }
    }
    return false;
}

void print_dry_run_sequence(uint8_t r, uint8_t g, uint8_t b) {
    std::cout << "Dry run: no hardware writes will be performed.\n";
    std::cout << "SMBus base: 0x0B20\n";
    std::cout << "Aura/ENE addr7: 0x40\n\n";
    std::cout << "Exact direct sequence:\n";
    std::cout << "  select 0x8020 -> write 0x01\n";
    std::cout << "  select 0x80A0 -> write 0x01\n";
    std::cout << "  select 0x8101 -> block RGB payload "
              << hex_byte(r) << ' ' << hex_byte(g) << ' ' << hex_byte(b) << "\n";
    std::cout << "  select 0x80A0 -> write 0x01\n\n";
    std::cout << "1. WORD_DATA  addr=0x40 CMD=0x00 D0=0x80 D1=0x20 ; select register 0x8020\n";
    std::cout << "2. BYTE_DATA  addr=0x40 CMD=0x01 D0=0x01           ; enable direct mode\n";
    std::cout << "3. WORD_DATA  addr=0x40 CMD=0x00 D0=0x80 D1=0xA0 ; select register 0x80A0\n";
    std::cout << "4. BYTE_DATA  addr=0x40 CMD=0x01 D0=0x01           ; apply\n";
    std::cout << "5. WORD_DATA  addr=0x40 CMD=0x00 D0=0x81 D1=0x01 ; select register 0x8101\n";
    std::cout << "6. BLOCK_DATA addr=0x40 CMD=0x03 LEN=0x03 PAYLOAD="
              << hex_byte(r) << ' ' << hex_byte(g) << ' ' << hex_byte(b)
              << " ; write RGB direct\n";
    std::cout << "7. WORD_DATA  addr=0x40 CMD=0x00 D0=0x80 D1=0xA0 ; select register 0x80A0\n";
    std::cout << "8. BYTE_DATA  addr=0x40 CMD=0x01 D0=0x01           ; apply\n";
}

std::string rgb_hex(const RgbColor& color) {
    return hex_byte(color.r) + hex_byte(color.g) + hex_byte(color.b);
}

const Scene* find_scene(const std::string& name) {
    for (const Scene& scene : kScenes) {
        if (name == scene.name) {
            return &scene;
        }
    }
    return nullptr;
}

void print_scenes(std::ostream& out) {
    out << "Available scenes:\n";
    out << std::left << std::setw(12) << "Name"
        << std::setw(8) << "RGB"
        << "Description\n";
    out << std::string(60, '-') << "\n";
    for (const Scene& scene : kScenes) {
        out << std::left << std::setw(12) << scene.name
            << std::setw(8) << rgb_hex(scene.color)
            << scene.description << "\n";
    }
}

void print_unknown_scene(const std::string& name) {
    std::cerr << "error: unknown scene '" << name << "'\n\n";
    print_scenes(std::cerr);
}

void print_calibration_sequence(std::ostream& out) {
    out << "Manual calibration sequence:\n";
    out << "Run each command manually and verify the visible result before continuing.\n\n";
    for (const Scene& step : kCalibrationSteps) {
        out << std::left << std::setw(8) << step.name
            << rgb_hex(step.color) << "  "
            << "sylphie_rgb.exe set " << rgb_hex(step.color)
            << "  ; " << step.description << "\n";
    }
}

bool query_service_running(SC_HANDLE scm, const std::string& service_name, bool& exists) {
    exists = false;
    SC_HANDLE service = OpenServiceA(scm, service_name.c_str(), SERVICE_QUERY_STATUS);
    if (service == nullptr) {
        return false;
    }
    exists = true;

    SERVICE_STATUS_PROCESS status = {};
    DWORD needed = 0;
    const BOOL ok = QueryServiceStatusEx(
        service,
        SC_STATUS_PROCESS_INFO,
        reinterpret_cast<LPBYTE>(&status),
        sizeof(status),
        &needed);
    CloseServiceHandle(service);
    return ok && status.dwCurrentState != SERVICE_STOPPED;
}

std::vector<unsigned long> find_exact_process_pids(const std::string& rule_name) {
    std::vector<unsigned long> pids;
    const std::string rule_lower = lower_ascii(rule_name);
    const HANDLE snapshot = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
    if (snapshot == INVALID_HANDLE_VALUE) {
        return pids;
    }

    PROCESSENTRY32 entry = {};
    entry.dwSize = sizeof(entry);
    if (!Process32First(snapshot, &entry)) {
        CloseHandle(snapshot);
        return pids;
    }

    do {
        const std::string process_name = strip_exe_suffix(entry.szExeFile);
        if (lower_ascii(process_name) == rule_lower) {
            pids.push_back(entry.th32ProcessID);
        }
    } while (Process32Next(snapshot, &entry));

    CloseHandle(snapshot);
    return pids;
}

std::vector<TakeoverTarget> collect_takeover_targets(bool include_armoury_core) {
    std::vector<TakeoverTarget> targets;
    SC_HANDLE scm = OpenSCManagerA(nullptr, nullptr, SC_MANAGER_CONNECT);
    for (const TakeoverRule& rule : kTakeoverRules) {
        TakeoverTarget target;
        target.name = rule.name;
        target.service = rule.service;
        target.process = rule.process;
        target.tier = rule.tier;
        target.allowed_to_stop =
            rule.tier == TakeoverTier::Tier1 ||
            (include_armoury_core && rule.tier == TakeoverTier::Tier2WarnOnly && target.name != "AsusCertService");

        if (rule.service && scm != nullptr) {
            target.service_running = query_service_running(scm, target.name, target.service_exists);
        }
        if (rule.process) {
            target.pids = find_exact_process_pids(target.name);
        }

        if (target.service_running || !target.pids.empty()) {
            targets.push_back(target);
        }
    }
    if (scm != nullptr) {
        CloseServiceHandle(scm);
    }
    return targets;
}

const char* tier_label(TakeoverTier tier) {
    switch (tier) {
    case TakeoverTier::Tier1:
        return "tier1";
    case TakeoverTier::Tier2WarnOnly:
        return "tier2";
    case TakeoverTier::NeverStop:
        return "never-stop";
    }
    return "unknown";
}

void print_takeover_plan(const std::vector<TakeoverTarget>& targets, bool execute) {
    std::cout << "Sylphie takeover " << (execute ? "execute plan" : "dry-run plan") << "\n";
    if (targets.empty()) {
        std::cout << "[ok] no whitelisted lighting service/process candidates found\n";
        return;
    }

    for (const TakeoverTarget& target : targets) {
        std::cout << "- " << target.name << " (" << tier_label(target.tier) << ")";
        if (target.allowed_to_stop) {
            std::cout << " action=" << (execute ? "stop/terminate" : "would stop/terminate");
        } else {
            std::cout << " action=warn-only";
        }
        std::cout << "\n";
        if (target.service) {
            if (target.service_exists) {
                std::cout << "  service: " << (target.service_running ? "running" : "exists but not running") << "\n";
            } else {
                std::cout << "  service: not found\n";
            }
        }
        if (!target.pids.empty()) {
            std::cout << "  processes:";
            for (unsigned long pid : target.pids) {
                std::cout << " " << pid;
            }
            std::cout << "\n";
        }
    }
}

bool stop_service_by_name(SC_HANDLE scm, const std::string& service_name, std::string& report) {
    SC_HANDLE service = OpenServiceA(scm, service_name.c_str(), SERVICE_STOP | SERVICE_QUERY_STATUS);
    if (service == nullptr) {
        report = "service not found or access denied";
        return false;
    }

    SERVICE_STATUS_PROCESS status = {};
    DWORD needed = 0;
    if (!QueryServiceStatusEx(service, SC_STATUS_PROCESS_INFO, reinterpret_cast<LPBYTE>(&status), sizeof(status), &needed)) {
        CloseServiceHandle(service);
        report = "could not query service";
        return false;
    }
    if (status.dwCurrentState == SERVICE_STOPPED) {
        CloseServiceHandle(service);
        report = "already stopped";
        return false;
    }

    SERVICE_STATUS control_status = {};
    if (!ControlService(service, SERVICE_CONTROL_STOP, &control_status)) {
        const DWORD error = GetLastError();
        CloseServiceHandle(service);
        report = "stop failed: " + windows_error_message(error);
        return false;
    }

    for (int i = 0; i < 20; ++i) {
        Sleep(250);
        if (QueryServiceStatusEx(service, SC_STATUS_PROCESS_INFO, reinterpret_cast<LPBYTE>(&status), sizeof(status), &needed) &&
            status.dwCurrentState == SERVICE_STOPPED) {
            CloseServiceHandle(service);
            report = "stopped";
            return true;
        }
    }

    CloseServiceHandle(service);
    report = "stop requested; service did not report stopped within timeout";
    return true;
}

bool terminate_process_by_pid(unsigned long pid, std::string& report) {
    HANDLE process = OpenProcess(PROCESS_TERMINATE | SYNCHRONIZE, FALSE, pid);
    if (process == nullptr) {
        report = "process not openable";
        return false;
    }
    if (!TerminateProcess(process, 1)) {
        const DWORD error = GetLastError();
        CloseHandle(process);
        report = "terminate failed: " + windows_error_message(error);
        return false;
    }
    WaitForSingleObject(process, 1500);
    CloseHandle(process);
    report = "terminated";
    return true;
}

void write_takeover_state(const std::vector<std::string>& stopped_services, const std::vector<unsigned long>& killed_pids) {
    const std::string path = takeover_state_path();
    std::ofstream out(path, std::ios::trunc);
    if (!out) {
        throw std::runtime_error("could not write takeover state: " + path);
    }

    out << "{\n";
    out << "  \"version\": 1,\n";
    out << "  \"stopped_services\": [";
    for (size_t i = 0; i < stopped_services.size(); ++i) {
        if (i != 0) {
            out << ", ";
        }
        out << "\"" << json_escape(stopped_services[i]) << "\"";
    }
    out << "],\n";
    out << "  \"terminated_process_pids\": [";
    for (size_t i = 0; i < killed_pids.size(); ++i) {
        if (i != 0) {
            out << ", ";
        }
        out << killed_pids[i];
    }
    out << "]\n";
    out << "}\n";
}

std::vector<std::string> read_stopped_services_from_state() {
    const std::string path = takeover_state_path();
    std::ifstream in(path);
    if (!in) {
        return {};
    }
    const std::string content((std::istreambuf_iterator<char>(in)), std::istreambuf_iterator<char>());
    const std::string key = "\"stopped_services\"";
    size_t pos = content.find(key);
    if (pos == std::string::npos) {
        return {};
    }
    pos = content.find('[', pos);
    const size_t end = content.find(']', pos);
    if (pos == std::string::npos || end == std::string::npos) {
        return {};
    }

    std::vector<std::string> services;
    size_t cursor = pos + 1;
    while (cursor < end) {
        cursor = content.find('"', cursor);
        if (cursor == std::string::npos || cursor >= end) {
            break;
        }
        ++cursor;
        std::ostringstream item;
        bool escaped = false;
        for (; cursor < end; ++cursor) {
            const char c = content[cursor];
            if (escaped) {
                item << c;
                escaped = false;
                continue;
            }
            if (c == '\\') {
                escaped = true;
                continue;
            }
            if (c == '"') {
                ++cursor;
                break;
            }
            item << c;
        }
        services.push_back(item.str());
    }
    return services;
}

bool start_service_by_name(SC_HANDLE scm, const std::string& service_name, std::string& report) {
    SC_HANDLE service = OpenServiceA(scm, service_name.c_str(), SERVICE_START | SERVICE_QUERY_STATUS);
    if (service == nullptr) {
        report = "service not found or access denied";
        return false;
    }
    if (!StartServiceA(service, 0, nullptr)) {
        const DWORD error = GetLastError();
        if (error == ERROR_SERVICE_ALREADY_RUNNING) {
            CloseServiceHandle(service);
            report = "already running";
            return true;
        }
        CloseServiceHandle(service);
        report = "start failed: " + windows_error_message(error);
        return false;
    }
    CloseServiceHandle(service);
    report = "start requested";
    return true;
}

int run_bus_status();
int run_recover(bool verbose);

int run_takeover(bool dry_run, bool execute, bool accepted_stop, bool include_armoury_core, bool verbose) {
    if (verbose) {
        std::cout << "Takeover state path: " << takeover_state_path() << "\n";
    }
    if (dry_run && execute) {
        std::cerr << "error: takeover cannot use --dry-run and --execute together\n";
        return kExitUsage;
    }
    if (!dry_run && !execute) {
        dry_run = true;
    }
    if (execute && !accepted_stop) {
        std::cerr << "error: takeover --execute requires --i-accept-stopping-lighting-services\n";
        return kExitUsage;
    }

    const auto targets = collect_takeover_targets(include_armoury_core);
    print_takeover_plan(targets, execute);
    if (dry_run) {
        std::cout << "Dry run: no services or processes were stopped.\n";
        return kExitOk;
    }

    std::vector<std::string> stopped_services;
    std::vector<unsigned long> killed_pids;
    SC_HANDLE scm = OpenSCManagerA(nullptr, nullptr, SC_MANAGER_CONNECT);
    if (scm == nullptr) {
        throw std::runtime_error("could not open Service Control Manager: " + windows_error_message(GetLastError()));
    }

    std::cout << "\nStopping allowed services first:\n";
    for (const TakeoverTarget& target : targets) {
        if (!target.allowed_to_stop || !target.service || !target.service_exists || !target.service_running) {
            continue;
        }
        std::string report;
        const bool stopped = stop_service_by_name(scm, target.name, report);
        std::cout << "  " << target.name << ": " << report << "\n";
        if (stopped) {
            stopped_services.push_back(target.name);
        }
    }
    CloseServiceHandle(scm);

    Sleep(1000);

    std::cout << "\nTerminating allowed whitelisted processes still running:\n";
    for (const TakeoverTarget& original : targets) {
        if (!original.allowed_to_stop || !original.process) {
            continue;
        }
        const std::vector<unsigned long> pids = find_exact_process_pids(original.name);
        for (unsigned long pid : pids) {
            std::string report;
            const bool killed = terminate_process_by_pid(pid, report);
            std::cout << "  " << original.name << " pid=" << pid << ": " << report << "\n";
            if (killed) {
                killed_pids.push_back(pid);
            }
        }
    }

    write_takeover_state(stopped_services, killed_pids);
    std::cout << "\nSaved takeover state: " << takeover_state_path() << "\n";

    std::cout << "\nPost-takeover bus status:\n";
    run_bus_status();

    std::cout << "\nRunning conservative recovery:\n";
    const int recover_code = run_recover(verbose);
    if (recover_code != kExitOk) {
        return recover_code;
    }

    std::cout << "\nTakeover complete. Armoury/Aura/OpenRGB may not control RGB again until restore or reboot.\n";
    return kExitOk;
}

int run_restore_services() {
    const std::vector<std::string> services = read_stopped_services_from_state();
    std::cout << "Sylphie restore-services\n";
    if (services.empty()) {
        std::cout << "No stopped services recorded in takeover state.\n";
        return kExitOk;
    }

    SC_HANDLE scm = OpenSCManagerA(nullptr, nullptr, SC_MANAGER_CONNECT);
    if (scm == nullptr) {
        throw std::runtime_error("could not open Service Control Manager: " + windows_error_message(GetLastError()));
    }

    for (const std::string& service : services) {
        std::string report;
        start_service_by_name(scm, service, report);
        std::cout << "  " << service << ": " << report << "\n";
    }
    CloseServiceHandle(scm);
    std::cout << "restore-services does not recreate standalone processes; it only restarts services Sylphie stopped.\n";
    return kExitOk;
}

int run_doctor() {
    bool failed = false;

    std::cout << "Sylphie RGB doctor\n";
    std::cout << "Target SMBus base: 0x0B20\n";
    std::cout << "Aura/ENE addr7: 0x40\n\n";

    const std::string dll_path = executable_inpout32_path();
    if (file_exists(dll_path)) {
        std::cout << "[ok] inpout32.dll found next to executable: " << dll_path << "\n";
    } else {
        std::cout << "[warn] inpout32.dll not found next to executable: " << dll_path << "\n";
    }

    try {
        Piix4Smbus smbus;
        std::cout << "[ok] inpout32.dll loaded and exports Inp32/Out32\n\n";

        const auto snapshot = smbus.read_safe_register_snapshot();
        std::cout << "PIIX4 register snapshot (safe offsets only; +0x07 SMBBLKDAT not read):\n";
        for (const auto& item : snapshot) {
            std::cout << "  " << hex_offset(item.first) << " = 0x" << hex_byte(item.second) << "\n";
        }

        const uint8_t status = smbus.host_status();
        if ((status & Piix4Smbus::kStatusBusy) != 0) {
            std::cout << "[warn] SMBus host status bit BUSY is set (status=0x" << hex_byte(status) << ")\n";
        } else {
            std::cout << "[ok] SMBus host status bit BUSY is clear (status=0x" << hex_byte(status) << ")\n";
        }
    } catch (const std::exception& ex) {
        failed = true;
        std::cout << "[fail] " << ex.what() << "\n";
    }

    std::cout << "\nASUS/Aura process check:\n";
    const auto processes = find_asus_lighting_processes();
    if (processes.empty()) {
        std::cout << "[ok] no common ASUS/Aura lighting processes detected\n";
    } else {
        std::cout << "[warn] detected processes that can contend for the SMBus:\n";
        for (const auto& process : processes) {
            std::cout << "  " << process.process_name << " pid=" << process.pid
                      << " rule=" << process.matched_rule << "\n";
        }
    }

    std::cout << "\nDoctor performed reads only and did not write to hardware.\n";
    return failed ? kExitRuntimeError : kExitOk;
}

void print_process_conflicts(const std::vector<ProcessMatch>& processes) {
    if (processes.empty()) {
        std::cout << "[ok] no common ASUS/Aura/OpenRGB processes detected\n";
        return;
    }

    std::cout << "[warn] detected processes that can contend for the SMBus:\n";
    for (const auto& process : processes) {
        std::cout << "  " << process.process_name << " pid=" << process.pid
                  << " rule=" << process.matched_rule << "\n";
    }
}

void print_ownership_conflicts(const OwnershipConflicts& conflicts) {
    std::cout << "Blocking conflicts:\n";
    if (conflicts.blocking_conflicts.empty()) {
        std::cout << "  [ok] none\n";
    } else {
        for (const auto& item : conflicts.blocking_conflicts) {
            std::cout << "  " << item << "\n";
        }
    }

    std::cout << "Warnings:\n";
    if (conflicts.warnings.empty()) {
        std::cout << "  [ok] none\n";
    } else {
        for (const auto& item : conflicts.warnings) {
            std::cout << "  " << item << "\n";
        }
    }
}

int run_bus_status() {
    Piix4Smbus smbus;
    const uint8_t status = smbus.host_status();

    std::cout << "PIIX4 SMBus bus status\n";
    std::cout << "base: 0x0B20\n";
    std::cout << "status: 0x" << hex_byte(status) << "\n";
    std::cout << "busy: " << (((status & Piix4Smbus::kStatusBusy) != 0) ? "true" : "false") << "\n";
    std::cout << "CNT(+0x02): 0x" << hex_byte(smbus.read8(Piix4Smbus::kOffsetHostControl)) << "\n";
    std::cout << "CMD(+0x03): 0x" << hex_byte(smbus.read8(Piix4Smbus::kOffsetHostCommand)) << "\n";
    std::cout << "ADDR(+0x04): 0x" << hex_byte(smbus.read8(Piix4Smbus::kOffsetHostAddress)) << "\n";
    std::cout << "D0(+0x05): 0x" << hex_byte(smbus.read8(Piix4Smbus::kOffsetHostData0)) << "\n";
    std::cout << "D1(+0x06): 0x" << hex_byte(smbus.read8(Piix4Smbus::kOffsetHostData1)) << "\n";
    std::cout << "safe snapshot excludes +0x07 / SMBBLKDAT\n";
    return kExitOk;
}

int run_takeover_check() {
    bool busy_persistent = false;

    std::cout << "Sylphie takeover check\n";
    try {
        Piix4Smbus smbus;
        const uint8_t status = smbus.host_status();
        std::cout << "SMBus status: 0x" << hex_byte(status) << "\n";
        std::cout << "SMBus busy: " << (((status & Piix4Smbus::kStatusBusy) != 0) ? "true" : "false") << "\n";
        if (!smbus.wait_not_busy(500)) {
            busy_persistent = true;
            std::cout << "[warn] SMBus busy persisted after 500ms\n";
        }
    } catch (const std::exception& ex) {
        std::cout << "[fail] " << ex.what() << "\n";
        return kExitRuntimeError;
    }

    const auto ownership = classify_process_matches(find_asus_lighting_processes());
    print_ownership_conflicts(ownership);
    std::cout << "takeover-check performed reads only and did not write hardware.\n";

    if (busy_persistent) {
        return kExitSmbusBusy;
    }
    if (!ownership.blocking_conflicts.empty()) {
        return kExitTakeoverConflict;
    }
    return kExitOk;
}

bool takeover_is_clear() {
    const auto ownership = classify_process_matches(find_asus_lighting_processes());
    if (!ownership.blocking_conflicts.empty()) {
        std::cerr << "error: controller conflict detected\n";
        print_ownership_conflicts(ownership);
        return false;
    }

    Piix4Smbus smbus;
    if (!smbus.wait_not_busy(500)) {
        std::cerr << "error: SMBus busy persisted after 500ms\n";
        return false;
    }
    return true;
}

int write_rgb(uint8_t r, uint8_t g, uint8_t b, bool force, bool verbose, bool recover_first) {
    Piix4Smbus smbus(Piix4Smbus::kDefaultBase, force, verbose);
    AuraEne aura(smbus);
    if (recover_first) {
        aura.recover();
    }
    aura.set_rgb(r, g, b);
    std::cout << "ok: wrote RGB " << hex_byte(r) << hex_byte(g) << hex_byte(b)
              << " through Aura direct register " << hex_word(AuraEne::kRgbDirectRegister) << "\n";
    return kExitOk;
}

int run_rgb_command(
    const RgbColor& color,
    bool dry_run,
    bool force,
    bool verbose,
    bool recover_first,
    bool strict_takeover) {
    if (dry_run) {
        print_dry_run_sequence(color.r, color.g, color.b);
        return kExitOk;
    }
    if (strict_takeover && !takeover_is_clear()) {
        return kExitTakeoverConflict;
    }
    return write_rgb(color.r, color.g, color.b, force, verbose, recover_first);
}

int run_calibrate(bool dry_run, bool accepted_hardware_calibration, bool force, bool verbose) {
    if (force || verbose) {
        std::cerr << "error: calibrate does not accept --force or --verbose\n";
        return kExitUsage;
    }

    if (!dry_run && !accepted_hardware_calibration) {
        std::cerr
            << "error: calibrate refuses to run without --dry-run unless "
            << "--i-accept-hardware-calibration is passed\n\n";
        print_calibration_sequence(std::cerr);
        return kExitUsage;
    }

    if (dry_run) {
        std::cout << "Dry run: calibration will not write hardware.\n\n";
    } else {
        std::cout << "Manual hardware calibration acknowledged. No automatic color cycle will run.\n\n";
    }
    print_calibration_sequence(std::cout);
    return kExitOk;
}

int run_recover(bool verbose) {
    Piix4Smbus smbus(Piix4Smbus::kDefaultBase, false, verbose);
    AuraEne aura(smbus);
    aura.recover();
    std::cout << "ok: recovery sequence completed\n";
    return kExitOk;
}

int run_recover_set(const RgbColor& color, bool verbose) {
    Piix4Smbus smbus(Piix4Smbus::kDefaultBase, false, verbose);
    AuraEne aura(smbus);
    aura.recover();
    aura.set_rgb(color.r, color.g, color.b);
    std::cout << "ok: recovered and wrote RGB " << rgb_hex(color) << "\n";
    return kExitOk;
}
}

int main(int argc, char** argv) {
    try {
        std::vector<std::string> args;
        for (int i = 1; i < argc; ++i) {
            args.emplace_back(argv[i]);
        }

        if (args.empty() || (args.size() == 1 && args[0] == "--help")) {
            print_help();
            return kExitOk;
        }

        const bool dry_run = take_flag(args, "--dry-run");
        const bool force = take_flag(args, "--force");
        const bool verbose = take_flag(args, "--verbose");
        const bool accepted_hardware_calibration = take_flag(args, "--i-accept-hardware-calibration");
        const bool accepted_stopping_services = take_flag(args, "--i-accept-stopping-lighting-services");
        const bool recover_first = take_flag(args, "--recover-first");
        const bool strict_takeover = take_flag(args, "--strict-takeover");
        const bool execute = take_flag(args, "--execute");
        const bool include_armoury_core = take_flag(args, "--include-armoury-core");

        if (args.size() == 1 && args[0] == "doctor") {
            if (dry_run || force || verbose || accepted_hardware_calibration || accepted_stopping_services || recover_first || strict_takeover || execute || include_armoury_core) {
                std::cerr << "error: doctor does not accept flags\n";
                return kExitUsage;
            }
            return run_doctor();
        }

        if (args.size() == 1 && args[0] == "scenes") {
            if (dry_run || force || verbose || accepted_hardware_calibration || accepted_stopping_services || recover_first || strict_takeover || execute || include_armoury_core) {
                std::cerr << "error: scenes does not accept flags\n";
                return kExitUsage;
            }
            print_scenes(std::cout);
            return kExitOk;
        }

        if (args.size() == 1 && args[0] == "bus-status") {
            if (dry_run || force || verbose || accepted_hardware_calibration || accepted_stopping_services || recover_first || strict_takeover || execute || include_armoury_core) {
                std::cerr << "error: bus-status does not accept flags\n";
                return kExitUsage;
            }
            return run_bus_status();
        }

        if (args.size() == 1 && args[0] == "takeover-check") {
            if (dry_run || force || verbose || accepted_hardware_calibration || accepted_stopping_services || recover_first || strict_takeover || execute || include_armoury_core) {
                std::cerr << "error: takeover-check does not accept flags\n";
                return kExitUsage;
            }
            return run_takeover_check();
        }

        if (args.size() == 1 && args[0] == "takeover") {
            if (force || accepted_hardware_calibration || recover_first || strict_takeover) {
                std::cerr << "error: takeover accepts only --dry-run, --execute, --i-accept-stopping-lighting-services, --include-armoury-core, and --verbose\n";
                return kExitUsage;
            }
            return run_takeover(dry_run, execute, accepted_stopping_services, include_armoury_core, verbose);
        }

        if (args.size() == 1 && args[0] == "restore-services") {
            if (dry_run || force || verbose || accepted_hardware_calibration || accepted_stopping_services || recover_first || strict_takeover || execute || include_armoury_core) {
                std::cerr << "error: restore-services does not accept flags\n";
                return kExitUsage;
            }
            return run_restore_services();
        }

        if (args.size() == 1 && args[0] == "recover") {
            if (dry_run || force || accepted_hardware_calibration || accepted_stopping_services || recover_first || strict_takeover || execute || include_armoury_core) {
                std::cerr << "error: recover only accepts --verbose\n";
                return kExitUsage;
            }
            return run_recover(verbose);
        }

        if (args.size() == 2 && args[0] == "recover-set") {
            if (dry_run || force || accepted_hardware_calibration || accepted_stopping_services || recover_first || strict_takeover || execute || include_armoury_core) {
                std::cerr << "error: recover-set only accepts --verbose\n";
                return kExitUsage;
            }
            RgbColor color;
            if (!parse_rgb_hex(args[1], color)) {
                std::cerr << "error: expected color as exactly 6 hexadecimal digits, for example FF0000\n";
                return kExitUsage;
            }
            return run_recover_set(color, verbose);
        }

        if (args.size() == 1 && args[0] == "calibrate") {
            if (accepted_stopping_services || recover_first || strict_takeover || execute || include_armoury_core) {
                std::cerr << "error: calibrate does not accept takeover/recovery-control flags\n";
                return kExitUsage;
            }
            return run_calibrate(dry_run, accepted_hardware_calibration, force, verbose);
        }

        if (args.size() == 2 && args[0] == "set") {
            if (accepted_hardware_calibration || accepted_stopping_services || execute || include_armoury_core) {
                std::cerr << "error: set does not accept calibration/takeover execution flags\n";
                return kExitUsage;
            }
            RgbColor color;
            if (!parse_rgb_hex(args[1], color)) {
                std::cerr << "error: expected color as exactly 6 hexadecimal digits, for example FF0000\n";
                return kExitUsage;
            }

            return run_rgb_command(color, dry_run, force, verbose, recover_first, strict_takeover);
        }

        if (args.size() == 1 && args[0] == "off") {
            if (accepted_hardware_calibration || accepted_stopping_services || execute || include_armoury_core) {
                std::cerr << "error: off does not accept calibration/takeover execution flags\n";
                return kExitUsage;
            }
            const RgbColor off = {0x00, 0x00, 0x00};
            return run_rgb_command(off, dry_run, force, verbose, recover_first, strict_takeover);
        }

        if (args.size() == 2 && args[0] == "scene") {
            if (accepted_hardware_calibration || accepted_stopping_services || execute || include_armoury_core) {
                std::cerr << "error: scene does not accept calibration/takeover execution flags\n";
                return kExitUsage;
            }
            const Scene* scene = find_scene(args[1]);
            if (scene == nullptr) {
                print_unknown_scene(args[1]);
                return kExitUsage;
            }

            std::cout << "Scene: " << scene->name << " RGB=" << rgb_hex(scene->color)
                      << " - " << scene->description << "\n";
            return run_rgb_command(scene->color, dry_run, force, verbose, recover_first, strict_takeover);
        }

        std::cerr << "error: invalid command or arguments\n\n";
        print_help();
        return kExitUsage;
    } catch (const std::exception& ex) {
        std::cerr << "error: " << ex.what() << "\n";
        return kExitRuntimeError;
    }
}
