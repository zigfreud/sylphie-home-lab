#include "agent_state.hpp"
#include "hardware_controller.hpp"
#include "named_pipe_server.hpp"

#include <atomic>
#include <chrono>
#include <fstream>
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

namespace {
constexpr const char* kDefaultPipe = R"(\\.\pipe\sylphie-hw)";

uint32_t elapsed_ms(std::chrono::steady_clock::time_point start) {
    return static_cast<uint32_t>(
        std::chrono::duration_cast<std::chrono::milliseconds>(
            std::chrono::steady_clock::now() - start)
            .count());
}

void ensure_logs_dir() {
    CreateDirectoryA("logs", nullptr);
}

std::string timestamp() {
    SYSTEMTIME time = {};
    GetLocalTime(&time);
    char buffer[64] = {};
    sprintf_s(
        buffer,
        "%04u-%02u-%02u %02u:%02u:%02u",
        time.wYear,
        time.wMonth,
        time.wDay,
        time.wHour,
        time.wMinute,
        time.wSecond);
    return buffer;
}

void log_line(const std::string& message) {
    ensure_logs_dir();
    std::ofstream log("logs/agent.log", std::ios::app);
    log << timestamp() << " " << message << "\n";
}

std::string make_request_json(const std::string& id, const std::string& cmd, const std::string& key = "", const std::string& value = "") {
    std::ostringstream out;
    out << "{\"id\":" << json_string(id) << ",\"cmd\":" << json_string(cmd);
    if (!key.empty()) {
        out << "," << json_string(key) << ":" << json_string(value);
    }
    out << "}";
    return out.str();
}

void print_help() {
    std::cout
        << "sylphie_agent.exe - persistent Sylphie hardware owner\n\n"
        << "Server:\n"
        << "  sylphie_agent.exe --pipe \\\\.\\pipe\\sylphie-hw [--allow-conflicts]\n\n"
        << "Client:\n"
        << "  sylphie_agent.exe --client ping\n"
        << "  sylphie_agent.exe --client status\n"
        << "  sylphie_agent.exe --client bus-status\n"
        << "  sylphie_agent.exe --client takeover-check\n"
        << "  sylphie_agent.exe --client service-status\n"
        << "  sylphie_agent.exe --client takeover-dry-run\n"
        << "  sylphie_agent.exe --client takeover-execute --i-accept-stopping-lighting-services\n"
        << "  sylphie_agent.exe --client restore-services\n"
        << "  sylphie_agent.exe --client set FF0000\n"
        << "  sylphie_agent.exe --client scene movie\n"
        << "  sylphie_agent.exe --client off\n"
        << "  sylphie_agent.exe --client recover\n"
        << "  sylphie_agent.exe --client recover-set FF0000\n";
}

std::string next_client_id() {
    static unsigned long counter = 0;
    std::ostringstream out;
    out << "client-" << GetCurrentProcessId() << "-" << ++counter;
    return out.str();
}

std::string build_client_request(const std::vector<std::string>& args) {
    if (args.empty()) {
        throw std::runtime_error("missing client command");
    }

    const std::string id = next_client_id();
    const std::string& command = args[0];
    if (command == "ping" || command == "status" || command == "doctor" || command == "off" || command == "recover" || command == "shutdown") {
        return make_request_json(id, command);
    }
    if (command == "bus-status") {
        return make_request_json(id, "bus_status");
    }
    if (command == "takeover-check") {
        return make_request_json(id, "takeover_check");
    }
    if (command == "service-status") {
        return make_request_json(id, "service_status");
    }
    if (command == "takeover-dry-run") {
        bool include_core = false;
        for (size_t i = 1; i < args.size(); ++i) {
            if (args[i] == "--include-armoury-core") {
                include_core = true;
            } else {
                throw std::runtime_error("invalid takeover-dry-run flag: " + args[i]);
            }
        }
        std::ostringstream out;
        out << "{\"id\":" << json_string(id)
            << ",\"cmd\":\"takeover_dry_run\""
            << ",\"include_armoury_core\":" << (include_core ? "true" : "false")
            << "}";
        return out.str();
    }
    if (command == "takeover-execute") {
        bool accepted = false;
        bool include_core = false;
        for (size_t i = 1; i < args.size(); ++i) {
            if (args[i] == "--i-accept-stopping-lighting-services") {
                accepted = true;
            } else if (args[i] == "--include-armoury-core") {
                include_core = true;
            } else {
                throw std::runtime_error("invalid takeover-execute flag: " + args[i]);
            }
        }
        std::ostringstream out;
        out << "{\"id\":" << json_string(id)
            << ",\"cmd\":\"takeover_execute\""
            << ",\"i_accept_stopping_lighting_services\":" << (accepted ? "true" : "false")
            << ",\"include_armoury_core\":" << (include_core ? "true" : "false")
            << "}";
        return out.str();
    }
    if (command == "restore-services") {
        return make_request_json(id, "restore_services");
    }
    if (command == "set" && args.size() == 2) {
        return make_request_json(id, "set", "rgb", args[1]);
    }
    if (command == "scene" && args.size() == 2) {
        return make_request_json(id, "scene", "name", args[1]);
    }
    if (command == "recover-set" && args.size() == 2) {
        return make_request_json(id, "recover_set", "rgb", args[1]);
    }

    throw std::runtime_error("invalid client command or arguments");
}

class AgentApp {
public:
    AgentApp(bool allow_conflicts)
        : hardware_(allow_conflicts) {
    }

    bool should_stop() const {
        return stop_requested_.load();
    }

    std::string handle_line(const std::string& line) {
        CommandRequest request;
        std::string parse_error;
        if (!parse_command_request(line, request, parse_error)) {
            CommandResponse response;
            response.ok = false;
            response.error = parse_error;
            response.cmd = "parse";
            response.state_json = state_.to_json();
            return command_response_to_json(response);
        }

        const auto start = std::chrono::steady_clock::now();
        state_.begin_command(request.cmd);
        log_line("command id=" + request.id + " cmd=" + request.cmd);

        CommandResponse response;
        response.id = request.id;
        response.cmd = request.cmd;

        std::string result_json = "{}";
        try {
            result_json = execute(request, response);
            response.ok = true;
        } catch (const std::exception& ex) {
            response.ok = false;
            response.error = ex.what();
            result_json = "{\"error\":" + json_string(response.error) + "}";
        }

        response.duration_ms = elapsed_ms(start);
        state_.set_ownership(hardware_.current_blocking_conflicts(), hardware_.current_warnings());
        state_.finish_command(request.cmd, result_json, response.ok);
        response.state_json = state_.to_json();
        log_line(
            std::string(response.ok ? "success" : "failure") +
            " id=" + request.id +
            " cmd=" + request.cmd +
            " duration_ms=" + std::to_string(response.duration_ms) +
            (response.error.empty() ? "" : " error=" + response.error));
        return command_response_to_json(response);
    }

private:
    std::string execute(const CommandRequest& request, CommandResponse& response) {
        if (request.cmd == "ping") {
            return "{\"pong\":true}";
        }
        if (request.cmd == "status") {
            hardware_.refresh_ownership();
            return "{\"status\":\"ok\"}";
        }
        if (request.cmd == "doctor") {
            return hardware_.doctor_json();
        }
        if (request.cmd == "takeover_check") {
            const std::string result = hardware_.takeover_check_json();
            return result;
        }
        if (request.cmd == "service_status") {
            return hardware_.service_status_json();
        }
        if (request.cmd == "takeover_dry_run") {
            return hardware_.takeover_dry_run_json(request.include_armoury_core);
        }
        if (request.cmd == "takeover_execute") {
            const std::string result = hardware_.takeover_execute_json(
                request.i_accept_stopping_lighting_services,
                request.include_armoury_core);
            state_.mark_recover();
            return result;
        }
        if (request.cmd == "restore_services") {
            return hardware_.restore_services_json();
        }
        if (request.cmd == "bus_status") {
            return hardware_.bus_status_json();
        }
        if (request.cmd == "set") {
            RgbColor color;
            if (!parse_rgb_hex(request.rgb, color)) {
                throw std::runtime_error("rgb must be exactly 6 hex characters");
            }
            hardware_.set_rgb(color);
            state_.set_rgb(rgb_to_hex(color));
            return "{\"applied_rgb\":" + json_string(rgb_to_hex(color)) + "}";
        }
        if (request.cmd == "off") {
            hardware_.off();
            state_.set_rgb("000000");
            state_.set_scene("off");
            return "{\"applied_rgb\":\"000000\"}";
        }
        if (request.cmd == "recover") {
            hardware_.recover();
            state_.mark_recover();
            return "{\"recovered\":true}";
        }
        if (request.cmd == "recover_set") {
            RgbColor color;
            if (!parse_rgb_hex(request.rgb, color)) {
                throw std::runtime_error("rgb must be exactly 6 hex characters");
            }
            hardware_.recover_set(color);
            state_.mark_recover();
            state_.set_rgb(rgb_to_hex(color));
            return "{\"recovered\":true,\"applied_rgb\":" + json_string(rgb_to_hex(color)) + "}";
        }
        if (request.cmd == "scene") {
            RgbColor color;
            hardware_.scene(request.name, color);
            state_.set_rgb(rgb_to_hex(color));
            state_.set_scene(request.name);
            return "{\"scene\":" + json_string(request.name) + ",\"applied_rgb\":" + json_string(rgb_to_hex(color)) + "}";
        }
        if (request.cmd == "shutdown") {
            stop_requested_.store(true);
            response.shutdown_requested = true;
            return "{\"shutdown\":true}";
        }

        throw std::runtime_error("unsupported command: " + request.cmd);
    }

    AgentState state_;
    HardwareController hardware_;
    std::atomic<bool> stop_requested_{false};
};
}

int main(int argc, char** argv) {
    std::string pipe_name = kDefaultPipe;
    bool allow_conflicts = false;
    bool client_mode = false;
    std::vector<std::string> client_args;

    for (int i = 1; i < argc; ++i) {
        const std::string arg = argv[i];
        if (arg == "--help" || arg == "-h") {
            print_help();
            return 0;
        }
        if (arg == "--pipe" && i + 1 < argc) {
            pipe_name = argv[++i];
            continue;
        }
        if (arg == "--allow-conflicts") {
            allow_conflicts = true;
            continue;
        }
        if (arg == "--client") {
            client_mode = true;
            while (i + 1 < argc) {
                client_args.push_back(argv[++i]);
            }
            break;
        }
        std::cerr << "error: unknown argument " << arg << "\n";
        return 2;
    }

    try {
        if (client_mode) {
            const std::string request = build_client_request(client_args);
            std::cout << send_pipe_request(pipe_name, request, 5000) << "\n";
            return 0;
        }

        ensure_logs_dir();
        AgentState startup_state;
        log_line("startup pipe=" + pipe_name + " pid=" + std::to_string(startup_state.pid()) +
                 " elevated=" + std::string(startup_state.is_elevated() ? "true" : "false") +
                 " allow_conflicts=" + std::string(allow_conflicts ? "true" : "false"));
        std::cout << "Sylphie agent listening on " << pipe_name << "\n";
        std::cout << "PID: " << startup_state.pid() << "\n";
        std::cout << "Elevated: " << (startup_state.is_elevated() ? "true" : "false") << "\n";

        AgentApp app(allow_conflicts);
        NamedPipeServer server(pipe_name);
        server.run(
            [&](const std::string& line) { return app.handle_line(line); },
            [&]() { return app.should_stop(); });
        log_line("shutdown");
        return 0;
    } catch (const std::exception& ex) {
        log_line(std::string("fatal error: ") + ex.what());
        std::cerr << "error: " << ex.what() << "\n";
        return 1;
    }
}
