#pragma once

#include <cstddef>
#include <cstdint>
#include <string>

struct RgbColor {
    uint8_t r = 0;
    uint8_t g = 0;
    uint8_t b = 0;
};

inline int hex_digit_value(char ch) {
    if (ch >= '0' && ch <= '9') {
        return ch - '0';
    }
    if (ch >= 'a' && ch <= 'f') {
        return 10 + (ch - 'a');
    }
    if (ch >= 'A' && ch <= 'F') {
        return 10 + (ch - 'A');
    }
    return -1;
}

inline bool parse_rgb_hex(const std::string& text, RgbColor& out) {
    if (text.size() != 6) {
        return false;
    }

    uint8_t bytes[3] = {};
    for (int i = 0; i < 3; ++i) {
        const int hi = hex_digit_value(text[static_cast<size_t>(i * 2)]);
        const int lo = hex_digit_value(text[static_cast<size_t>(i * 2 + 1)]);
        if (hi < 0 || lo < 0) {
            return false;
        }
        bytes[i] = static_cast<uint8_t>((hi << 4) | lo);
    }

    out.r = bytes[0];
    out.g = bytes[1];
    out.b = bytes[2];
    return true;
}
