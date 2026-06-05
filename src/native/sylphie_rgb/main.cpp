#include "aura_ene.hpp"
#include "color.hpp"
#include "piix4_smbus.hpp"
#include "process_check.hpp"

#include <iomanip>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
constexpr int kExitOk = 0;
constexpr int kExitRuntimeError = 1;
constexpr int kExitUsage = 2;

struct Scene {
    const char* name;
    RgbColor color;
    const char* description;
};

const Scene kScenes[] = {
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

const Scene kCalibrationSteps[] = {
    {"red", {0xFF, 0x00, 0x00}, "full red"},
    {"green", {0x00, 0xFF, 0x00}, "full green"},
    {"blue", {0x00, 0x00, 0xFF}, "full blue"},
    {"white", {0xFF, 0xFF, 0xFF}, "full white"},
    {"movie", {0x20, 0x20, 0x60}, "visible dark blue-purple bias light"},
    {"night", {0x30, 0x00, 0x00}, "low red above visibility threshold"},
    {"off", {0x00, 0x00, 0x00}, "direct RGB off"},
};

std::string hex_byte(uint8_t value) {
    std::ostringstream oss;
    oss << std::uppercase << std::hex << std::setw(2) << std::setfill('0') << static_cast<int>(value);
    return oss.str();
}

std::string hex_word(uint16_t value) {
    std::ostringstream oss;
    oss << "0x" << std::uppercase << std::hex << std::setw(4) << std::setfill('0') << static_cast<int>(value);
    return oss.str();
}

std::string hex_offset(uint8_t value) {
    std::ostringstream oss;
    oss << "+0x" << std::uppercase << std::hex << std::setw(2) << std::setfill('0') << static_cast<int>(value);
    return oss.str();
}

void print_help() {
    std::cout
        << "sylphie_rgb.exe - Sylphie native RGB CLI for ASUS PRIME B450M-GAMING/BR\n\n"
        << "Usage:\n"
        << "  sylphie_rgb.exe set RRGGBB [--dry-run] [--verbose]\n"
        << "  sylphie_rgb.exe off [--dry-run] [--verbose]\n"
        << "  sylphie_rgb.exe scene <name> [--dry-run] [--verbose]\n"
        << "  sylphie_rgb.exe scenes\n"
        << "  sylphie_rgb.exe calibrate --dry-run\n"
        << "  sylphie_rgb.exe doctor\n"
        << "  sylphie_rgb.exe --help\n\n"
        << "Notes:\n"
        << "  set/off/scene use Aura direct RGB register 0x8101 with payload order R G B.\n"
        << "  off writes RGB 000000 through the same direct RGB path.\n"
        << "  scene off uses the same direct RGB path as off.\n"
        << "  inpout32.dll must be next to sylphie_rgb.exe or loadable by Windows.\n";
}

bool take_flag(std::vector<std::string>& args, const std::string& flag) {
    for (auto it = args.begin(); it != args.end(); ++it) {
        if (*it == flag) {
            args.erase(it);
            return true;
        }
    }
    return false;
}

void print_dry_run_sequence(uint8_t r, uint8_t g, uint8_t b) {
    std::cout << "Dry run: no hardware writes will be performed.\n";
    std::cout << "SMBus base: 0x0B20\n";
    std::cout << "Aura/ENE addr7: 0x40\n\n";
    std::cout << "Exact direct sequence:\n";
    std::cout << "  select 0x8020 -> write 0x01\n";
    std::cout << "  select 0x80A0 -> write 0x01\n";
    std::cout << "  select 0x8101 -> block RGB payload "
              << hex_byte(r) << ' ' << hex_byte(g) << ' ' << hex_byte(b) << "\n";
    std::cout << "  select 0x80A0 -> write 0x01\n\n";
    std::cout << "1. WORD_DATA  addr=0x40 CMD=0x00 D0=0x80 D1=0x20 ; select register 0x8020\n";
    std::cout << "2. BYTE_DATA  addr=0x40 CMD=0x01 D0=0x01           ; enable direct mode\n";
    std::cout << "3. WORD_DATA  addr=0x40 CMD=0x00 D0=0x80 D1=0xA0 ; select register 0x80A0\n";
    std::cout << "4. BYTE_DATA  addr=0x40 CMD=0x01 D0=0x01           ; apply\n";
    std::cout << "5. WORD_DATA  addr=0x40 CMD=0x00 D0=0x81 D1=0x01 ; select register 0x8101\n";
    std::cout << "6. BLOCK_DATA addr=0x40 CMD=0x03 LEN=0x03 PAYLOAD="
              << hex_byte(r) << ' ' << hex_byte(g) << ' ' << hex_byte(b)
              << " ; write RGB direct\n";
    std::cout << "7. WORD_DATA  addr=0x40 CMD=0x00 D0=0x80 D1=0xA0 ; select register 0x80A0\n";
    std::cout << "8. BYTE_DATA  addr=0x40 CMD=0x01 D0=0x01           ; apply\n";
}

std::string rgb_hex(const RgbColor& color) {
    return hex_byte(color.r) + hex_byte(color.g) + hex_byte(color.b);
}

const Scene* find_scene(const std::string& name) {
    for (const Scene& scene : kScenes) {
        if (name == scene.name) {
            return &scene;
        }
    }
    return nullptr;
}

void print_scenes(std::ostream& out) {
    out << "Available scenes:\n";
    out << std::left << std::setw(12) << "Name"
        << std::setw(8) << "RGB"
        << "Description\n";
    out << std::string(60, '-') << "\n";
    for (const Scene& scene : kScenes) {
        out << std::left << std::setw(12) << scene.name
            << std::setw(8) << rgb_hex(scene.color)
            << scene.description << "\n";
    }
}

void print_unknown_scene(const std::string& name) {
    std::cerr << "error: unknown scene '" << name << "'\n\n";
    print_scenes(std::cerr);
}

void print_calibration_sequence(std::ostream& out) {
    out << "Manual calibration sequence:\n";
    out << "Run each command manually and verify the visible result before continuing.\n\n";
    for (const Scene& step : kCalibrationSteps) {
        out << std::left << std::setw(8) << step.name
            << rgb_hex(step.color) << "  "
            << "sylphie_rgb.exe set " << rgb_hex(step.color)
            << "  ; " << step.description << "\n";
    }
}

int run_doctor() {
    bool failed = false;

    std::cout << "Sylphie RGB doctor\n";
    std::cout << "Target SMBus base: 0x0B20\n";
    std::cout << "Aura/ENE addr7: 0x40\n\n";

    const std::string dll_path = executable_inpout32_path();
    if (file_exists(dll_path)) {
        std::cout << "[ok] inpout32.dll found next to executable: " << dll_path << "\n";
    } else {
        std::cout << "[warn] inpout32.dll not found next to executable: " << dll_path << "\n";
    }

    try {
        Piix4Smbus smbus;
        std::cout << "[ok] inpout32.dll loaded and exports Inp32/Out32\n\n";

        const auto snapshot = smbus.read_safe_register_snapshot();
        std::cout << "PIIX4 register snapshot (safe offsets only; +0x07 SMBBLKDAT not read):\n";
        for (const auto& item : snapshot) {
            std::cout << "  " << hex_offset(item.first) << " = 0x" << hex_byte(item.second) << "\n";
        }

        const uint8_t status = smbus.host_status();
        if ((status & Piix4Smbus::kStatusBusy) != 0) {
            std::cout << "[warn] SMBus host status bit BUSY is set (status=0x" << hex_byte(status) << ")\n";
        } else {
            std::cout << "[ok] SMBus host status bit BUSY is clear (status=0x" << hex_byte(status) << ")\n";
        }
    } catch (const std::exception& ex) {
        failed = true;
        std::cout << "[fail] " << ex.what() << "\n";
    }

    std::cout << "\nASUS/Aura process check:\n";
    const auto processes = find_asus_lighting_processes();
    if (processes.empty()) {
        std::cout << "[ok] no common ASUS/Aura lighting processes detected\n";
    } else {
        std::cout << "[warn] detected processes that can contend for the SMBus:\n";
        for (const auto& process : processes) {
            std::cout << "  " << process.process_name << " pid=" << process.pid
                      << " rule=" << process.matched_rule << "\n";
        }
    }

    std::cout << "\nDoctor performed reads only and did not write to hardware.\n";
    return failed ? kExitRuntimeError : kExitOk;
}

int write_rgb(uint8_t r, uint8_t g, uint8_t b, bool force, bool verbose) {
    Piix4Smbus smbus(Piix4Smbus::kDefaultBase, force, verbose);
    AuraEne aura(smbus);
    aura.set_rgb(r, g, b);
    std::cout << "ok: wrote RGB " << hex_byte(r) << hex_byte(g) << hex_byte(b)
              << " through Aura direct register " << hex_word(AuraEne::kRgbDirectRegister) << "\n";
    return kExitOk;
}

int run_rgb_command(const RgbColor& color, bool dry_run, bool force, bool verbose) {
    if (dry_run) {
        print_dry_run_sequence(color.r, color.g, color.b);
        return kExitOk;
    }
    return write_rgb(color.r, color.g, color.b, force, verbose);
}

int run_calibrate(bool dry_run, bool accepted_hardware_calibration, bool force, bool verbose) {
    if (force || verbose) {
        std::cerr << "error: calibrate does not accept --force or --verbose\n";
        return kExitUsage;
    }

    if (!dry_run && !accepted_hardware_calibration) {
        std::cerr
            << "error: calibrate refuses to run without --dry-run unless "
            << "--i-accept-hardware-calibration is passed\n\n";
        print_calibration_sequence(std::cerr);
        return kExitUsage;
    }

    if (dry_run) {
        std::cout << "Dry run: calibration will not write hardware.\n\n";
    } else {
        std::cout << "Manual hardware calibration acknowledged. No automatic color cycle will run.\n\n";
    }
    print_calibration_sequence(std::cout);
    return kExitOk;
}
}

int main(int argc, char** argv) {
    try {
        std::vector<std::string> args;
        for (int i = 1; i < argc; ++i) {
            args.emplace_back(argv[i]);
        }

        if (args.empty() || (args.size() == 1 && args[0] == "--help")) {
            print_help();
            return kExitOk;
        }

        const bool dry_run = take_flag(args, "--dry-run");
        const bool force = take_flag(args, "--force");
        const bool verbose = take_flag(args, "--verbose");
        const bool accepted_hardware_calibration = take_flag(args, "--i-accept-hardware-calibration");

        if (args.size() == 1 && args[0] == "doctor") {
            if (dry_run || force || verbose || accepted_hardware_calibration) {
                std::cerr << "error: doctor does not accept flags\n";
                return kExitUsage;
            }
            return run_doctor();
        }

        if (args.size() == 1 && args[0] == "scenes") {
            if (dry_run || force || verbose || accepted_hardware_calibration) {
                std::cerr << "error: scenes does not accept flags\n";
                return kExitUsage;
            }
            print_scenes(std::cout);
            return kExitOk;
        }

        if (args.size() == 1 && args[0] == "calibrate") {
            return run_calibrate(dry_run, accepted_hardware_calibration, force, verbose);
        }

        if (args.size() == 2 && args[0] == "set") {
            if (accepted_hardware_calibration) {
                std::cerr << "error: set does not accept --i-accept-hardware-calibration\n";
                return kExitUsage;
            }
            RgbColor color;
            if (!parse_rgb_hex(args[1], color)) {
                std::cerr << "error: expected color as exactly 6 hexadecimal digits, for example FF0000\n";
                return kExitUsage;
            }

            return run_rgb_command(color, dry_run, force, verbose);
        }

        if (args.size() == 1 && args[0] == "off") {
            if (accepted_hardware_calibration) {
                std::cerr << "error: off does not accept --i-accept-hardware-calibration\n";
                return kExitUsage;
            }
            const RgbColor off = {0x00, 0x00, 0x00};
            return run_rgb_command(off, dry_run, force, verbose);
        }

        if (args.size() == 2 && args[0] == "scene") {
            if (accepted_hardware_calibration) {
                std::cerr << "error: scene does not accept --i-accept-hardware-calibration\n";
                return kExitUsage;
            }
            const Scene* scene = find_scene(args[1]);
            if (scene == nullptr) {
                print_unknown_scene(args[1]);
                return kExitUsage;
            }

            std::cout << "Scene: " << scene->name << " RGB=" << rgb_hex(scene->color)
                      << " - " << scene->description << "\n";
            return run_rgb_command(scene->color, dry_run, force, verbose);
        }

        std::cerr << "error: invalid command or arguments\n\n";
        print_help();
        return kExitUsage;
    } catch (const std::exception& ex) {
        std::cerr << "error: " << ex.what() << "\n";
        return kExitRuntimeError;
    }
}
