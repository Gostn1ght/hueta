// Incremental, bounded reader for location journals. Never opens another UI.
#pragma once
#include "lzm_common.h"
#include <winsock2.h>
#include <windows.h>
#include <algorithm>
#include <filesystem>
#include <fstream>
#include <map>

namespace lzm {
class LocationLogs {
    struct Cursor {std::filesystem::path path;uintmax_t offset=0;std::string pending;bool skip=false;};
    std::map<std::string,Cursor> cursors_;
    static std::string utf8(const std::string& line) {
        if(line.empty()) return line;
        if(MultiByteToWideChar(CP_UTF8,MB_ERR_INVALID_CHARS,line.data(),int(line.size()),nullptr,0)) return line;
        const int count=MultiByteToWideChar(1251,0,line.data(),int(line.size()),nullptr,0);
        std::wstring wide(size_t(count),L'\0');
        if(count) MultiByteToWideChar(1251,0,line.data(),int(line.size()),wide.data(),count);
        return narrow(wide);
    }
public:
    // Names are matched longest first: l03_agroprom must not steal the
    // l03u_agr_underground log, and Marsh is the unqualified srv_<user>.
    static std::string map_for(const std::string& filename,const std::vector<std::string>& maps) {
        const auto name=lower(filename);
        if(name.rfind("xray_srv_",0)!=0 || name.size()<5 || name.substr(name.size()-4)!=".log") return "";
        std::string found;
        for(const auto& map:maps) if(name.rfind("xray_srv_"+map+"_",0)==0 && map.size()>found.size()) found=map;
        if(!found.empty()) return found;
        // Never assign a known map-looking, unsupported filename to Marsh.
        const auto suffix=name.substr(9);
        if(suffix.rfind("l0",0)==0 || suffix.rfind("l1",0)==0 || suffix.rfind("k0",0)==0 ||
            suffix.rfind("y04_",0)==0 || suffix.rfind("jupiter",0)==0 || suffix.rfind("zaton",0)==0 ||
            suffix.rfind("pripyat",0)==0 || suffix.rfind("labx8",0)==0) return "";
        return std::find(maps.begin(),maps.end(),"k00_marsh")!=maps.end() ? "k00_marsh":"";
    }
    void poll(const std::filesystem::path& root,const std::vector<std::string>& maps) {
        struct Pick {std::filesystem::path path;std::filesystem::file_time_type stamp;};
        std::map<std::string,Pick> files;
        for(const auto& directory:{root/L"appdata"/L"server"/L"logs",root/L"appdata"/L"logs"}) {
            std::error_code error;
            for(std::filesystem::directory_iterator it(directory,error),end;!error && it!=end;it.increment(error)) {
                if(!it->is_regular_file(error) || it->is_symlink(error)) continue;
                const auto map=map_for(narrow(it->path().filename().wstring()),maps);if(map.empty()) continue;
                const auto stamp=it->last_write_time(error);if(error) continue;
                const auto found=files.find(map);
                if(found==files.end() || stamp>found->second.stamp) files[map]={it->path(),stamp};
            }
        }
        for(const auto& entry:files) {
            const auto& map=entry.first;const auto& path=entry.second.path;auto& cursor=cursors_[map];
            std::error_code error;const auto size=std::filesystem::file_size(path,error);if(error) continue;
            if(cursor.path!=path || size<cursor.offset) {
                cursor.path=path;cursor.offset=size>4096 ? size-4096:0;cursor.pending.clear();cursor.skip=cursor.offset!=0;
                log_line("[location:"+map+"] journal attached: "+narrow(path.filename().wstring()));
            }
            if(size==cursor.offset) continue;
            std::ifstream input(path,std::ios::binary);if(!input) continue;
            input.seekg(std::streamoff(cursor.offset));
            const auto count=size_t((std::min)(size-cursor.offset,uintmax_t(16384)));
            std::string chunk(count,'\0');input.read(chunk.data(),std::streamsize(count));
            chunk.resize(size_t(input.gcount()));cursor.offset+=chunk.size();cursor.pending+=chunk;
            size_t start=0,end=0;
            while((end=cursor.pending.find('\n',start))!=std::string::npos) {
                if(!cursor.skip) {
                    auto line=cursor.pending.substr(start,end-start);if(!line.empty() && line.back()=='\r') line.pop_back();
                    if(!line.empty()) log_line("[location:"+map+"] "+utf8(line));
                }
                cursor.skip=false;start=end+1;
            }
            cursor.pending.erase(0,start);
            if(cursor.pending.size()>8192) {cursor.pending.clear();cursor.skip=true;}
        }
    }
};
}
