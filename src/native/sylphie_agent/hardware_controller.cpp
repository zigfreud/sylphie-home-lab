#include "hardware_controller.hpp"

#include "../sylphie_rgb/aura_ene.hpp"
#include "../sylphie_rgb/piix4_smbus.hpp"
#include "../sylphie_rgb/process_check.hpp"

#include <sstream>
#include <stdexcept>

namespace {
std::string hex_byte(uint8_t value) {
    const char* digits = "0123456789ABCDEF";
    std::string out;
    out.push_back(digits[(value >> 4) & 0x0F]);
    out.push_back(digits[value & 0x0F]);
    return out;
}

std::vector<std::string> process_conflict_names() {
    std::vector<std::string> conflicts;
    const auto processes = find_asus_lighting_processes();
    for (const auto& process : processes) {
        std::ostringstream item;
        item << process.process_name << " pid=" << process.pid << " rule=" << process.matched_rule;
        conflicts.push_back(item.str());
    }
    return conflicts;
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
        const auto conflicts = process_conflict_names();
        {
            std::lock_guard<std::mutex> lock(conflict_mutex_);
            last_conflicts_ = conflicts;
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
        out << "},\"conflicting_processes\":" << json_array(conflicts);
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

    const auto conflicts = process_conflict_names();
    {
        std::lock_guard<std::mutex> lock(conflict_mutex_);
        last_conflicts_ = conflicts;
    }

    std::ostringstream out;
    out << "{"
        << "\"ok\":" << ((!busy_persistent && conflicts.empty()) ? "true" : "false") << ","
        << "\"status\":" << json_string(status_text) << ","
        << "\"busy_persistent\":" << (busy_persistent ? "true" : "false") << ","
        << "\"conflicting_processes\":" << json_array(conflicts)
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

void HardwareController::set_rgb(const RgbColor& color) {
    std::lock_guard<std::mutex> lock(hardware_mutex_);
    refuse_if_conflicted();
    Piix4Smbus smbus;
    AuraEne aura(smbus);
    aura.set_rgb(color.r, color.g, color.b);
}

void HardwareController::off() {
    const RgbColor black = {0x00, 0x00, 0x00};
    set_rgb(black);
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

std::vector<std::string> HardwareController::current_conflicts() const {
    std::lock_guard<std::mutex> lock(conflict_mutex_);
    return last_conflicts_;
}

void HardwareController::refuse_if_conflicted() {
    const auto conflicts = process_conflict_names();
    {
        std::lock_guard<std::mutex> lock(conflict_mutex_);
        last_conflicts_ = conflicts;
    }
    if (!allow_conflicts_ && !conflicts.empty()) {
        throw std::runtime_error("controller conflict detected");
    }
}
