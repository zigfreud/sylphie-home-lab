#pragma once

#include "piix4_smbus.hpp"

#include <cstdint>

class AuraEne {
public:
    static constexpr uint8_t kDeviceAddress = 0x40;
    static constexpr uint16_t kDirectModeRegister = 0x8020;
    static constexpr uint16_t kApplyRegister = 0x80A0;
    static constexpr uint16_t kRgbDirectRegister = 0x8101;

    explicit AuraEne(Piix4Smbus& smbus);

    void select_register(uint16_t reg);
    void write_byte(uint16_t reg, uint8_t value);
    void write_block3(uint16_t reg, uint8_t a, uint8_t b, uint8_t c);
    void apply();
    void enable_direct();
    void set_rgb(uint8_t r, uint8_t g, uint8_t b);
    void off();

private:
    Piix4Smbus& smbus_;
};
