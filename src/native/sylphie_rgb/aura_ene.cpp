#include "aura_ene.hpp"

#include <iomanip>
#include <sstream>
#include <stdexcept>

namespace {
std::string hex_register(uint16_t reg) {
    std::ostringstream oss;
    oss << "0x" << std::uppercase << std::hex << std::setw(4) << std::setfill('0')
        << static_cast<int>(reg);
    return oss.str();
}
}

AuraEne::AuraEne(Piix4Smbus& smbus) : smbus_(smbus) {
}

void AuraEne::select_register(uint16_t reg) {
    smbus_.log_verbose("selected register: " + hex_register(reg));
    smbus_.write_word_data(
        kDeviceAddress,
        0x00,
        static_cast<uint8_t>((reg >> 8) & 0xFF),
        static_cast<uint8_t>(reg & 0xFF));
}

void AuraEne::write_byte(uint16_t reg, uint8_t value) {
    select_register(reg);
    smbus_.write_byte_data(kDeviceAddress, 0x01, value);
}

void AuraEne::write_block3(uint16_t reg, uint8_t a, uint8_t b, uint8_t c) {
    const uint8_t payload[3] = {a, b, c};
    select_register(reg);
    smbus_.write_block3(kDeviceAddress, 0x03, payload);
}

void AuraEne::apply() {
    write_byte(kApplyRegister, 0x01);
}

void AuraEne::enable_direct() {
    write_byte(kDirectModeRegister, 0x01);
    apply();
}

void AuraEne::disable_direct() {
    write_byte(kDirectModeRegister, 0x00);
    apply();
}

void AuraEne::recover() {
    smbus_.log_verbose("recover: wait for SMBus and clear status");
    if (!smbus_.wait_not_busy(500)) {
        throw std::runtime_error("SMBus host stayed busy after 500ms before recovery");
    }
    smbus_.clear_status();

    smbus_.log_verbose("recover: disable direct mode");
    disable_direct();
    Sleep(50);

    smbus_.log_verbose("recover: enable direct mode");
    enable_direct();
    Sleep(50);

    smbus_.log_verbose("recover: write RGB 000000 to direct register 0x8101");
    write_block3(kRgbDirectRegister, 0x00, 0x00, 0x00);
    apply();
    Sleep(50);

    smbus_.log_verbose("recover: repeat direct mode enable");
    enable_direct();
    Sleep(50);
}

void AuraEne::set_rgb(uint8_t r, uint8_t g, uint8_t b) {
    enable_direct();
    write_block3(kRgbDirectRegister, r, g, b);
    apply();
}

void AuraEne::off() {
    set_rgb(0x00, 0x00, 0x00);
}
