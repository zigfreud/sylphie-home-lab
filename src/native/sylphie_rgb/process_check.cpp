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
