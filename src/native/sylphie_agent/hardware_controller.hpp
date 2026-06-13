#pragma once

#include "agent_state.hpp"

#include <mutex>
#include <string>
#include <vector>

class HardwareController {
public:
    explicit HardwareController(bool allow_conflicts);

    std::string doctor_json();
    std::string takeover_check_json();
    std::string service_status_json();
    std::string takeover_dry_run_json(bool include_armoury_core);
    std::string takeover_execute_json(bool accepted_stop, bool include_armoury_core);
    std::string restore_services_json();
    std::string bus_status_json();
    void refresh_ownership();

    void set_rgb(const RgbColor& color);
    std::string set_rgb_json(const RgbColor& color, const std::string& function_used);
    std::string direct_v2_set_json(const RgbColor& color, bool re_prime, const std::string& function_used);
    void off();
    std::string off_json(const std::string& function_used);
    void recover();
    void recover_set(const RgbColor& color);
    void scene(const std::string& name, RgbColor& applied_color);
    std::string scene_json(const std::string& name, RgbColor& applied_color);

    std::vector<std::string> current_blocking_conflicts() const;
    std::vector<std::string> current_warnings() const;

private:
    void refuse_if_conflicted();

    bool allow_conflicts_ = false;
    mutable std::mutex hardware_mutex_;
    mutable std::mutex conflict_mutex_;
    std::vector<std::string> last_blocking_conflicts_;
    std::vector<std::string> last_warnings_;
};
