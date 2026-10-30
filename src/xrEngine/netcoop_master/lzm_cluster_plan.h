// Shared by bootstrap and the native location controller. No Win32/engine state.
#pragma once
#include <algorithm>
#include <map>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>
namespace lzm {
struct DefaultMap { const char* name; int port; const char* start; bool on_demand; };
inline const std::vector<DefaultMap>& default_maps() {
 static const std::vector<DefaultMap> maps={
    {"jupiter", 1301, "yanov_depo_monolith", true},
    {"jupiter_underground", 1343, "lz_jupiter_underground", true},
    {"k00_marsh", 1267, "hidden_base", false},
    {"k01_darkscape", 1303, "lz_k01_darkscape", true},
    {"k02_trucks_cemetery", 1305, "tc_central_tower", true},
    {"l01_escape", 1277, "rookie_village", false},
    {"l02_garbage", 1307, "train_hangar", true},
    {"l03_agroprom", 1309, "research_institute", true},
    {"l03u_agr_underground", 1345, "lz_l03u_agr_underground", true},
    {"l04_darkvalley", 1311, "eastern_factory", true},
    {"l04u_labx18", 1347, "lz_l04u_labx18", true},
    {"l05_bar", 1313, "makeshift_barracks", true},
    {"l06_rostok", 1315, "construction_site", true},
    {"l07_military", 1317, "military_base", true},
    {"l08_yantar", 1319, "sakharovs_bunker", true},
    {"l08u_brainlab", 1349, "lz_l08u_brainlab", true},
    {"l09_deadcity", 1321, "abandoned_school", true},
    {"l10_limansk", 1323, "lz_l10_limansk", true},
    {"l10_radar", 1325, "brain_scorcher", true},
    {"l10_red_forest", 1327, "bridge_red_forest_mon", true},
    {"l10u_bunker", 1351, "lz_l10u_bunker", true},
    {"l11_hospital", 1329, "lz_l11_hospital", true},
    {"l11_pripyat", 1331, "cultural_center", true},
    {"l12_stancia", 1333, "power_station", true},
    {"l12_stancia_2", 1335, "lz_l12_stancia_2", true},
    {"l12u_control_monolith", 1353, "lz_l12u_control_monolith", true},
    {"l12u_sarcofag", 1355, "lz_l12u_sarcofag", true},
    {"l13_generators", 1357, "lz_l13_generators", true},
    {"l13u_warlab", 1359, "lz_l13u_warlab", true},
    {"labx8", 1361, "lz_labx8", true},
    {"pripyat", 1337, "river_port", true},
    {"y04_pole", 1339, "lz_y04_pole", true},
    {"zaton", 1341, "abandoned_sawmill", true},
 }; return maps;
}
using ClusterSections=std::map<std::string,std::map<std::string,std::string>>;
inline std::string plan_trim(const std::string& s) {
 auto a=s.find_first_not_of(" \r\n\t");return a==std::string::npos ? "":s.substr(a,s.find_last_not_of(" \r\n\t")-a+1);
}
inline ClusterSections parse_cluster_sections(std::string text) {
 if(text.compare(0,3,"\xef\xbb\xbf")==0) text.erase(0,3);
 ClusterSections out;std::string section,line;std::istringstream in(text);
 while(std::getline(in,line)) {
  line=plan_trim(line.substr(0,line.find(';'))); if(line.empty()) continue;
  if(line.front()=='[' && line.back()==']') {section=plan_trim(line.substr(1,line.size()-2));continue;}
  auto eq=line.find('=');if(eq!=std::string::npos && !section.empty()) out[section][plan_trim(line.substr(0,eq))]=plan_trim(line.substr(eq+1));
 }return out;
}
inline int plan_port(const std::string& value) {
 auto colon=value.rfind(':');auto p=plan_trim(value.substr(colon==std::string::npos ? 0:colon+1));
 if(p.empty() || p.size()>5 || p.find_first_not_of("0123456789")!=std::string::npos) return 0;
 int n=std::stoi(p);return n>0 && n<65535 ? n:0; // the authority client needs port+1
}
inline std::string complete_cluster_plan(const std::string& text) {
 auto ini=parse_cluster_sections(text);auto& locations=ini["locations"];std::set<int> used;
 std::string default_host="127.0.0.1";
 for(const auto& pair:locations) {
  int port=plan_port(pair.second);if(!port) continue;
  if(used.count(port) || used.count(port+1)) throw std::invalid_argument("cluster UDP port collision at "+pair.first);
  used.insert(port);used.insert(port+1);
  auto colon=pair.second.rfind(':');if(colon!=std::string::npos && default_host=="127.0.0.1") default_host=plan_trim(pair.second.substr(0,colon));
 }
 for(const auto& m:default_maps()) {
  if(!plan_port(locations[m.name])) {
   int port=m.port;while(used.count(port) || used.count(port+1)) {port+=2;if(port>=65535) throw std::invalid_argument("no free cluster UDP pair");}
   locations[m.name]=default_host+":"+std::to_string(port);used.insert(port);used.insert(port+1);
  }
  if(ini["launch"][m.name].empty()) ini["launch"][m.name]=m.start;
  if(!ini["on_demand"].count(m.name)) ini["on_demand"][m.name]=m.on_demand ? "1":"0";
 }
 auto& c=ini["cluster"];if(!c.count("entry_port") || c["entry_port"]=="1267") c["entry_port"]="5446";
 if(!c.count("max_players")) c["max_players"]="512";if(!c.count("per_server")) c["per_server"]="128";
 std::ostringstream out;out<<"; Lost Zone cluster: completed automatically; existing addresses are preserved.\n";
 for(const auto& section:ini) {out<<"["<<section.first<<"]\n";for(const auto& kv:section.second) out<<kv.first<<" = "<<kv.second<<"\n";out<<"\n";}
 return out.str();
}
} // namespace lzm
