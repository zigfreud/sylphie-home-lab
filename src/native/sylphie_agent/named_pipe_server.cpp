#include "named_pipe_server.hpp"

#include <stdexcept>
#include <utility>
#include <vector>

#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>

namespace {
std::string win_error(const char* prefix) {
    const DWORD error = GetLastError();
    char* message = nullptr;
    FormatMessageA(
        FORMAT_MESSAGE_ALLOCATE_BUFFER | FORMAT_MESSAGE_FROM_SYSTEM | FORMAT_MESSAGE_IGNORE_INSERTS,
        nullptr,
        error,
        0,
        reinterpret_cast<LPSTR>(&message),
        0,
        nullptr);

    std::string text = prefix;
    text += " (";
    text += std::to_string(error);
    text += ")";
    if (message != nullptr) {
        text += ": ";
        text += message;
        LocalFree(message);
    }
    return text;
}

void write_all(HANDLE handle, const std::string& text) {
    DWORD written = 0;
    const char* cursor = text.data();
    DWORD remaining = static_cast<DWORD>(text.size());
    while (remaining > 0) {
        if (!WriteFile(handle, cursor, remaining, &written, nullptr)) {
            throw std::runtime_error(win_error("WriteFile failed"));
        }
        cursor += written;
        remaining -= written;
    }
}
}

NamedPipeServer::NamedPipeServer(std::string pipe_name)
    : pipe_name_(std::move(pipe_name)) {
}

void NamedPipeServer::run(const PipeRequestHandler& handler, const std::function<bool()>& should_stop) {
    while (!should_stop()) {
        HANDLE pipe = CreateNamedPipeA(
            pipe_name_.c_str(),
            PIPE_ACCESS_DUPLEX,
            PIPE_TYPE_BYTE | PIPE_READMODE_BYTE | PIPE_WAIT,
            1,
            8192,
            8192,
            0,
            nullptr);
        if (pipe == INVALID_HANDLE_VALUE) {
            throw std::runtime_error(win_error("CreateNamedPipe failed"));
        }

        const BOOL connected = ConnectNamedPipe(pipe, nullptr) ? TRUE : (GetLastError() == ERROR_PIPE_CONNECTED);
        if (!connected) {
            CloseHandle(pipe);
            if (should_stop()) {
                break;
            }
            continue;
        }

        std::string buffer;
        char chunk[512] = {};
        DWORD read = 0;
        while (!should_stop()) {
            if (!ReadFile(pipe, chunk, sizeof(chunk), &read, nullptr) || read == 0) {
                break;
            }
            buffer.append(chunk, chunk + read);

            size_t newline = std::string::npos;
            while ((newline = buffer.find('\n')) != std::string::npos) {
                std::string line = buffer.substr(0, newline);
                if (!line.empty() && line.back() == '\r') {
                    line.pop_back();
                }
                buffer.erase(0, newline + 1);

                const std::string response = handler(line) + "\n";
                write_all(pipe, response);
                FlushFileBuffers(pipe);
                if (should_stop()) {
                    break;
                }
            }
        }

        FlushFileBuffers(pipe);
        DisconnectNamedPipe(pipe);
        CloseHandle(pipe);
    }
}

std::string send_pipe_request(const std::string& pipe_name, const std::string& request_line, unsigned long timeout_ms) {
    if (!WaitNamedPipeA(pipe_name.c_str(), timeout_ms)) {
        throw std::runtime_error(win_error("WaitNamedPipe failed"));
    }

    HANDLE pipe = CreateFileA(
        pipe_name.c_str(),
        GENERIC_READ | GENERIC_WRITE,
        0,
        nullptr,
        OPEN_EXISTING,
        0,
        nullptr);
    if (pipe == INVALID_HANDLE_VALUE) {
        throw std::runtime_error(win_error("CreateFile pipe failed"));
    }

    std::string request = request_line;
    if (request.empty() || request.back() != '\n') {
        request.push_back('\n');
    }
    try {
        write_all(pipe, request);
        FlushFileBuffers(pipe);

        std::string response;
        char c = 0;
        DWORD read = 0;
        while (ReadFile(pipe, &c, 1, &read, nullptr) && read == 1) {
            if (c == '\n') {
                break;
            }
            if (c != '\r') {
                response.push_back(c);
            }
        }
        CloseHandle(pipe);
        return response;
    } catch (...) {
        CloseHandle(pipe);
        throw;
    }
}
