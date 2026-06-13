#include "process_check.hpp"

#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#include <tlhelp32.h>

#include <algorithm>
#include <sstream>

namespace {
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

bool is_name_in_list(const std::string& name, const char* const* values, size_t count) {
    const std::string lower = lower_ascii(name);
    for (size_t i = 0; i < count; ++i) {
        if (lower == lower_ascii(values[i])) {
            return true;
        }
    }
    return false;
}
}

std::vector<ProcessMatch> find_asus_lighting_processes() {
    const char* rules[] = {
        "LightingService",
        "ArmouryCrate",
        "ArmouryCrate.Service",
        "ArmouryCrate.UserSessionHelper",
        "ArmourySocketServer",
        "ArmourySwAgent",
        "ArmouryHtmlDebugServer",
        "asus_framework",
        "AsusCertService",
        "AuraWallpaperService",
        "Aura Wallpaper Service",
        "Aura",
        "OpenRGB",
        "OpenAuraSDK",
    };

    std::vector<ProcessMatch> matches;
    const HANDLE snapshot = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
    if (snapshot == INVALID_HANDLE_VALUE) {
        return matches;
    }

    PROCESSENTRY32 entry = {};
    entry.dwSize = sizeof(entry);
    if (!Process32First(snapshot, &entry)) {
        CloseHandle(snapshot);
        return matches;
    }

    do {
        const std::string process_name = entry.szExeFile;
        const std::string process_lower = lower_ascii(strip_exe_suffix(process_name));
        for (const char* rule : rules) {
            const std::string rule_lower = lower_ascii(rule);
            if (process_lower.find(rule_lower) != std::string::npos) {
                ProcessMatch match;
                match.process_name = process_name;
                match.pid = entry.th32ProcessID;
                match.matched_rule = rule;
                matches.push_back(match);
                break;
            }
        }
    } while (Process32Next(snapshot, &entry));

    CloseHandle(snapshot);
    return matches;
}

bool process_match_is_blocking(const ProcessMatch& process) {
    static const char* const blocking[] = {
        "LightingService",
        "Aura",
        "OpenRGB",
        "OpenAuraSDK",
        "AuraWallpaperService",
        "Aura Wallpaper Service",
        "ArmourySocketServer",
        "ArmourySwAgent",
        "ArmouryHtmlDebugServer",
    };
    return is_name_in_list(process.matched_rule, blocking, sizeof(blocking) / sizeof(blocking[0]));
}

bool process_match_is_warning(const ProcessMatch& process) {
    static const char* const warnings[] = {
        "AsusCertService",
        "ArmouryCrate.Service",
        "ArmouryCrate.UserSessionHelper",
        "asus_framework",
    };
    return is_name_in_list(process.matched_rule, warnings, sizeof(warnings) / sizeof(warnings[0]));
}

std::string process_match_summary(const ProcessMatch& process) {
    std::ostringstream item;
    item << process.process_name << " pid=" << process.pid << " rule=" << process.matched_rule;
    return item.str();
}

OwnershipConflicts classify_process_matches(const std::vector<ProcessMatch>& processes) {
    OwnershipConflicts result;
    for (const auto& process : processes) {
        if (process_match_is_blocking(process)) {
            result.blocking_conflicts.push_back(process_match_summary(process));
        } else if (process_match_is_warning(process)) {
            result.warnings.push_back(process_match_summary(process));
        }
    }
    return result;
}
