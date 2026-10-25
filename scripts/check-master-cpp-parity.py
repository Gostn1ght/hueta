"""The engine master (C++, src/xrEngine/netcoop_master) against the Python
World Service it replaces: the same configuration, the same requests the
location servers send, the same answers (owner 2026-10-19: the master is part
of the engine). Run on Windows with the CI-built test executable:

    python scripts/check-master-cpp-parity.py <LostZoneMasterTest.exe>

Both services get one configuration (tokens, keys, WorldID), separate DBs and
the director off, so every journal sequence is deterministic. Random IDs,
tokens and clock readings are normalised before comparing; canonical JSON is
compared through the journal's payload hashes.
"""
import base64
import hashlib
import json
from pathlib import Path
import re
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from lostzone.__main__ import create_config  # noqa: E402
from lostzone.native_save import identity, crc32c  # noqa: E402

EXE = None if sys.argv[1] == "--python-both" else Path(sys.argv[1]).resolve()  # --python-both: check the scenario itself
WORLD_ID, SEED = 4242, 1717
INSTANCE_A, INSTANCE_B = "a" * 32, "b" * 32
TIME_KEYS = {"world_ms", "expires_ms", "sequence", "observed_world_ms", "last_cycle_age_ms", "death_time", "applied_world_ms",
             "event_highwater", "due_world_ms", "lease_remaining_ms", "capture_remaining_ms", "events_processed", "revision",
             "state_revision"}
failures = []


def ready_call(client, *args, seconds=20, **kwargs):
    """A restarted master settles the events that fell due first (the relayed
    schedules start now): 503 "recovering" until then."""
    deadline = time.time() + seconds
    while True:
        status, body = client.call(*args, **kwargs)
        if status != 503 or time.time() > deadline:
            return status, body
        time.sleep(0.5)


def wait_port(port, process, seconds=30):
    deadline = time.time() + seconds
    while time.time() < deadline:
        if process.poll() is not None:
            raise SystemExit(f"service on {port} exited with {process.returncode}")
        with socket.socket() as probe:
            if probe.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.2)
    raise SystemExit(f"service on {port} did not listen")


class Client:
    def __init__(self, port, config):
        self.port, self.config = port, config

    def token(self, actor):
        return self.config["credentials"][actor]["token"]

    def call(self, method, path, body=None, actor="admin", instance=None, bound=False, raw=None, headers=None):
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        request = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=data, method=method)
        if actor:
            request.add_header("Authorization", "Bearer " + self.token(actor))
        if data is not None:
            request.add_header("Content-Type", "application/json")
        if instance:
            request.add_header("X-LostZone-Instance", instance)
        if bound:
            request.add_header("X-LostZone-World", f"{WORLD_ID}:{SEED}:{bound}")
        for key, value in (headers or {}).items():
            request.add_header(key, value)
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.read()


class Normaliser:
    def __init__(self):
        self.ids = {}

    def __call__(self, value, key=None):
        if isinstance(value, dict):
            return {k: self(v, k) for k, v in value.items()}
        if isinstance(value, list):
            return [self(v) for v in value]
        if key in TIME_KEYS and isinstance(value, (int, float)) and not isinstance(value, bool):
            return "<time>"
        if key in ("token", "nonce", "signature", "checksum"):
            return "<secret>"
        if isinstance(value, str):
            if re.fullmatch(r"[0-9a-f]{32}", value) and value not in FIXED:
                return self.ids.setdefault(value, f"<id{len(self.ids)}>")
            if key in ("text",):
                value = re.sub(r"[0-9a-f]{32}", "<hex>", value)
                return re.sub(r"\d+(\.\d+)?(e[+-]?\d+)?", "#", value)
            if key == "data" and len(value) > 64:
                return hashlib.sha256(value.encode()).hexdigest()
        return value


FIXED = set()


def native_save(name="Tester"):
    def packet(data):
        return struct.pack("<II", len(data), crc32c(data)) + data
    out = b"NCH9" + name.encode() + b"\0" + b"stalker\0" + b"loadout\0" + b"x\0" + b"y\0"
    out += bytes([3, 0, 1]) + packet(b"actor-state" * 30)
    out += struct.pack("<I", 1) + b"wpn_pm\0" + struct.pack("<HH", 0, 7) + packet(b"item") + struct.pack("<H", 3) + b"abc"
    out += packet(b"progress" * 100)
    out += struct.pack("<I", 1) + b"stash\0" + b"label\0" + struct.pack("<I", 0)
    out += struct.pack("<I", 40)
    return out


def scenario(client):
    """Every step returns (status, normalised body)."""
    norm = Normaliser()
    steps = []

    def step(name, status_body):
        status, body = status_body
        try:
            parsed = json.loads(body) if body else None
        except ValueError:
            parsed = body.decode("latin-1")
        steps.append((name, status, norm(parsed)))
        return status, parsed

    def command(name, operation, arguments, actor, command_id=None, instance=None):
        return step(name, client.call("POST", "/v1/command", {"command_id": command_id or uuid.uuid5(uuid.NAMESPACE_URL, name).hex,
                                                             "operation": operation, "arguments": arguments},
                                      actor=actor, instance=instance))

    marsh, escape = "location:k00_marsh", "location:l01_escape"
    step("unauthenticated", client.call("GET", "/v1/clock", actor=None))
    step("status keys", (200, json.dumps(sorted(json.loads(client.call("GET", "/v1/status")[1])["result"])).encode()))
    step("observer cannot command", client.call("POST", "/v1/command", {"command_id": "1" * 32, "operation": "location_claim",
                                                                        "arguments": {"location": "k00_marsh"}}, actor="observer:engine"))
    step("bad json", client.call("POST", "/v1/command", raw=b"{", actor=marsh))
    step("duplicate key", client.call("POST", "/v1/command", raw=b'{"a":1,"a":2}', actor=marsh))
    step("no content type", client.call("POST", "/v1/command", raw=b"{}", actor=marsh, headers={"Content-Type": "text/plain"}))
    step("unknown endpoint", client.call("GET", "/v1/nothing", actor=marsh))
    step("unknown operation", client.call("POST", "/v1/command", {"command_id": "2" * 32, "operation": "trade", "arguments": {}}, actor=marsh))
    step("foreign map", client.call("POST", "/v1/command", {"command_id": "3" * 32, "operation": "location_claim",
                                                            "arguments": {"location": "l01_escape"}}, actor=marsh))
    step("extra argument", client.call("POST", "/v1/command", {"command_id": "4" * 32, "operation": "location_claim",
                                                               "arguments": {"location": "k00_marsh", "colour": 1}}, actor=marsh))
    _, claim = command("claim marsh", "location_claim", {"location": "k00_marsh", "ttl_ms": 60000}, marsh, instance=INSTANCE_A)
    command("claim marsh replay", "location_claim", {"location": "k00_marsh", "ttl_ms": 60000}, marsh, uuid.uuid5(uuid.NAMESPACE_URL, "claim marsh").hex, INSTANCE_A)
    command("claim marsh reused id", "location_claim", {"location": "k00_marsh", "ttl_ms": 30000}, marsh, uuid.uuid5(uuid.NAMESPACE_URL, "claim marsh").hex, INSTANCE_A)
    command("claim marsh twice", "location_claim", {"location": "k00_marsh"}, marsh, instance=INSTANCE_B)
    _, claim_b = command("claim escape", "location_claim", {"location": "l01_escape", "ttl_ms": 60000}, escape, instance=INSTANCE_B)
    fa, fb = claim["result"]["fence"], claim_b["result"]["fence"]
    command("renew marsh", "location_renew", {"location": "k00_marsh", "fence": fa, "ttl_ms": 60000}, marsh, instance=INSTANCE_A)
    command("renew wrong fence", "location_renew", {"location": "k00_marsh", "fence": fa + 5}, marsh, instance=INSTANCE_A)
    step("clock", client.call("GET", "/v1/clock", actor="observer:engine"))
    for name, times, parameters in (
            ("weather", {"TRANSITION": 7e13, "SETTLED": 7.1e13}, {"source": "clear", "target": "rain", "seed": 5}),
            ("emission", {"WARNING": 7e13, "ACTIVE": 7.0001e13, "PEAK": 7.0002e13, "ENDED": 7.0003e13}, {"intensity": 100, "seed": 2**63 + 7}),
            ("psi_storm", {"WARNING": 8e13, "ACTIVE": 8.0001e13, "PEAK": 8.0002e13, "ENDED": 8.0003e13}, {"intensity": 55.5, "seed": 9})):
        command("timeline " + name, "timeline_schedule", {"name": name, "timeline_id": hashlib.md5(name.encode()).hexdigest(), "version": None,
                                                          "times": times, "parameters": parameters}, "admin")
    command("timeline bad order", "timeline_schedule", {"name": "weather", "timeline_id": "5" * 32, "version": None,
                                                        "times": {"TRANSITION": 9e13, "SETTLED": 8e13}, "parameters": {"source": "a", "target": "b", "seed": 1}}, "admin")
    command("world state floats", "world_state", {"name": "probe", "version": 0, "state": {
        "floats": [1e16, 1.5e-05, 63676137600000.0, 0.1, 1e22, 123456789012345678.0, -0.0, 0.0001, 2.5, 1e-7, 123.456],
        "ints": [0, -1, 2**63 - 1, 2**64 - 1], "text": "кириллица \u0001 \"q\" \\ \t\n/ é 😀", "nested": {"b": [True, False, None], "a": {}}}}, "admin")
    command("world scale", "world_scale", {"value": 10}, "admin")
    step("engine bootstrap", client.call("GET", "/v1/engine-bootstrap", actor="observer:engine"))
    step("bootstrap", client.call("GET", "/v1/bootstrap", actor="admin"))

    account = "Tester"
    character = identity(WORLD_ID, SEED, account, 1)
    FIXED.add(character)
    epoch = client.epoch
    step("admission absent", client.call("GET", f"/v1/player-admission?account={account}&slot=1&location=k00_marsh&fence={fa}&epoch={epoch}",
                                         actor=marsh, instance=INSTANCE_A, bound=epoch))
    step("admission no binding", client.call("GET", f"/v1/player-admission?account={account}&slot=1&location=k00_marsh&fence={fa}&epoch={epoch}",
                                             actor=marsh, instance=INSTANCE_A))
    step("admission bad query", client.call("GET", f"/v1/player-admission?account={account}&slot=0&location=k00_marsh&fence={fa}&epoch={epoch}",
                                            actor=marsh, instance=INSTANCE_A, bound=epoch))
    step("admission wrong epoch", client.call("GET", f"/v1/player-admission?account={account}&slot=1&location=k00_marsh&fence={fa}&epoch={epoch}",
                                              actor=marsh, instance=INSTANCE_A, bound=epoch + 1))
    _, created = command("create character", "entity_create", {"entity_id": character, "kind": "CHARACTER", "location": "k00_marsh", "fence": fa,
                                                               "state": {"name": "Стрелок", "faction": "stalker", "hp": 0.75}, "account": account},
                         marsh, instance=INSTANCE_A)
    command("create character again", "entity_create", {"entity_id": character, "kind": "CHARACTER", "location": "k00_marsh", "fence": fa,
                                                        "state": {}, "account": account}, marsh, instance=INSTANCE_A)
    npc, group, stash, item, item2 = (hashlib.md5(n.encode()).hexdigest() for n in ("npc", "group", "stash", "item", "item2"))
    FIXED.update((npc, group, stash, item, item2))
    command("create npc", "entity_create", {"entity_id": npc, "kind": "NPC", "location": "k00_marsh", "fence": fa, "state": {"faction": "bandit"}}, marsh, instance=INSTANCE_A)
    command("create group", "entity_create", {"entity_id": group, "kind": "GROUP", "location": "k00_marsh", "fence": fa, "state": {"member_ids": [npc]}}, marsh, instance=INSTANCE_A)
    command("create stash", "entity_create", {"entity_id": stash, "kind": "STASH", "location": "k00_marsh", "fence": fa, "state": {},
                                              "policy": "PLAYER_ONLY", "owner": character, "capacity": 1}, marsh, instance=INSTANCE_A)
    command("create item world", "item_create", {"item_id": item, "section": "wpn_ak74", "location": "k00_marsh", "fence": fa, "state": {"condition": 0.9}}, marsh, instance=INSTANCE_A)
    command("create item npc", "item_create", {"item_id": item2, "section": "ammo_5.45x39", "location": "k00_marsh", "fence": fa,
                                               "kind": "NPC", "holder": npc, "quantity": 30}, marsh, instance=INSTANCE_A)
    command("move to player", "item_move", {"item_id": item, "location": "k00_marsh", "fence": fa, "version": 1, "source_kind": "WORLD",
                                            "source_holder": "k00_marsh", "target_kind": "PLAYER", "target_holder": character, "requester": character},
            marsh, instance=INSTANCE_A)
    command("move to stash", "item_move", {"item_id": item, "location": "k00_marsh", "fence": fa, "version": 2, "source_kind": "PLAYER",
                                           "source_holder": character, "target_kind": "STASH", "target_holder": stash, "requester": character},
            marsh, instance=INSTANCE_A)
    command("move stale version", "item_move", {"item_id": item, "location": "k00_marsh", "fence": fa, "version": 2, "source_kind": "STASH",
                                                "source_holder": stash, "target_kind": "WORLD", "target_holder": "k00_marsh", "requester": character},
            marsh, instance=INSTANCE_A)
    step("location state", client.call("GET", f"/v1/location?id=k00_marsh&fence={fa}", actor=marsh, instance=INSTANCE_A))
    step("admission active", client.call("GET", f"/v1/player-admission?account={account}&slot=1&location=k00_marsh&fence={fa}&epoch={epoch}",
                                         actor=marsh, instance=INSTANCE_A, bound=epoch))
    raw = native_save()
    sha = hashlib.sha256(raw).hexdigest()
    _, begun = command("save begin", "native_save_begin", {"character_id": character, "fence": fa, "session_fence": 1, "entity_version": 1,
                                                           "base_revision": 0, "slot": 1, "byte_count": len(raw), "sha256": sha}, marsh, instance=INSTANCE_A)
    upload = begun["result"]["upload_id"]
    command("save append bad", "native_save_append", {"character_id": character, "fence": fa, "session_fence": 1, "upload_id": upload,
                                                      "offset": 0, "data": "@@@@"}, marsh, instance=INSTANCE_A)
    command("save append", "native_save_append", {"character_id": character, "fence": fa, "session_fence": 1, "upload_id": upload,
                                                  "offset": 0, "data": base64.b64encode(raw).decode()}, marsh, instance=INSTANCE_A)
    command("save finish", "native_save_finish", {"character_id": character, "fence": fa, "session_fence": 1, "upload_id": upload}, marsh, instance=INSTANCE_A)
    command("save finish replay", "native_save_finish", {"character_id": character, "fence": fa, "session_fence": 1, "upload_id": upload},
            marsh, uuid.uuid5(uuid.NAMESPACE_URL, "save finish").hex, INSTANCE_A)
    step("save read", client.call("GET", f"/v1/player-save?character_id={character}&fence={fa}&session_fence=1&revision=1", actor=marsh, instance=INSTANCE_A))
    step("save read bad offset", client.call("GET", f"/v1/player-save?character_id={character}&fence={fa}&session_fence=1&revision=1&offset=5",
                                             actor=marsh, instance=INSTANCE_A))
    command("update character", "entity_update", {"entity_id": character, "fence": fa, "version": 2, "state": {"name": "Стрелок", "hp": 1}}, marsh, instance=INSTANCE_A)
    command("disconnect", "session_disconnect", {"character_id": character, "fence": fa, "version": 3, "state": {"name": "Стрелок", "hp": 1}}, marsh, instance=INSTANCE_A)
    step("admission disconnected", client.call("GET", f"/v1/player-admission?account=tester&slot=1&location=k00_marsh&fence={fa}&epoch={epoch}",
                                               actor=marsh, instance=INSTANCE_A, bound=epoch))
    _, resumed = command("resume", "session_resume", {"character_id": character, "location": "k00_marsh", "fence": fa, "version": 4}, marsh, instance=INSTANCE_A)
    session_fence = resumed["result"]["session_fence"]
    command("prepare group member", "transfer_prepare", {"entity_id": npc, "source": "k00_marsh", "source_fence": fa, "target": "l01_escape",
                                                         "entity_version": 1}, marsh, instance=INSTANCE_A)
    _, prepared = command("prepare", "transfer_prepare", {"entity_id": character, "source": "k00_marsh", "source_fence": fa, "target": "l01_escape",
                                                          "entity_version": 5}, marsh, instance=INSTANCE_A)
    token, transfer = prepared["result"]["token"], prepared["result"]["transfer_id"]
    step("transfer status", client.call("GET", f"/v1/transfer?id={transfer}", actor=marsh, instance=INSTANCE_A))
    command("claim bad token", "transfer_claim", {"token": token[:-2] + "00", "target_fence": fb}, escape, instance=INSTANCE_B)
    command("claim", "transfer_claim", {"token": token, "target_fence": fb}, escape, instance=INSTANCE_B)
    step("save read transfer", client.call("GET", f"/v1/player-save?character_id={character}&fence={fb}&session_fence={session_fence + 1}&revision=1&transfer_id={transfer}",
                                           actor=escape, instance=INSTANCE_B))
    command("commit", "transfer_commit", {"transfer_id": transfer, "target_fence": fb}, escape, instance=INSTANCE_B)
    command("abort committed", "transfer_abort", {"transfer_id": transfer, "source_fence": fa}, marsh, instance=INSTANCE_A)
    step("admission elsewhere", client.call("GET", f"/v1/player-admission?account={account}&slot=1&location=k00_marsh&fence={fa}&epoch={epoch}",
                                            actor=marsh, instance=INSTANCE_A, bound=epoch))
    command("npc dies", "entity_death", {"entity_id": npc, "fence": fa, "version": 1, "cause": "bullet"}, marsh, instance=INSTANCE_A)
    command("npc dies twice", "entity_death", {"entity_id": npc, "fence": fa, "version": 2, "cause": "bullet"}, marsh, instance=INSTANCE_A)
    command("corpse cleanup", "corpse_cleanup", {"entity_id": npc, "fence": fa, "version": 2}, marsh, instance=INSTANCE_A)
    command("recover", "location_recover", {"location": "k00_marsh", "fence": fa}, marsh, instance=INSTANCE_A)
    # In-game administrators' orders relayed by their location (owner 2026-10-23).
    relay = lambda order, values, actor=marsh: {"account": "Admin", "order": order, "values": values}
    command("relay scale", "admin_relay", relay("scale", {"value": 12}), marsh, instance=INSTANCE_A)
    command("relay advance", "admin_relay", relay("advance", {"game_s": 3600}), marsh, instance=INSTANCE_A)
    command("relay advance replay", "admin_relay", relay("advance", {"game_s": 3600}), marsh, uuid.uuid5(uuid.NAMESPACE_URL, "relay advance").hex, INSTANCE_A)
    command("relay advance backwards", "admin_relay", relay("advance", {"game_s": -5}), marsh, instance=INSTANCE_A)
    command("relay unknown order", "admin_relay", relay("teleport", {}), marsh, instance=INSTANCE_A)
    command("relay weather missing", "admin_relay", relay("weather", {"source": "clear", "target": "rain"}), marsh, instance=INSTANCE_A)
    command("relay bad account", "admin_relay", {"account": "", "order": "scale", "values": {"value": 10}}, marsh, instance=INSTANCE_A)
    command("relay by admin", "admin_relay", relay("scale", {"value": 10}), "admin")
    # help differs on purpose: the engine master adds psi and drops quit.
    for line in ("status", "clock", "locations", "players", "characters", "npcs", "transfers", "events", "weather", "emission",
                 "psi_storm", "scale", "nonsense", "status now"):
        step("console " + line, client.call("POST", "/v1/console", {"line": line}))
    step("console quit", client.call("POST", "/v1/console", {"line": "quit"}))
    status, events = client.call("GET", "/v1/events?after=0&limit=512")
    hashes = [(e["type"], e["aggregate_id"] if not re.fullmatch(r"transfer:[0-9a-f]{32}", e["aggregate_id"]) else "transfer",
               e["payload_hash"] if e["type"] not in ("TransferPrepared", "LocationClaimed", "TransferClaimed", "ScheduledEventApplied") else "-")
              for e in json.loads(events)["result"]["events"]]
    steps.append(("journal hashes", status, hashes))
    step("snapshot", client.call("POST", "/v1/snapshot", {}))
    # Relayed schedules start now: their times differ between the two runs,
    # so they come after the journal and the snapshot (results compared).
    command("relay weather", "admin_relay", {"account": "Admin", "order": "weather",
            "values": {"source": "clear", "target": "rain", "transition_s": 30}}, marsh, instance=INSTANCE_A)
    command("relay emission", "admin_relay", {"account": "Admin", "order": "emission",
            "values": {"durations": [10, 20, 30], "intensity": 80}}, marsh, instance=INSTANCE_A)
    command("relay psi bad durations", "admin_relay", {"account": "Admin", "order": "psi_storm",
            "values": {"durations": [10, 20], "intensity": 80}}, marsh, instance=INSTANCE_A)
    return steps


def main():
    work = Path(tempfile.mkdtemp(prefix="lzm_parity_"))
    base = work / "base" / "config.json"
    create_config(base, ["k00_marsh", "l01_escape"], world_id=WORLD_ID, seed=SEED, initial_ms=63676137600000, scale=10)
    config = json.loads(base.read_text(encoding="utf-8"))
    config["director"] = {"enabled": False}
    plan = work / "netcoop_cluster.ltx"
    plan.write_text("[cluster]\nentry_port = 1\n[locations]\nk00_marsh = 127.0.0.1:1267\nl01_escape = 127.0.0.1:1277\n", encoding="cp1251")
    processes, clients = [], []
    for name, port, entry in (("python", 38611, 38711), ("cpp", 38612, 38712)):
        folder = work / name
        folder.mkdir()
        (folder / "config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
        if name == "python" or EXE is None:
            command = [sys.executable, "-m", "lostzone", "serve", "--config", str(folder / "config.json"), "--port", str(port),
                       "--gateway-port", str(entry), "--cluster", str(plan)]
            process = subprocess.Popen(command, cwd=ROOT / "backend", stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            command = [str(EXE), "serve", "--config", str(folder / "config.json"), "--port", str(port), "--gateway-port", str(entry),
                       "--cluster", str(plan), "--root", str(work)]
            process = subprocess.Popen(command, cwd=folder)
        processes.append(process)
        wait_port(port, process)
        wait_port(entry, process)
        client = Client(port, config)
        client.epoch = 1
        client.entry = entry
        clients.append(client)
    try:
        results = [scenario(client) for client in clients]
        for (name, status_a, body_a), (_, status_b, body_b) in zip(*results):
            if (status_a, body_a) != (status_b, body_b):
                failures.append(name)
                print(f"DIFF {name}:\n  python {status_a} {json.dumps(body_a, ensure_ascii=False)[:1500]}\n  cpp    {status_b} {json.dumps(body_b, ensure_ascii=False)[:1500]}")
        # The entry: the first running map; by account and slot the character's
        # map (Tester lives on Cordon after the transfer), Cordon for a newcomer
        # (owner 2026-10-24); a malformed account falls back to the first map.
        for query in ("", "?account=Tester&slot=1", "?account=Newbie&slot=2", "?account=x&slot=1", "?account=Tester&slot=99"):
            answers = []
            for client in clients:
                with urllib.request.urlopen(f"http://127.0.0.1:{client.entry}/v1/entry{query}", timeout=5) as response:
                    answers.append(json.loads(response.read()))
            if answers[0] != answers[1]:
                failures.append("entry " + query)
                print("DIFF entry", query, answers[0], answers[1])
            elif query == "?account=Tester&slot=1" and answers[0]["location"] != "l01_escape":
                failures.append("entry home")
                print("entry home is not the character's map", answers[0])
        # Accounts (doc 154): the C++ master only keeps them (the Python service has none).
        if EXE is not None:
            cpp = clients[1]

            def account_call(operation, arguments, actor="location:k00_marsh"):
                status, body = cpp.call("POST", "/v1/command", {"command_id": uuid.uuid4().hex, "operation": operation, "arguments": arguments},
                                        actor=actor, instance=(INSTANCE_B if actor.endswith("escape") else INSTANCE_A) if actor.startswith("location:") else None,
                                        bound=cpp.epoch if actor.startswith("location:") else False)
                return status, json.loads(body) if body else None
            tester = {"login": "Tester", "role": "player", "salt": "a" * 32, "hash": "b" * 64, "money": 500,
                      "device": "", "approval": "approved", "firebase_uid": ""}
            google = dict(tester, login="Ghost", hash="firebase", money=None, firebase_uid="u" * 28)
            checks = [
                ("account put", account_call("account_put", {"accounts": [tester, google], "only_new": False}),
                 lambda s, b: s == 200 and b["result"]["changed"] == 2),
                ("account import keeps", account_call("account_put", {"accounts": [dict(tester, money=1)], "only_new": True}),
                 lambda s, b: s == 200 and b["result"]["changed"] == 0),
                ("account update", account_call("account_put", {"accounts": [dict(tester, money=750)], "only_new": False}),
                 lambda s, b: s == 200 and b["result"]["changed"] == 1),
                ("account list", account_call("account_list", {"after": 0}, "location:l01_escape"),
                 lambda s, b: s == 200 and sorted((a["login"], a["money"]) for a in b["result"]["accounts"]) == [("Ghost", None), ("Tester", 750)]),
                ("account list after", account_call("account_list", {"after": 1}),
                 lambda s, b: s == 200 and [a["login"] for a in b["result"]["accounts"]] == ["Tester"] and b["result"]["revision"] == 2),
                ("account bad login", account_call("account_put", {"accounts": [dict(tester, login="a|b")], "only_new": False}),
                 lambda s, b: s == 400),
                ("account by admin", account_call("account_list", {"after": 0}, "admin"), lambda s, b: s == 403),
            ]
            for name, (status, body), good in checks:
                if not good(status, body):
                    failures.append(name)
                    print("FAIL", name, status, json.dumps(body)[:400])
        print(f"compared {len(results[0])} steps, {len(failures)} differ")
        if EXE is None:
            for name, status, body in results[0]:
                print(status, name, json.dumps(body, ensure_ascii=False)[:160])
            return
    finally:
        for process in processes:
            process.kill()
            process.wait()
    # Restart: the C++ master reopens the same DB (epoch 2), the calendar continues.
    folder = work / "cpp"
    process = subprocess.Popen([str(EXE), "serve", "--config", str(folder / "config.json"), "--port", "38613", "--root", str(work)], cwd=folder)
    try:
        wait_port(38613, process)
        status, body = ready_call(Client(38613, config), "GET", "/v1/clock", actor="observer:engine")
        clock = json.loads(body).get("result") or {"error": json.loads(body)}
        if status != 200 or clock.get("authority_epoch") != 2 or clock.get("world_ms", 0) < 63676137600000:
            failures.append("restart")
            print("DIFF restart", status, clock)
    finally:
        process.kill()
        process.wait()
    # The Python service opens the DB the C++ master wrote, and the other way round.
    shutil.copytree(work / "cpp", work / "cpp_to_python")
    process = subprocess.Popen([sys.executable, "-m", "lostzone", "serve", "--config", str(work / "cpp_to_python" / "config.json"), "--port", "38614"],
                               cwd=ROOT / "backend", stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        wait_port(38614, process)
        status, body = ready_call(Client(38614, config), "POST", "/v1/console", {"line": "players"})
        if status != 200 or "l01_escape: Tester" not in json.loads(body)["result"]["text"]:
            failures.append("python reads cpp db")
            print("DIFF python reads cpp db", status, body)
    finally:
        process.kill()
        process.wait()
    if failures:
        raise SystemExit("engine master differs from the Python service: " + ", ".join(failures))
    print("engine master matches the Python service")


if __name__ == "__main__":
    main()
