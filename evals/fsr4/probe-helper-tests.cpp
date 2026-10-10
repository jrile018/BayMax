#include "probe-helpers.h"
#include <iostream>
#include <stdexcept>
static void require(bool b, const char *m) { if (!b) throw std::runtime_error(m); }
int main() {
    require(probe::is_target_version("AMD FSR Upscaling 4.1.1"), "target provider rejected");
    require(probe::is_target_version("4.1.1"), "bare target rejected");
    require(!probe::is_target_version("AMD FSR 14.1.1"), "prefix version confused");
    require(!probe::is_target_version("AMD FSR 4.1.10"), "patch version confused");
    require(!probe::is_target_version("AMD FSR 4.1.1.2"), "four-component version confused");
    require(!probe::is_target_version("AMD FSR 3.1.5"), "fallback accepted");
    require(probe::json_quote("quote\"\\\n\t") == "\"quote\\\"\\\\\\n\\t\"", "JSON escaping corrupted");
    require(probe::json_quote(std::string(1, '\x01')) == "\"\\u0001\"", "control byte escaped incorrectly");
    require(probe::json_quote(std::string(1, static_cast<char>(0xff))) == "\"\\u00ff\"", "non-ASCII byte did not produce valid JSON");
    require(probe::parse_frames("1") == 1 && probe::parse_frames("8") == 8, "bounds rejected");
    for (const auto *s : {"0", "9", "-1", "2garbage", "", "999999999999999999"}) {
        bool rejected=false; try { (void)probe::parse_frames(s); } catch (const std::exception &) { rejected=true; }
        require(rejected, "invalid frame bound accepted");
    }
    std::cout << "probe CPU helper regressions passed\n";
}
