#pragma once

#include <functional>
#include <string>

using PipeRequestHandler = std::function<std::string(const std::string&)>;

class NamedPipeServer {
public:
    explicit NamedPipeServer(std::string pipe_name);

    void run(const PipeRequestHandler& handler, const std::function<bool()>& should_stop);

private:
    std::string pipe_name_;
};

std::string send_pipe_request(const std::string& pipe_name, const std::string& request_line, unsigned long timeout_ms);
