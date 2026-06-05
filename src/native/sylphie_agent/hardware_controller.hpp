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
    std::string bus_status_json();

    void set_rgb(const RgbColor& color);
    void off();
    void recover();
    void recover_set(const RgbColor& color);
    void scene(const std::string& name, RgbColor& applied_color);

    std::vector<std::string> current_conflicts() const;

private:
    void refuse_if_conflicted();
    std::string conflicts_json(const std::vector<std::string>& conflicts) const;

    bool allow_conflicts_ = false;
    mutable std::mutex hardware_mutex_;
    mutable std::mutex conflict_mutex_;
    std::vector<std::string> last_conflicts_;
};
