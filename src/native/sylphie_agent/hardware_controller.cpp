#include "hardware_controller.hpp"

#include "../sylphie_rgb/aura_ene.hpp"
#include "../sylphie_rgb/piix4_smbus.hpp"
#include "../sylphie_rgb/process_check.hpp"

#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#include <tlhelp32.h>

#include <algorithm>
#include <fstream>
#include <iterator>
#include <sstream>
#include <stdexcept>

namespace {
enum class TakeoverTier {
    Tier1,
    Tier2WarnOnly,
    NeverStop,
    Ignore,
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
    std::string service_state;
    std::string service_name;
    std::string start_mode;
    std::string display_name;
    std::string binary_path;
    unsigned long service_pid = 0;
};

const TakeoverRule kTakeoverRules[] = {
    {"LightingService", true, true, TakeoverTier::Tier1},
    {"Aura Wallpaper Service", true, false, TakeoverTier::Tier1},
    {"AuraWallpaperService", false, true, TakeoverTier::Tier1},
    {"ArmourySocketServer", false, true, TakeoverTier::Tier1},
    {"ArmourySwAgent", false, true, TakeoverTier::Tier1},
    {"ArmouryHtmlDebugServer", false, true, TakeoverTier::Tier1},
    {"OpenRGB", false, true, TakeoverTier::Tier1},
    {"OpenAuraSDK", false, true, TakeoverTier::Tier1},
    {"ArmouryCrateService", true, false, TakeoverTier::Tier2WarnOnly},
    {"asComSvc", true, false, TakeoverTier::Tier2WarnOnly},
    {"ArmouryCrate.Service", true, false, TakeoverTier::Tier2WarnOnly},
    {"ArmouryCrate", false, true, TakeoverTier::Tier2WarnOnly},
    {"ArmouryCrate.Service", false, true, TakeoverTier::Tier2WarnOnly},
    {"ArmouryCrate.UserSessionHelper", false, true, TakeoverTier::Tier2WarnOnly},
    {"asus_framework", false, true, TakeoverTier::Tier2WarnOnly},
    {"AsusCertService", true, true, TakeoverTier::NeverStop},
    {"asus", true, false, TakeoverTier::Ignore},
    {"asusm", true, false, TakeoverTier::Ignore},
    {"AsusROGLSLService", true, false, TakeoverTier::Ignore},
};

std::string hex_byte(uint8_t value) {
    const char* digits = "0123456789ABCDEF";
    std::string out;
    out.push_back(digits[(value >> 4) & 0x0F]);
    out.push_back(digits[value & 0x0F]);
    return out;
}

std::string hex_word(uint16_t value) {
    std::ostringstream out;
    out << "0x" << std::uppercase << std::hex;
    out.width(4);
    out.fill('0');
    out << static_cast<int>(value);
    return out.str();
}

std::string rgb_payload_hex(const RgbColor& color) {
    return hex_byte(color.r) + hex_byte(color.g) + hex_byte(color.b);
}

OwnershipConflicts current_ownership_conflicts() {
    return classify_process_matches(find_asus_lighting_processes());
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

std::string agent_windows_error_message(DWORD error) {
    char* message = nullptr;
    FormatMessageA(
        FORMAT_MESSAGE_ALLOCATE_BUFFER | FORMAT_MESSAGE_FROM_SYSTEM | FORMAT_MESSAGE_IGNORE_INSERTS,
        nullptr,
        error,
        0,
        reinterpret_cast<LPSTR>(&message),
        0,
        nullptr);
    std::string text = message != nullptr ? message : "unknown Windows error";
    if (message != nullptr) {
        LocalFree(message);
    }
    while (!text.empty() && (text.back() == '\r' || text.back() == '\n')) {
        text.pop_back();
    }
    return text;
}

std::string service_state_text(DWORD state) {
    switch (state) {
    case SERVICE_STOPPED:
        return "stopped";
    case SERVICE_START_PENDING:
        return "start_pending";
    case SERVICE_STOP_PENDING:
        return "stop_pending";
    case SERVICE_RUNNING:
        return "running";
    case SERVICE_CONTINUE_PENDING:
        return "continue_pending";
    case SERVICE_PAUSE_PENDING:
        return "pause_pending";
    case SERVICE_PAUSED:
        return "paused";
    default:
        return "unknown";
    }
}

std::string start_mode_text(DWORD start_type) {
    switch (start_type) {
    case SERVICE_AUTO_START:
        return "auto";
    case SERVICE_BOOT_START:
        return "boot";
    case SERVICE_DEMAND_START:
        return "manual";
    case SERVICE_DISABLED:
        return "disabled";
    case SERVICE_SYSTEM_START:
        return "system";
    default:
        return "unknown";
    }
}

std::string executable_directory() {
    char path[MAX_PATH] = {};
    const DWORD length = GetModuleFileNameA(nullptr, path, MAX_PATH);
    if (length == 0 || length >= MAX_PATH) {
        return ".";
    }
    std::string text(path, path + length);
    const size_t pos = text.find_last_of("\\/");
    if (pos == std::string::npos) {
        return ".";
    }
    return text.substr(0, pos);
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
    const std::string lower = lower_ascii(exe_dir);
    if (lower.size() >= 4 && lower.substr(lower.size() - 4) == "\\bin") {
        return parent_directory(exe_dir);
    }
    return ".";
}

std::string takeover_state_path() {
    const std::string root = project_root_directory();
    CreateDirectoryA((root + "\\.sylphie").c_str(), nullptr);
    return root + "\\.sylphie\\takeover_state.json";
}

const char* tier_label(TakeoverTier tier) {
    switch (tier) {
    case TakeoverTier::Tier1:
        return "tier1";
    case TakeoverTier::Tier2WarnOnly:
        return "tier2-warning";
    case TakeoverTier::NeverStop:
        return "never-stop";
    case TakeoverTier::Ignore:
        return "ignore";
    }
    return "unknown";
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

std::string find_service_name_by_name_or_display(SC_HANDLE scm, const std::string& query_name) {
    SC_HANDLE direct = OpenServiceA(scm, query_name.c_str(), SERVICE_QUERY_STATUS);
    if (direct != nullptr) {
        CloseServiceHandle(direct);
        return query_name;
    }

    DWORD bytes_needed = 0;
    DWORD services_returned = 0;
    DWORD resume_handle = 0;
    EnumServicesStatusExA(
        scm,
        SC_ENUM_PROCESS_INFO,
        SERVICE_WIN32,
        SERVICE_STATE_ALL,
        nullptr,
        0,
        &bytes_needed,
        &services_returned,
        &resume_handle,
        nullptr);
    if (bytes_needed == 0) {
        return "";
    }

    std::vector<uint8_t> buffer(bytes_needed);
    resume_handle = 0;
    if (!EnumServicesStatusExA(
            scm,
            SC_ENUM_PROCESS_INFO,
            SERVICE_WIN32,
            SERVICE_STATE_ALL,
            buffer.data(),
            static_cast<DWORD>(buffer.size()),
            &bytes_needed,
            &services_returned,
            &resume_handle,
            nullptr)) {
        return "";
    }

    const std::string wanted = lower_ascii(query_name);
    ENUM_SERVICE_STATUS_PROCESSA* entries = reinterpret_cast<ENUM_SERVICE_STATUS_PROCESSA*>(buffer.data());
    for (DWORD i = 0; i < services_returned; ++i) {
        const std::string service_name = entries[i].lpServiceName != nullptr ? entries[i].lpServiceName : "";
        const std::string display_name = entries[i].lpDisplayName != nullptr ? entries[i].lpDisplayName : "";
        if (lower_ascii(service_name) == wanted || lower_ascii(display_name) == wanted) {
            return service_name;
        }
    }
    return "";
}

void query_service_details(SC_HANDLE scm, TakeoverTarget& target) {
    target.service_exists = false;
    target.service_running = false;
    target.service_state = "not_found";
    if (!target.service) {
        return;
    }

    const std::string service_name = find_service_name_by_name_or_display(scm, target.name);
    if (service_name.empty()) {
        return;
    }
    target.service_name = service_name;

    SC_HANDLE service = OpenServiceA(scm, service_name.c_str(), SERVICE_QUERY_STATUS | SERVICE_QUERY_CONFIG);
    if (service == nullptr) {
        return;
    }
    target.service_exists = true;

    SERVICE_STATUS_PROCESS status = {};
    DWORD needed = 0;
    if (QueryServiceStatusEx(
            service,
            SC_STATUS_PROCESS_INFO,
            reinterpret_cast<LPBYTE>(&status),
            sizeof(status),
            &needed)) {
        target.service_state = service_state_text(status.dwCurrentState);
        target.service_running = status.dwCurrentState != SERVICE_STOPPED;
        target.service_pid = status.dwProcessId;
    }

    DWORD bytes_needed = 0;
    QueryServiceConfigA(service, nullptr, 0, &bytes_needed);
    if (bytes_needed > 0) {
        std::vector<uint8_t> buffer(bytes_needed);
        QUERY_SERVICE_CONFIGA* config = reinterpret_cast<QUERY_SERVICE_CONFIGA*>(buffer.data());
        if (QueryServiceConfigA(service, config, bytes_needed, &bytes_needed)) {
            target.start_mode = start_mode_text(config->dwStartType);
            if (config->lpDisplayName != nullptr) {
                target.display_name = config->lpDisplayName;
            }
            if (config->lpBinaryPathName != nullptr) {
                target.binary_path = config->lpBinaryPathName;
            }
        }
    }

    CloseServiceHandle(service);
}

std::vector<TakeoverTarget> collect_takeover_targets(bool include_armoury_core, bool only_present) {
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
            query_service_details(scm, target);
        }
        if (rule.process) {
            target.pids = find_exact_process_pids(target.name);
        }

        if (!only_present || target.service_exists || !target.pids.empty()) {
            targets.push_back(target);
        }
    }
    if (scm != nullptr) {
        CloseServiceHandle(scm);
    }
    return targets;
}

std::string target_to_json(const TakeoverTarget& target) {
    const std::string output_name = target.service_exists && !target.service_name.empty() ? target.service_name : target.name;
    std::ostringstream out;
    out << "{"
        << "\"name\":" << json_string(output_name) << ","
        << "\"rule_name\":" << json_string(target.name) << ","
        << "\"display_name\":" << json_string_or_null(target.display_name) << ","
        << "\"tier\":" << json_string(tier_label(target.tier)) << ","
        << "\"service\":" << (target.service ? "true" : "false") << ","
        << "\"process\":" << (target.process ? "true" : "false") << ","
        << "\"allowed_to_stop\":" << (target.allowed_to_stop ? "true" : "false") << ","
        << "\"service_exists\":" << (target.service_exists ? "true" : "false") << ","
        << "\"process_exists\":" << (!target.pids.empty() ? "true" : "false") << ","
        << "\"state\":" << json_string(target.service_state.empty() ? "unknown" : target.service_state) << ","
        << "\"start_mode\":" << json_string_or_null(target.start_mode) << ","
        << "\"pid\":" << target.service_pid << ","
        << "\"account\":\"unknown\","
        << "\"privilege\":\"unknown\","
        << "\"path\":" << json_string_or_null(target.binary_path) << ","
        << "\"process_pids\":[";
    for (size_t i = 0; i < target.pids.size(); ++i) {
        if (i != 0) {
            out << ",";
        }
        out << target.pids[i];
    }
    out << "]}";
    return out.str();
}

std::string targets_json_array(const std::vector<TakeoverTarget>& targets) {
    std::ostringstream out;
    out << "[";
    for (size_t i = 0; i < targets.size(); ++i) {
        if (i != 0) {
            out << ",";
        }
        out << target_to_json(targets[i]);
    }
    out << "]";
    return out.str();
}

std::string conflict_rule_name(const std::string& conflict) {
    const std::string marker = " rule=";
    const size_t pos = conflict.find(marker);
    if (pos == std::string::npos) {
        return "";
    }
    return conflict.substr(pos + marker.size());
}

const TakeoverTarget* find_target_by_name(const std::vector<TakeoverTarget>& targets, const std::string& name) {
    const std::string lower_name = lower_ascii(name);
    for (const auto& target : targets) {
        if (lower_ascii(target.name) == lower_name) {
            return &target;
        }
    }
    return nullptr;
}

bool target_has_automatic_action(const TakeoverTarget& target) {
    return target.allowed_to_stop &&
           ((target.service && target.service_exists && target.service_running) ||
            (target.process && !target.pids.empty()));
}

std::vector<std::string> manual_action_required_for_blockers(
    const std::vector<std::string>& blocking_conflicts,
    const std::vector<TakeoverTarget>& targets) {
    std::vector<std::string> manual;
    for (const auto& conflict : blocking_conflicts) {
        const std::string rule_name = conflict_rule_name(conflict);
        const TakeoverTarget* target = find_target_by_name(targets, rule_name);
        if (target == nullptr || !target_has_automatic_action(*target)) {
            manual.push_back(conflict);
        }
    }
    return manual;
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
        report = "stop failed: " + agent_windows_error_message(error);
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
        report = "terminate failed: " + agent_windows_error_message(error);
        return false;
    }
    WaitForSingleObject(process, 1500);
    CloseHandle(process);
    report = "terminated";
    return true;
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
        report = "start failed: " + agent_windows_error_message(error);
        return false;
    }
    CloseServiceHandle(service);
    report = "start requested";
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
        out << json_string(stopped_services[i]);
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

std::string string_array_json(const std::vector<std::string>& values) {
    return json_array(values);
}
}

HardwareController::HardwareController(bool allow_conflicts)
    : allow_conflicts_(allow_conflicts) {
}

std::string HardwareController::doctor_json() {
    std::ostringstream out;
    out << "{";
    try {
        Piix4Smbus smbus;
        const auto snapshot = smbus.read_safe_register_snapshot();
        const auto ownership = current_ownership_conflicts();
        {
            std::lock_guard<std::mutex> lock(conflict_mutex_);
            last_blocking_conflicts_ = ownership.blocking_conflicts;
            last_warnings_ = ownership.warnings;
        }

        out << "\"inpout32_loaded\":true,"
            << "\"base\":\"0x0B20\","
            << "\"status\":\"0x" << hex_byte(smbus.host_status()) << "\","
            << "\"busy\":" << (smbus.host_busy() ? "true" : "false") << ","
            << "\"safe_snapshot\":{";
        for (size_t i = 0; i < snapshot.size(); ++i) {
            if (i != 0) {
                out << ",";
            }
            out << "\"0x" << hex_byte(snapshot[i].first) << "\":\"0x" << hex_byte(snapshot[i].second) << "\"";
        }
        out << "},"
            << "\"blocking_conflicts\":" << json_array(ownership.blocking_conflicts) << ","
            << "\"warnings\":" << json_array(ownership.warnings) << ","
            << "\"conflicting_processes\":" << json_array(ownership.blocking_conflicts);
    } catch (const std::exception& ex) {
        out << "\"inpout32_loaded\":false,\"error\":" << json_string(ex.what());
    }
    out << "}";
    return out.str();
}

std::string HardwareController::takeover_check_json() {
    bool busy_persistent = false;
    std::string status_text = "unknown";

    try {
        Piix4Smbus smbus;
        const uint8_t status = smbus.host_status();
        status_text = "0x" + hex_byte(status);
        if (!smbus.wait_not_busy(500)) {
            busy_persistent = true;
        }
    } catch (const std::exception& ex) {
        std::ostringstream fail;
        fail << "{\"ok\":false,\"error\":" << json_string(ex.what()) << "}";
        return fail.str();
    }

    const auto ownership = current_ownership_conflicts();
    {
        std::lock_guard<std::mutex> lock(conflict_mutex_);
        last_blocking_conflicts_ = ownership.blocking_conflicts;
        last_warnings_ = ownership.warnings;
    }

    std::ostringstream out;
    out << "{"
        << "\"ok\":" << ((!busy_persistent && ownership.blocking_conflicts.empty()) ? "true" : "false") << ","
        << "\"status\":" << json_string(status_text) << ","
        << "\"busy_persistent\":" << (busy_persistent ? "true" : "false") << ","
        << "\"blocking_conflicts\":" << json_array(ownership.blocking_conflicts) << ","
        << "\"warnings\":" << json_array(ownership.warnings) << ","
        << "\"conflicting_processes\":" << json_array(ownership.blocking_conflicts)
        << "}";
    return out.str();
}

std::string HardwareController::service_status_json() {
    const auto targets = collect_takeover_targets(false, false);
    const auto ownership = current_ownership_conflicts();
    {
        std::lock_guard<std::mutex> lock(conflict_mutex_);
        last_blocking_conflicts_ = ownership.blocking_conflicts;
        last_warnings_ = ownership.warnings;
    }

    std::ostringstream out;
    out << "{"
        << "\"ok\":true,"
        << "\"services\":" << targets_json_array(targets) << ","
        << "\"blocking_conflicts\":" << json_array(ownership.blocking_conflicts) << ","
        << "\"warnings\":" << json_array(ownership.warnings)
        << "}";
    return out.str();
}

std::string HardwareController::takeover_dry_run_json(bool include_armoury_core) {
    const auto targets = collect_takeover_targets(include_armoury_core, true);
    const auto ownership = current_ownership_conflicts();
    std::vector<std::string> stop_services_first;
    std::vector<std::string> terminate_processes_after;
    std::vector<std::string> manual_action_required;
    std::vector<std::string> warn_only;

    for (const auto& target : targets) {
        if (target.allowed_to_stop) {
            if (target.service && target.service_exists && target.service_running) {
                stop_services_first.push_back(target.service_name.empty() ? target.name : target.service_name);
            }
            if (target.process && !target.pids.empty()) {
                terminate_processes_after.push_back(target.name);
            }
        } else {
            warn_only.push_back(target.name);
        }
    }
    manual_action_required = manual_action_required_for_blockers(ownership.blocking_conflicts, targets);
    {
        std::lock_guard<std::mutex> lock(conflict_mutex_);
        last_blocking_conflicts_ = ownership.blocking_conflicts;
        last_warnings_ = ownership.warnings;
    }

    std::ostringstream out;
    out << "{"
        << "\"ok\":" << (manual_action_required.empty() ? "true" : "false") << ","
        << "\"mode\":\"dry-run\","
        << "\"message\":\"LightingService will be stopped first when present. AsusCertService is warning-only and will not be stopped by default.\","
        << "\"include_armoury_core\":" << (include_armoury_core ? "true" : "false") << ","
        << "\"targets\":" << targets_json_array(targets) << ","
        << "\"blocking_conflicts\":" << json_array(ownership.blocking_conflicts) << ","
        << "\"stop_services_first\":" << json_array(stop_services_first) << ","
        << "\"terminate_processes_after\":" << json_array(terminate_processes_after) << ","
        << "\"manual_action_required\":" << json_array(manual_action_required) << ","
        << "\"warnings_only\":" << json_array(warn_only)
        << "}";
    return out.str();
}

std::string HardwareController::takeover_execute_json(bool accepted_stop, bool include_armoury_core) {
    if (!accepted_stop) {
        throw std::runtime_error("takeover_execute requires i_accept_stopping_lighting_services=true");
    }

    std::lock_guard<std::mutex> lock(hardware_mutex_);
    const auto targets = collect_takeover_targets(include_armoury_core, true);
    std::vector<std::string> stopped_services;
    std::vector<unsigned long> killed_pids;
    std::vector<std::string> reports;

    SC_HANDLE scm = OpenSCManagerA(nullptr, nullptr, SC_MANAGER_CONNECT);
    if (scm == nullptr) {
        throw std::runtime_error("could not open Service Control Manager: " + agent_windows_error_message(GetLastError()));
    }

    for (const auto& target : targets) {
        if (!target.allowed_to_stop || !target.service || !target.service_exists || !target.service_running) {
            continue;
        }
        std::string report;
        const std::string service_name = target.service_name.empty() ? target.name : target.service_name;
        const bool stopped = stop_service_by_name(scm, service_name, report);
        reports.push_back("service " + service_name + ": " + report);
        if (stopped) {
            stopped_services.push_back(service_name);
        }
    }
    CloseServiceHandle(scm);

    Sleep(1000);

    for (const auto& target : targets) {
        if (!target.allowed_to_stop || !target.process) {
            continue;
        }
        const std::vector<unsigned long> pids = find_exact_process_pids(target.name);
        for (unsigned long pid : pids) {
            std::string report;
            const bool killed = terminate_process_by_pid(pid, report);
            reports.push_back("process " + target.name + " pid=" + std::to_string(pid) + ": " + report);
            if (killed) {
                killed_pids.push_back(pid);
            }
        }
    }

    write_takeover_state(stopped_services, killed_pids);

    Piix4Smbus smbus;
    AuraEne aura(smbus);
    aura.recover();

    refresh_ownership();
    std::ostringstream out;
    out << "{"
        << "\"ok\":true,"
        << "\"mode\":\"execute\","
        << "\"state_path\":" << json_string(takeover_state_path()) << ","
        << "\"stopped_services\":" << json_array(stopped_services) << ","
        << "\"terminated_process_pids\":[";
    for (size_t i = 0; i < killed_pids.size(); ++i) {
        if (i != 0) {
            out << ",";
        }
        out << killed_pids[i];
    }
    out << "],\"reports\":" << json_array(reports) << ","
        << "\"post_bus_status\":" << bus_status_json()
        << "}";
    return out.str();
}

std::string HardwareController::restore_services_json() {
    std::lock_guard<std::mutex> lock(hardware_mutex_);
    const std::vector<std::string> services = read_stopped_services_from_state();
    std::vector<std::string> reports;

    SC_HANDLE scm = OpenSCManagerA(nullptr, nullptr, SC_MANAGER_CONNECT);
    if (scm == nullptr) {
        throw std::runtime_error("could not open Service Control Manager: " + agent_windows_error_message(GetLastError()));
    }

    for (const std::string& service : services) {
        std::string report;
        start_service_by_name(scm, service, report);
        reports.push_back(service + ": " + report);
    }
    CloseServiceHandle(scm);

    std::ostringstream out;
    out << "{"
        << "\"ok\":true,"
        << "\"state_path\":" << json_string(takeover_state_path()) << ","
        << "\"restored_services\":" << json_array(services) << ","
        << "\"reports\":" << json_array(reports) << ","
        << "\"note\":\"restore-services only restarts services recorded by Sylphie; it does not recreate standalone processes\""
        << "}";
    return out.str();
}

std::string HardwareController::bus_status_json() {
    Piix4Smbus smbus;
    const uint8_t status = smbus.host_status();
    std::ostringstream out;
    out << "{"
        << "\"base\":\"0x0B20\","
        << "\"status\":\"0x" << hex_byte(status) << "\","
        << "\"busy\":" << (((status & Piix4Smbus::kStatusBusy) != 0) ? "true" : "false") << ","
        << "\"cnt\":\"0x" << hex_byte(smbus.read8(Piix4Smbus::kOffsetHostControl)) << "\","
        << "\"cmd\":\"0x" << hex_byte(smbus.read8(Piix4Smbus::kOffsetHostCommand)) << "\","
        << "\"addr\":\"0x" << hex_byte(smbus.read8(Piix4Smbus::kOffsetHostAddress)) << "\","
        << "\"d0\":\"0x" << hex_byte(smbus.read8(Piix4Smbus::kOffsetHostData0)) << "\","
        << "\"d1\":\"0x" << hex_byte(smbus.read8(Piix4Smbus::kOffsetHostData1)) << "\","
        << "\"excludes_smbblkdat\":true"
        << "}";
    return out.str();
}

void HardwareController::refresh_ownership() {
    const auto ownership = current_ownership_conflicts();
    std::lock_guard<std::mutex> lock(conflict_mutex_);
    last_blocking_conflicts_ = ownership.blocking_conflicts;
    last_warnings_ = ownership.warnings;
}

void HardwareController::set_rgb(const RgbColor& color) {
    (void)set_rgb_json(color, "HardwareController::set_rgb");
}

std::string HardwareController::set_rgb_json(const RgbColor& color, const std::string& function_used) {
    return direct_v2_set_json(color, false, function_used);
}

std::string HardwareController::direct_v2_set_json(const RgbColor& color, bool re_prime, const std::string& function_used) {
    std::lock_guard<std::mutex> lock(hardware_mutex_);
    refuse_if_conflicted();
    const ULONGLONG start_ms = GetTickCount64();
    Piix4Smbus smbus;
    const uint8_t bus_status_before = smbus.host_status();
    AuraEne aura(smbus);
    std::vector<std::string> write_steps;

    if (re_prime) {
        aura.write_byte(AuraEne::kDirectModeRegister, 0x01);
        write_steps.push_back("re-prime: select " + hex_word(AuraEne::kDirectModeRegister));
        write_steps.push_back("re-prime: byte write 0x01");
        aura.apply();
        write_steps.push_back("re-prime: select " + hex_word(AuraEne::kApplyRegister));
        write_steps.push_back("re-prime: byte write 0x01");
    }

    aura.write_byte(AuraEne::kDirectModeRegister, 0x01);
    write_steps.push_back("select " + hex_word(AuraEne::kDirectModeRegister));
    write_steps.push_back("byte write 0x01");
    aura.apply();
    write_steps.push_back("select " + hex_word(AuraEne::kApplyRegister));
    write_steps.push_back("byte write 0x01");
    aura.write_block3(AuraEne::kRgbDirectRegister, color.r, color.g, color.b);
    write_steps.push_back("select " + hex_word(AuraEne::kRgbDirectRegister));
    write_steps.push_back("block write len=3 payload RGB");
    aura.apply();
    write_steps.push_back("select " + hex_word(AuraEne::kApplyRegister));
    write_steps.push_back("byte write 0x01");

    const uint8_t bus_status_after = smbus.host_status();
    const ULONGLONG duration_ms = GetTickCount64() - start_ms;
    std::ostringstream out;
    out << "{"
        << "\"ok\":true,"
        << "\"function_used\":" << json_string(function_used) << ","
        << "\"path_used\":\"direct_v2_8101\","
        << "\"register_rgb\":" << json_string(hex_word(AuraEne::kRgbDirectRegister)) << ","
        << "\"payload_order\":\"R G B\","
        << "\"payload_hex\":" << json_string(rgb_payload_hex(color)) << ","
        << "\"direct_mode_register\":" << json_string(hex_word(AuraEne::kDirectModeRegister)) << ","
        << "\"apply_register\":" << json_string(hex_word(AuraEne::kApplyRegister)) << ","
        << "\"bus_status_before\":\"0x" << hex_byte(bus_status_before) << "\","
        << "\"bus_status_after\":\"0x" << hex_byte(bus_status_after) << "\","
        << "\"write_steps\":" << json_array(write_steps) << ","
        << "\"duration_ms\":" << duration_ms << ","
        << "\"bus_write_ok\":true,"
        << "\"visual_verified\":false,"
        << "\"visual_state\":\"unknown\","
        << "\"applied\":false,"
        << "\"re_prime\":" << (re_prime ? "true" : "false")
        << "}";
    return out.str();
}

void HardwareController::off() {
    const RgbColor black = {0x00, 0x00, 0x00};
    set_rgb(black);
}

std::string HardwareController::off_json(const std::string& function_used) {
    const RgbColor black = {0x00, 0x00, 0x00};
    return set_rgb_json(black, function_used);
}

void HardwareController::recover() {
    std::lock_guard<std::mutex> lock(hardware_mutex_);
    Piix4Smbus smbus;
    AuraEne aura(smbus);
    aura.recover();
}

void HardwareController::recover_set(const RgbColor& color) {
    std::lock_guard<std::mutex> lock(hardware_mutex_);
    Piix4Smbus smbus;
    AuraEne aura(smbus);
    aura.recover();
    aura.set_rgb(color.r, color.g, color.b);
}

void HardwareController::scene(const std::string& name, RgbColor& applied_color) {
    const SceneDefinition* definition = find_scene(name);
    if (definition == nullptr) {
        throw std::runtime_error("unknown scene: " + name);
    }
    applied_color = definition->color;
    set_rgb(applied_color);
}

std::string HardwareController::scene_json(const std::string& name, RgbColor& applied_color) {
    const SceneDefinition* definition = find_scene(name);
    if (definition == nullptr) {
        throw std::runtime_error("unknown scene: " + name);
    }
    applied_color = definition->color;
    return set_rgb_json(applied_color, "agent.scene:" + name);
}

std::vector<std::string> HardwareController::current_blocking_conflicts() const {
    std::lock_guard<std::mutex> lock(conflict_mutex_);
    return last_blocking_conflicts_;
}

std::vector<std::string> HardwareController::current_warnings() const {
    std::lock_guard<std::mutex> lock(conflict_mutex_);
    return last_warnings_;
}

void HardwareController::refuse_if_conflicted() {
    const auto ownership = current_ownership_conflicts();
    {
        std::lock_guard<std::mutex> lock(conflict_mutex_);
        last_blocking_conflicts_ = ownership.blocking_conflicts;
        last_warnings_ = ownership.warnings;
    }
    if (!allow_conflicts_ && !ownership.blocking_conflicts.empty()) {
        throw std::runtime_error("controller conflict detected");
    }
}
