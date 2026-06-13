#include "agent_state.hpp"

#include <algorithm>
#include <chrono>
#include <iomanip>
#include <sstream>

#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>

namespace {
uint64_t unix_time_seconds() {
    using namespace std::chrono;
    return static_cast<uint64_t>(duration_cast<seconds>(system_clock::now().time_since_epoch()).count());
}

bool process_is_elevated() {
    HANDLE token = nullptr;
    if (!OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &token)) {
        return false;
    }

    TOKEN_ELEVATION elevation = {};
    DWORD size = 0;
    const BOOL ok = GetTokenInformation(token, TokenElevation, &elevation, sizeof(elevation), &size);
    CloseHandle(token);
    return ok && elevation.TokenIsElevated != 0;
}

int hex_value(char c) {
    if (c >= '0' && c <= '9') {
        return c - '0';
    }
    if (c >= 'a' && c <= 'f') {
        return 10 + (c - 'a');
    }
    if (c >= 'A' && c <= 'F') {
        return 10 + (c - 'A');
    }
    return -1;
}

bool extract_json_string(const std::string& line, const std::string& key, std::string& value) {
    const std::string pattern = "\"" + key + "\"";
    size_t pos = line.find(pattern);
    if (pos == std::string::npos) {
        return false;
    }

    pos = line.find(':', pos + pattern.size());
    if (pos == std::string::npos) {
        return false;
    }
    ++pos;
    while (pos < line.size() && (line[pos] == ' ' || line[pos] == '\t')) {
        ++pos;
    }
    if (pos >= line.size() || line[pos] != '"') {
        return false;
    }
    ++pos;

    std::ostringstream out;
    bool escaped = false;
    for (; pos < line.size(); ++pos) {
        const char c = line[pos];
        if (escaped) {
            switch (c) {
            case '"':
            case '\\':
            case '/':
                out << c;
                break;
            case 'n':
                out << '\n';
                break;
            case 'r':
                out << '\r';
                break;
            case 't':
                out << '\t';
                break;
            default:
                out << c;
                break;
            }
            escaped = false;
            continue;
        }
        if (c == '\\') {
            escaped = true;
            continue;
        }
        if (c == '"') {
            value = out.str();
            return true;
        }
        out << c;
    }
    return false;
}

bool extract_json_bool(const std::string& line, const std::string& key, bool& value) {
    const std::string pattern = "\"" + key + "\"";
    size_t pos = line.find(pattern);
    if (pos == std::string::npos) {
        return false;
    }

    pos = line.find(':', pos + pattern.size());
    if (pos == std::string::npos) {
        return false;
    }
    ++pos;
    while (pos < line.size() && (line[pos] == ' ' || line[pos] == '\t')) {
        ++pos;
    }

    if (line.compare(pos, 4, "true") == 0) {
        value = true;
        return true;
    }
    if (line.compare(pos, 5, "false") == 0) {
        value = false;
        return true;
    }
    return false;
}
}

AgentState::AgentState()
    : start_time_(unix_time_seconds()),
      pid_(GetCurrentProcessId()),
      is_elevated_(process_is_elevated()) {
}

uint64_t AgentState::start_time() const {
    return start_time_;
}

unsigned long AgentState::pid() const {
    return pid_;
}

bool AgentState::is_elevated() const {
    return is_elevated_;
}

void AgentState::begin_command(const std::string& cmd) {
    std::lock_guard<std::mutex> lock(mutex_);
    current_command_ = cmd;
    ++command_count_;
}

void AgentState::finish_command(const std::string& cmd, const std::string& result_json, bool ok) {
    std::lock_guard<std::mutex> lock(mutex_);
    current_command_.clear();
    last_command_ = cmd;
    last_result_json_ = result_json;
    if (!ok) {
        ++failure_count_;
    }
}

void AgentState::set_rgb(const std::string& rgb) {
    std::lock_guard<std::mutex> lock(mutex_);
    last_rgb_ = rgb;
    last_scene_.clear();
}

void AgentState::set_scene(const std::string& scene) {
    std::lock_guard<std::mutex> lock(mutex_);
    last_scene_ = scene;
}

void AgentState::set_ownership(const std::vector<std::string>& blocking_conflicts, const std::vector<std::string>& warnings) {
    std::lock_guard<std::mutex> lock(mutex_);
    blocking_conflicts_ = blocking_conflicts;
    warnings_ = warnings;
    if (!blocking_conflicts_.empty()) {
        current_owner_status_ = "conflict";
    } else if (!warnings_.empty()) {
        current_owner_status_ = "warning";
    } else {
        current_owner_status_ = "clear";
    }
}

void AgentState::mark_recover() {
    std::lock_guard<std::mutex> lock(mutex_);
    last_recover_time_ = unix_time_seconds();
}

std::string AgentState::to_json() const {
    std::lock_guard<std::mutex> lock(mutex_);
    std::ostringstream out;
    out << "{"
        << "\"start_time\":" << start_time_ << ","
        << "\"pid\":" << pid_ << ","
        << "\"is_elevated\":" << (is_elevated_ ? "true" : "false") << ","
        << "\"current_command\":" << json_string_or_null(current_command_) << ","
        << "\"last_command\":" << json_string_or_null(last_command_) << ","
        << "\"last_result\":" << (last_result_json_.empty() ? "null" : last_result_json_) << ","
        << "\"last_rgb\":" << json_string_or_null(last_rgb_) << ","
        << "\"last_scene\":" << json_string_or_null(last_scene_) << ","
        << "\"command_count\":" << command_count_ << ","
        << "\"failure_count\":" << failure_count_ << ","
        << "\"current_owner_status\":" << json_string(current_owner_status_) << ","
        << "\"blocking_conflicts\":" << json_array(blocking_conflicts_) << ","
        << "\"warnings\":" << json_array(warnings_) << ","
        << "\"conflicting_processes\":" << json_array(blocking_conflicts_) << ","
        << "\"last_recover_time\":" << (last_recover_time_ == 0 ? std::string("null") : std::to_string(last_recover_time_))
        << "}";
    return out.str();
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
            const unsigned char ch = static_cast<unsigned char>(c);
            if (ch < 0x20 || ch >= 0x80) {
                out << "\\u" << std::hex << std::setw(4) << std::setfill('0') << static_cast<int>(ch) << std::dec;
            } else {
                out << c;
            }
            break;
        }
    }
    return out.str();
}

std::string json_string(const std::string& value) {
    return "\"" + json_escape(value) + "\"";
}

std::string json_string_or_null(const std::string& value) {
    if (value.empty()) {
        return "null";
    }
    return json_string(value);
}

std::string json_array(const std::vector<std::string>& values) {
    std::ostringstream out;
    out << "[";
    for (size_t i = 0; i < values.size(); ++i) {
        if (i != 0) {
            out << ",";
        }
        out << json_string(values[i]);
    }
    out << "]";
    return out.str();
}

std::string command_response_to_json(const CommandResponse& response) {
    std::ostringstream out;
    out << "{"
        << "\"ok\":" << (response.ok ? "true" : "false") << ","
        << "\"id\":" << json_string_or_null(response.id) << ","
        << "\"cmd\":" << json_string(response.cmd) << ","
        << "\"error\":" << (response.error.empty() ? std::string("null") : json_string(response.error)) << ","
        << "\"duration_ms\":" << response.duration_ms << ","
        << "\"state\":" << (response.state_json.empty() ? "{}" : response.state_json)
        << "}";
    return out.str();
}

bool parse_rgb_hex(const std::string& text, RgbColor& color) {
    std::string rgb = text;
    if (!rgb.empty() && rgb[0] == '#') {
        rgb = rgb.substr(1);
    }
    if (rgb.size() != 6) {
        return false;
    }
    for (char c : rgb) {
        if (hex_value(c) < 0) {
            return false;
        }
    }

    color.r = static_cast<uint8_t>((hex_value(rgb[0]) << 4) | hex_value(rgb[1]));
    color.g = static_cast<uint8_t>((hex_value(rgb[2]) << 4) | hex_value(rgb[3]));
    color.b = static_cast<uint8_t>((hex_value(rgb[4]) << 4) | hex_value(rgb[5]));
    return true;
}

std::string rgb_to_hex(const RgbColor& color) {
    std::ostringstream out;
    out << std::uppercase << std::hex << std::setw(2) << std::setfill('0') << static_cast<int>(color.r)
        << std::setw(2) << static_cast<int>(color.g)
        << std::setw(2) << static_cast<int>(color.b);
    return out.str();
}

std::vector<SceneDefinition> scene_definitions() {
    return {
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
}

const SceneDefinition* find_scene(const std::string& name) {
    static const std::vector<SceneDefinition> scenes = scene_definitions();
    const auto it = std::find_if(scenes.begin(), scenes.end(), [&](const SceneDefinition& scene) {
        return scene.name == name;
    });
    if (it == scenes.end()) {
        return nullptr;
    }
    return &(*it);
}

bool parse_command_request(const std::string& line, CommandRequest& request, std::string& error) {
    if (line.size() > 4096) {
        error = "request too large";
        return false;
    }
    if (!extract_json_string(line, "cmd", request.cmd)) {
        error = "missing cmd";
        return false;
    }
    extract_json_string(line, "id", request.id);
    extract_json_string(line, "rgb", request.rgb);
    extract_json_string(line, "name", request.name);
    extract_json_bool(line, "i_accept_stopping_lighting_services", request.i_accept_stopping_lighting_services);
    extract_json_bool(line, "include_armoury_core", request.include_armoury_core);
    return true;
}
