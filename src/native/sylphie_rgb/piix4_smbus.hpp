#pragma once

#include <cstdint>
#include <string>
#include <utility>
#include <vector>

#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>

class Piix4Smbus {
public:
    static constexpr uint16_t kDefaultBase = 0x0B20;

    static constexpr uint8_t kOffsetHostStatus = 0x00;
    static constexpr uint8_t kOffsetHostSlaveStatus = 0x01;
    static constexpr uint8_t kOffsetHostControl = 0x02;
    static constexpr uint8_t kOffsetHostCommand = 0x03;
    static constexpr uint8_t kOffsetHostAddress = 0x04;
    static constexpr uint8_t kOffsetHostData0 = 0x05;
    static constexpr uint8_t kOffsetHostData1 = 0x06;
    static constexpr uint8_t kOffsetBlockData = 0x07;
    static constexpr uint8_t kOffsetSlaveControl = 0x08;
    static constexpr uint8_t kOffsetShadowCommand = 0x09;
    static constexpr uint8_t kOffsetSlaveEvent = 0x0A;
    static constexpr uint8_t kOffsetSlaveData = 0x0C;

    static constexpr uint8_t kStatusBusy = 0x01;
    static constexpr uint8_t kStatusInterrupt = 0x02;
    static constexpr uint8_t kStatusDeviceError = 0x04;
    static constexpr uint8_t kStatusBusError = 0x08;
    static constexpr uint8_t kStatusFailed = 0x10;

    explicit Piix4Smbus(
        uint16_t base = kDefaultBase,
        bool allow_busy_override = false,
        bool verbose = false);
    ~Piix4Smbus();

    Piix4Smbus(const Piix4Smbus&) = delete;
    Piix4Smbus& operator=(const Piix4Smbus&) = delete;

    uint8_t read8(uint8_t offset) const;
    void write8(uint8_t offset, uint8_t value) const;

    void clear_status() const;
    bool wait_not_busy(uint32_t timeout_ms) const;
    uint8_t host_status() const;
    bool host_busy() const;
    bool verbose() const;
    void log_verbose(const std::string& message) const;

    void write_byte_data(uint8_t addr7, uint8_t command, uint8_t data0) const;
    void write_word_data(uint8_t addr7, uint8_t command, uint8_t data0, uint8_t data1) const;
    void write_block3(uint8_t addr7, uint8_t command, const uint8_t payload[3]) const;

    std::vector<std::pair<uint8_t, uint8_t>> read_safe_register_snapshot() const;

private:
    using Inp32Fn = short(__stdcall*)(short port);
    using Out32Fn = void(__stdcall*)(short port, short value);

    uint16_t port(uint8_t offset) const;
    void start_transaction(uint8_t protocol) const;
    void begin_transaction(const char* transaction_type) const;
    void finish_transaction_after_setup(uint8_t protocol) const;
    bool wait_not_busy_capture(uint32_t timeout_ms, uint8_t& before, uint8_t& after) const;
    uint8_t read_final_status_after_wait() const;
    std::string busy_timeout_error(uint32_t timeout_ms) const;
    std::string status_error(uint8_t status) const;

    uint16_t base_;
    bool allow_busy_override_ = false;
    bool verbose_ = false;
    mutable uint8_t last_wait_status_ = 0;
    HMODULE library_ = nullptr;
    Inp32Fn inp32_ = nullptr;
    Out32Fn out32_ = nullptr;
};

std::string windows_error_message(DWORD error_code);
std::string executable_directory();
std::string executable_inpout32_path();
bool file_exists(const std::string& path);
