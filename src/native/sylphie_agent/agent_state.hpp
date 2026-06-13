#pragma once

#include <cstdint>
#include <mutex>
#include <string>
#include <vector>

struct RgbColor {
    uint8_t r = 0;
    uint8_t g = 0;
    uint8_t b = 0;
};

struct SceneDefinition {
    const char* name;
    RgbColor color;
    const char* description;
};

struct CommandRequest {
    std::string id;
    std::string cmd;
    std::string rgb;
    std::string name;
    std::string variant;
    bool i_accept_stopping_lighting_services = false;
    bool include_armoury_core = false;
};

struct CommandResponse {
    bool ok = false;
    std::string id;
    std::string cmd;
    std::string error;
    uint32_t duration_ms = 0;
    std::string state_json;
    bool shutdown_requested = false;
};

class AgentState {
public:
    AgentState();

    uint64_t start_time() const;
    unsigned long pid() const;
    bool is_elevated() const;

    void begin_command(const std::string& cmd);
    void finish_command(const std::string& cmd, const std::string& result_json, bool ok);
    void set_rgb(const std::string& rgb);
    void set_scene(const std::string& scene);
    void set_ownership(const std::vector<std::string>& blocking_conflicts, const std::vector<std::string>& warnings);
    void mark_recover();

    std::string to_json() const;

private:
    mutable std::mutex mutex_;
    uint64_t start_time_ = 0;
    unsigned long pid_ = 0;
    bool is_elevated_ = false;
    std::string current_command_;
    std::string last_command_;
    std::string last_result_json_;
    std::string last_rgb_;
    std::string last_scene_;
    uint64_t command_count_ = 0;
    uint64_t failure_count_ = 0;
    std::string current_owner_status_ = "unknown";
    std::vector<std::string> blocking_conflicts_;
    std::vector<std::string> warnings_;
    uint64_t last_recover_time_ = 0;
};

std::string json_escape(const std::string& value);
std::string json_string(const std::string& value);
std::string json_string_or_null(const std::string& value);
std::string json_array(const std::vector<std::string>& values);
std::string command_response_to_json(const CommandResponse& response);
bool parse_rgb_hex(const std::string& text, RgbColor& color);
std::string rgb_to_hex(const RgbColor& color);
const SceneDefinition* find_scene(const std::string& name);
std::vector<SceneDefinition> scene_definitions();
bool parse_command_request(const std::string& line, CommandRequest& request, std::string& error);
