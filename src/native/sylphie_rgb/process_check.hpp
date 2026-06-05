#pragma once

#include <string>
#include <vector>

struct ProcessMatch {
    std::string process_name;
    unsigned long pid = 0;
    std::string matched_rule;
};

struct OwnershipConflicts {
    std::vector<std::string> blocking_conflicts;
    std::vector<std::string> warnings;
};

std::vector<ProcessMatch> find_asus_lighting_processes();
bool process_match_is_blocking(const ProcessMatch& process);
bool process_match_is_warning(const ProcessMatch& process);
std::string process_match_summary(const ProcessMatch& process);
OwnershipConflicts classify_process_matches(const std::vector<ProcessMatch>& processes);
