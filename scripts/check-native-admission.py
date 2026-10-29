"""CI-only: the actual native admission coordinator against the real durable master (doc 135).

Two location coordinators (Cordon, Garbage) take their leases; a player is
registered, saves, leaves, resumes with the master's newer image over a stale
local file, goes through a passage with the master's handoff token and leaves
the target. The database is checked afterwards: one character, at Garbage,
DISCONNECTED, newest checkpoint = the last capture.
"""
from pathlib import Path
import base64
import json
import os
import subprocess
import sys
import threading
from tempfile import TemporaryDirectory

if os.environ.get("GITHUB_ACTIONS") != "true":
    raise SystemExit("Native checks must run in GitHub Actions")
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "backend"))
from lostzone import Store, World
from lostzone.http import Credentials, Dispatcher, Server
from lostzone.__main__ import create_config, create_writer_config
from lostzone.native_save import identity
sys.path.insert(0, str(root / "backend/tests"))
from test_native_save import native_fixture

source = r'''
#define NOMINMAX
#include <windows.h>
#include "netcoop_admission.h"
#include <cassert>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <iterator>
#include <string>
#include <vector>
using namespace netcoop_world;

static std::string file(const char* path)
{
    std::ifstream in(path,std::ios::binary);
    return std::string(std::istreambuf_iterator<char>(in),std::istreambuf_iterator<char>());
}
static void ready(AdmissionCoordinator& c)
{
    for(int i=0;i<600;++i){auto s=c.status();if(s.ready) return;if(s.failed) break;Sleep(100);}
    std::puts("coordinator not ready");std::exit(2);
}
static AdmissionResult admit(AdmissionCoordinator& c,const std::string& local,const char* token,std::vector<unsigned char>& bytes)
{
    const auto ticket=c.admit("Alice",1,local.empty()?nullptr:local.data(),local.size(),token);
    assert(ticket);
    AdmissionResult result;
    for(int i=0;i<600;++i){if(c.poll_admission(ticket,result,bytes)) return result;Sleep(50);}
    std::puts("admission timed out");std::exit(3);
}
static void settle(AdmissionCoordinator& c)
{
    // A later admission is queued behind the earlier jobs: wait for the queue.
    for(int i=0;i<600 && c.status().pending;++i) Sleep(50);
}
int main(int argc,char** argv)
{
    assert(argc==7);
    const std::string first=file(argv[3]),second=file(argv[4]),third=file(argv[5]),stale=file(argv[6]);
    wchar_t here[1024]{};GetCurrentDirectoryW(1024,here);
    const std::wstring spool_cordon=std::wstring(here)+L"\\spool_cordon",spool_garbage=std::wstring(here)+L"\\spool_garbage";
    AdmissionCoordinator cordon,garbage;
    assert(cordon.start(argv[1],"cordon",spool_cordon.c_str()));
    assert(garbage.start(argv[2],"garbage",spool_garbage.c_str()));
    ready(cordon);ready(garbage);
    assert(!cordon.capture("Alice",1,first.data(),first.size())); // not admitted yet
    std::vector<unsigned char> bytes;
    // 1. A character the master does not know yet.
    auto result=admit(cordon,first,nullptr,bytes);
    assert(result.state==AdmissionState::Admitted && !result.master_bytes && !result.revision && bytes.empty());
    assert(cordon.admitted("alice",1));
    assert(cordon.capture("Alice",1,first.data(),first.size()));
    assert(cordon.capture("alice",1,second.data(),second.size()));
    // 2. Leave: the session closes after the newest capture is durable.
    assert(cordon.leave("alice",1));
    settle(cordon);
    // 3. Resume with a stale local file: the master's newest image comes back.
    result=admit(cordon,stale,nullptr,bytes);
    assert(result.state==AdmissionState::Admitted && result.master_bytes && result.revision==2);
    assert(std::string(bytes.begin(),bytes.end())==second);
    // Even a matching disk backup does not prove the engine cache is current.
    assert(cordon.leave("alice",1));settle(cordon);
    result=admit(cordon,second,nullptr,bytes);
    assert(result.state==AdmissionState::Admitted && result.master_bytes && std::string(bytes.begin(),bytes.end())==second);
    // 4. A login of an admitted (ACTIVE) slot at another location learns
    // where the character lives (the server sends the player there).
    result=admit(garbage,second,nullptr,bytes);
    assert(result.state==AdmissionState::Elsewhere && std::string(result.home)=="cordon" && bytes.empty());
    // 5. Passage: the newest capture, the handoff token, the target claims it.
    assert(cordon.capture("alice",1,third.data(),third.size()));
    const auto ticket=cordon.depart("alice",1,"garbage");
    assert(ticket);
    DepartureResult departure;
    for(int i=0;i<600 && !cordon.poll_departure(ticket,departure);++i) Sleep(50);
    assert(departure.state==DepartureState::Ready && departure.token[0]);
    assert(!cordon.admitted("alice",1));
    result=admit(garbage,stale,departure.token,bytes);
    assert(result.state==AdmissionState::Admitted && result.master_bytes && result.revision==3);
    assert(std::string(bytes.begin(),bytes.end())==third);
    // The source can no longer admit it: the character is on Garbage now.
    result=admit(cordon,third,nullptr,bytes);
    assert(result.state==AdmissionState::Elsewhere && std::string(result.home)=="garbage");
    assert(garbage.leave("alice",1));settle(garbage);
    // Disconnected on Garbage, a login at Cordon is still sent to Garbage.
    result=admit(cordon,third,nullptr,bytes);
    assert(result.state==AdmissionState::Elsewhere && std::string(result.home)=="garbage");
    // An old passage token at a later login (owner 2026-10-17, refused after
    // every reconnect): the login goes on; a token the master refuses for good
    // is reported stale so the server deletes it.
    result=admit(garbage,third,departure.token,bytes);
    assert(result.state==AdmissionState::Admitted);
    assert(garbage.leave("alice",1));settle(garbage);
    result=admit(garbage,third,"not-a-token",bytes);
    std::fprintf(stderr,"malformed token: state %u stale %d reason '%s'\n",unsigned(result.state),int(result.stale_token),result.reason);std::fflush(stderr);
    assert(result.state==AdmissionState::Admitted && result.stale_token);
    assert(garbage.leave("alice",1));settle(garbage);
    cordon.stop();garbage.stop();
    std::puts("PASS native admission coordinator: create, durable captures, leave, resume with the master's newer image, the home location answered elsewhere (active and disconnected), stale passage tokens dropped, master handoff to another location");
    return 0;
}
'''

with TemporaryDirectory(prefix="native-admission-") as tmp:
    folder = Path(tmp)
    cpp = folder / "admission.cpp"
    exe = folder / "admission.exe"
    cpp.write_text(source, encoding="utf-8")
    include = str(root / "src/xrGame")
    command = ["cl", "/nologo", "/std:c++17", "/EHsc", "/W4", "/WX", "/O2", "/UNDEBUG", "/I" + include, str(cpp),
               str(root / "src/xrGame/netcoop_admission.cpp"), str(root / "src/xrGame/netcoop_checkpoint_worker.cpp"),
               "/Fe:" + str(exe), "/link", "winhttp.lib", "bcrypt.lib"]
    subprocess.run(command, cwd=tmp, check=True)
    store = Store(folder / "world.db")
    world = World(store, world_id=71, seed=0)
    credentials = {"location:cordon": {"role": "location", "locations": ["cordon"], "token": "s" * 48},
                   "location:garbage": {"role": "location", "locations": ["garbage"], "token": "d" * 48},
                   "admin": {"role": "admin", "token": "a" * 48}}
    server = Server(("127.0.0.1", 0), Dispatcher(world, b"k" * 32), Credentials(credentials))
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        config = folder / "private.json"
        create_config(config, ["cordon", "garbage"], world_id=71, seed=0)
        data = json.loads(config.read_bytes())
        data["credentials"] = credentials
        data["port"] = server.server_address[1]
        config.write_text(json.dumps(data))
        paths = []
        for location in ("cordon", "garbage"):
            dest = folder / ("netcoop_world_writer_" + location + ".json")
            create_writer_config(config, dest, location)
            paths.append(str(dest))
        images = []
        for name, progress in (("first", b"first save"), ("second", b"second save" * 2000),
                               ("third", b"third save after the passage"), ("stale", b"an old local file")):
            path = folder / (name + ".nch")
            path.write_bytes(native_fixture(9, progress=progress))
            images.append(str(path))
        subprocess.run([str(exe), *paths, *images], cwd=tmp, check=True)
        character = identity(71, 0, "alice", 1)
        db = store.db
        assert db.execute("SELECT COUNT(*) FROM entity WHERE kind='CHARACTER'").fetchone()[0] == 1
        assert db.execute("SELECT location FROM entity WHERE id=?", (character,)).fetchone()[0] == "garbage"
        assert db.execute("SELECT state FROM player_session WHERE character_id=?", (character,)).fetchone()[0] == "DISCONNECTED"
        assert db.execute("SELECT COUNT(*) FROM native_player_upload").fetchone()[0] == 0
        newest = db.execute("SELECT payload_base64 FROM native_player_save WHERE character_id=? ORDER BY revision DESC LIMIT 1",
                            (character,)).fetchone()[0]
        assert base64.b64decode(newest) == Path(images[2]).read_bytes()
        assert db.execute("SELECT COUNT(*) FROM world_event WHERE type='TransferCommitted'").fetchone()[0] == 1
        print("PASS master state after native admission: one character at the target, disconnected, newest image durable")
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
        store.close()
