#ifndef PROBE_HELPERS_H
#define PROBE_HELPERS_H
#include <cstdint>
#include <stdexcept>
#include <string>
namespace probe {
// Match a complete three-component version; never accept a fallback or 4.1.10.
inline bool is_target_version(const std::string &name) {
    const std::string target="4.1.1";
    std::size_t pos=0;
    while ((pos=name.find(target,pos)) != std::string::npos) {
        auto version_char=[](char c) { return (c>='0' && c<='9') || c=='.'; };
        if ((pos==0 || !version_char(name[pos-1])) &&
            (pos+target.size()==name.size() || !version_char(name[pos+target.size()]))) return true;
        pos += target.size();
    }
    return false;
}
// Escape arbitrary SDK byte strings into valid ASCII JSON, including control and
// non-ASCII bytes. Byte escapes are deliberate: no assumed SDK string encoding.
inline std::string json_quote(const std::string &value) {
    static const char hex[]="0123456789abcdef";
    std::string out="\"";
    for (unsigned char c : value) {
        switch (c) {
        case '"': out+="\\\""; break;
        case '\\': out+="\\\\"; break;
        case '\n': out+="\\n"; break;
        case '\r': out+="\\r"; break;
        case '\t': out+="\\t"; break;
        default:
            if (c<32 || c>=127) {
                out+="\\u00"; out+=hex[c>>4]; out+=hex[c&15];
            } else out+=static_cast<char>(c);
        }
    }
    return out+'"';
}
inline unsigned parse_frames(const std::string &s) {
    if (s.size()!=1 || s[0]<'1' || s[0]>'8') throw std::runtime_error("--frames must be 1..8");
    return static_cast<unsigned>(s[0]-'0');
}
inline uint64_t fnv1a(const unsigned char *bytes, std::size_t count, uint64_t hash=UINT64_C(14695981039346656037)) {
    for (std::size_t i=0;i<count;++i) { hash ^= bytes[i]; hash *= UINT64_C(1099511628211); }
    return hash;
}
}
#endif
