#include "piix4_smbus.hpp"

#include <iostream>
#include <sstream>
#include <stdexcept>

namespace {
constexpr uint8_t kPiix4ByteData = 0x08;
constexpr uint8_t kPiix4WordData = 0x0C;
constexpr uint8_t kPiix4BlockData = 0x14;
constexpr uint8_t kStart = 0x40;
constexpr uint8_t kWrite = 0x00;

std::string hex8(uint8_t value) {
    const char* digits = "0123456789ABCDEF";
    std::string out = "0x00";
    out[2] = digits[(value >> 4) & 0x0F];
    out[3] = digits[value & 0x0F];
    return out;
}
}

std::string windows_error_message(DWORD error_code) {
    if (error_code == 0) {
        return "no error";
    }

    LPSTR buffer = nullptr;
    const DWORD size = FormatMessageA(
        FORMAT_MESSAGE_ALLOCATE_BUFFER | FORMAT_MESSAGE_FROM_SYSTEM | FORMAT_MESSAGE_IGNORE_INSERTS,
        nullptr,
        error_code,
        MAKELANGID(LANG_NEUTRAL, SUBLANG_DEFAULT),
        reinterpret_cast<LPSTR>(&buffer),
        0,
        nullptr);

    if (size == 0 || buffer == nullptr) {
        std::ostringstream oss;
        oss << "Windows error " << error_code;
        return oss.str();
    }

    std::string message(buffer, size);
    LocalFree(buffer);
    while (!message.empty() && (message.back() == '\r' || message.back() == '\n')) {
        message.pop_back();
    }
    return message;
}

std::string executable_directory() {
    char path[MAX_PATH] = {};
    const DWORD len = GetModuleFileNameA(nullptr, path, MAX_PATH);
    if (len == 0 || len >= MAX_PATH) {
        return ".";
    }

    std::string full(path, len);
    const size_t pos = full.find_last_of("\\/");
    if (pos == std::string::npos) {
        return ".";
    }
    return full.substr(0, pos);
}

std::string executable_inpout32_path() {
    return executable_directory() + "\\inpout32.dll";
}

bool file_exists(const std::string& path) {
    const DWORD attrs = GetFileAttributesA(path.c_str());
    return attrs != INVALID_FILE_ATTRIBUTES && (attrs & FILE_ATTRIBUTE_DIRECTORY) == 0;
}

Piix4Smbus::Piix4Smbus(uint16_t base, bool allow_busy_override, bool verbose)
    : base_(base), allow_busy_override_(allow_busy_override), verbose_(verbose) {
    library_ = LoadLibraryA("inpout32.dll");
    if (library_ == nullptr) {
        throw std::runtime_error("failed to load inpout32.dll: " + windows_error_message(GetLastError()));
    }

    inp32_ = reinterpret_cast<Inp32Fn>(GetProcAddress(library_, "Inp32"));
    out32_ = reinterpret_cast<Out32Fn>(GetProcAddress(library_, "Out32"));
    if (inp32_ == nullptr || out32_ == nullptr) {
        FreeLibrary(library_);
        library_ = nullptr;
        throw std::runtime_error("inpout32.dll does not export both Inp32 and Out32");
    }
}

Piix4Smbus::~Piix4Smbus() {
    if (library_ != nullptr) {
        FreeLibrary(library_);
    }
}

uint16_t Piix4Smbus::port(uint8_t offset) const {
    return static_cast<uint16_t>(base_ + offset);
}

uint8_t Piix4Smbus::read8(uint8_t offset) const {
    return static_cast<uint8_t>(inp32_(static_cast<short>(port(offset))) & 0xFF);
}

void Piix4Smbus::write8(uint8_t offset, uint8_t value) const {
    out32_(static_cast<short>(port(offset)), static_cast<short>(value));
}

void Piix4Smbus::clear_status() const {
    write8(kOffsetHostStatus, 0xFF);
}

bool Piix4Smbus::wait_not_busy(uint32_t timeout_ms) const {
    uint8_t status = host_status();
    if (verbose_) {
        std::cout << "verbose: status before wait: " << hex8(status) << "\n";
    }

    const DWORD start = GetTickCount();
    do {
        last_wait_status_ = status;
        if ((status & kStatusBusy) == 0) {
            if (verbose_) {
                std::cout << "verbose: status after wait: " << hex8(status) << "\n";
            }
            return true;
        }
        Sleep(1);
        status = host_status();
    } while ((GetTickCount() - start) < timeout_ms);

    last_wait_status_ = host_status();
    if (verbose_) {
        std::cout << "verbose: status after wait: " << hex8(last_wait_status_) << "\n";
    }
    return (last_wait_status_ & kStatusBusy) == 0;
}

uint8_t Piix4Smbus::host_status() const {
    return read8(kOffsetHostStatus);
}

bool Piix4Smbus::host_busy() const {
    return (host_status() & kStatusBusy) != 0;
}

bool Piix4Smbus::verbose() const {
    return verbose_;
}

void Piix4Smbus::log_verbose(const std::string& message) const {
    if (verbose_) {
        std::cout << "verbose: " << message << "\n";
    }
}

void Piix4Smbus::start_transaction(uint8_t protocol) const {
    write8(kOffsetHostControl, protocol);
    write8(kOffsetHostControl, static_cast<uint8_t>(protocol | kStart));
}

void Piix4Smbus::finish_transaction() const {
    if (!wait_not_busy(500)) {
        throw std::runtime_error(busy_timeout_error(500));
    }

    const uint8_t status = host_status();
    if (verbose_) {
        std::cout << "verbose: final status: " << hex8(status) << "\n";
    }
    if ((status & (kStatusFailed | kStatusBusError | kStatusDeviceError)) != 0) {
        throw std::runtime_error(status_error(status));
    }

    clear_status();
}

void Piix4Smbus::ensure_ready_for_write(const char* operation) const {
    log_verbose(std::string("transaction type: ") + operation);
    if (wait_not_busy(500)) {
        return;
    }

    if (!allow_busy_override_) {
        throw std::runtime_error(busy_timeout_error(500));
    }

    log_verbose(std::string("--force continuing despite busy before ") + operation);
}

std::string Piix4Smbus::busy_timeout_error(uint32_t timeout_ms) const {
    std::ostringstream oss;
    oss << "SMBus host stayed busy after " << timeout_ms << "ms, last status=" << hex8(last_wait_status_);
    return oss.str();
}

std::string Piix4Smbus::status_error(uint8_t status) const {
    std::ostringstream oss;
    oss << "SMBus transaction failed; host status " << hex8(status);
    if ((status & kStatusFailed) != 0) {
        oss << " FAILED";
    }
    if ((status & kStatusBusError) != 0) {
        oss << " BUS_ERROR";
    }
    if ((status & kStatusDeviceError) != 0) {
        oss << " DEVICE_ERROR";
    }
    return oss.str();
}

void Piix4Smbus::write_byte_data(uint8_t addr7, uint8_t command, uint8_t data0) const {
    ensure_ready_for_write("BYTE_DATA write");
    clear_status();
    write8(kOffsetHostAddress, static_cast<uint8_t>((addr7 << 1) | kWrite));
    write8(kOffsetHostCommand, command);
    write8(kOffsetHostData0, data0);
    start_transaction(kPiix4ByteData);
    finish_transaction();
}

void Piix4Smbus::write_word_data(uint8_t addr7, uint8_t command, uint8_t data0, uint8_t data1) const {
    ensure_ready_for_write("WORD_DATA write");
    clear_status();
    write8(kOffsetHostAddress, static_cast<uint8_t>((addr7 << 1) | kWrite));
    write8(kOffsetHostCommand, command);
    write8(kOffsetHostData0, data0);
    write8(kOffsetHostData1, data1);
    start_transaction(kPiix4WordData);
    finish_transaction();
}

void Piix4Smbus::write_block3(uint8_t addr7, uint8_t command, const uint8_t payload[3]) const {
    ensure_ready_for_write("BLOCK_DATA write");
    clear_status();
    write8(kOffsetHostAddress, static_cast<uint8_t>((addr7 << 1) | kWrite));
    write8(kOffsetHostCommand, command);
    write8(kOffsetHostData0, 0x03);
    (void)read8(kOffsetHostControl);
    write8(kOffsetBlockData, payload[0]);
    write8(kOffsetBlockData, payload[1]);
    write8(kOffsetBlockData, payload[2]);
    start_transaction(kPiix4BlockData);
    finish_transaction();
}

std::vector<std::pair<uint8_t, uint8_t>> Piix4Smbus::read_safe_register_snapshot() const {
    const uint8_t offsets[] = {
        kOffsetHostStatus,
        kOffsetHostSlaveStatus,
        kOffsetHostControl,
        kOffsetHostCommand,
        kOffsetHostAddress,
        kOffsetHostData0,
        kOffsetHostData1,
        kOffsetSlaveControl,
        kOffsetShadowCommand,
        kOffsetSlaveEvent,
        kOffsetSlaveData,
    };

    std::vector<std::pair<uint8_t, uint8_t>> snapshot;
    for (const uint8_t offset : offsets) {
        snapshot.push_back({offset, read8(offset)});
    }
    return snapshot;
}
