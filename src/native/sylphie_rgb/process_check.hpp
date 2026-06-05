#pragma once

#include <string>
#include <vector>

struct ProcessMatch {
    std::string process_name;
    unsigned long pid = 0;
    std::string matched_rule;
};

std::vector<ProcessMatch> find_asus_lighting_processes();
