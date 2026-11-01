"""Exact native NCH admission and offline master staging; no game process."""
import base64
import contextlib
import io
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lostzone import Conflict, Invalid, Store, World
from lostzone.__main__ import create_config, player_migration
from lostzone.native_save import crc32c, identity, parse_native_save, read_import, scan_directory, stage_import


def independent_crc(data):
    value = 0xffffffff
    for byte in data:
        value ^= byte
        for _ in range(8):
            value = (value >> 1) ^ (0x82f63b78 if value & 1 else 0)
    return value


def native_fixture(version=8, *, ieee=False, section=b"wpn_pm", parent=0, state=b"uid/ammo/condition", actor=b"actor-position-state", progress=b"tasks/info/lua/origins", name=b"player", lives=5, dead=False):
    def packet(raw):
        checksum = zlib.crc32(raw) if ieee else independent_crc(raw)
        return struct.pack("<II", len(raw), checksum) + raw
    data = b"NCH" + (b"A" if version==10 else bytes([48 + version])) + name + b"\0stalker\0loadout\0"
    if version >= 5:
        data += b"description\0history\0"
    data += bytes([1,1,int(dead)]) + packet(actor)
    item = section + b"\0" + struct.pack("<H", parent)
    if version >= 4:
        item += struct.pack("<H", 5)
    item += packet(b"spawn-upgrades")
    if version >= 7:
        item += struct.pack("<H", len(state)) + state
    data += struct.pack("<I", 1) + item
    if version >= 4:
        data += packet(progress)
    if version >= 6:
        data += struct.pack("<I", 19) + b"request\0signature\0" + struct.pack("<I", 1) + item
    if version >= 9:
        data += struct.pack("<I",240)
    if version >= 10:
        data += bytes([lives])
    return data


class NativeSaveTest(unittest.TestCase):
    def test_native_checksum_and_legacy_versions_preserve_exact_bytes(self):
        self.assertEqual(crc32c(b"123456789"), 0x1cf96d7c)
        self.assertEqual(crc32c(b""), 0xffffffff)
        for version in range(3, 10):
            for ieee in (False, True):
                raw = native_fixture(version, ieee=ieee)
                if version >= 8 and ieee:
                    with self.assertRaises(Invalid):
                        parse_native_save(raw)
                    continue
                saved = parse_native_save(raw)
                self.assertEqual(saved.raw, raw)
                self.assertEqual(saved.version, version)
                self.assertEqual(saved.inventory_cells, 240 if version >= 9 else 0)
                self.assertEqual("inventory_cells" in saved.summary(), version >= 9)
                self.assertEqual(saved.item_count, 1)
                self.assertEqual(saved.safe_count, int(version >= 6))
                self.assertEqual(saved.progress_bytes, len(b"tasks/info/lua/origins") if version >= 4 else 0)
        raw = native_fixture(name="Сталкер".encode("cp1251") + b"\x98")
        self.assertEqual(parse_native_save(raw).raw, raw)

    def test_five_lives_persist_and_migrate(self):
        for lives in range(6):
            saved=parse_native_save(native_fixture(10,lives=lives,dead=lives<5))
            self.assertEqual(saved.lives_remaining,lives)
            self.assertEqual(saved.summary()["format"],"NCHA")
            self.assertEqual(saved.summary()["lives_remaining"],lives)
        self.assertEqual(parse_native_save(native_fixture(9,dead=True)).lives_remaining,4)
        self.assertEqual(parse_native_save(native_fixture(9)).lives_remaining,5)
        for raw in (native_fixture(10,lives=6),native_fixture(10)[:-1]):
            with self.assertRaises(Invalid): parse_native_save(raw)

    def test_truncation_corruption_forward_parents_and_trailing_bytes_fail_closed(self):
        raw = native_fixture()
        for cut in range(len(raw)):
            with self.subTest(cut=cut), self.assertRaises(Invalid):
                parse_native_save(raw[:cut])
        for value in (native_fixture(9)[:-4] + struct.pack("<I",513), raw + b"\0", b"NCHX" + raw[4:], native_fixture(parent=1),
                      native_fixture(state=b"x" * 513), native_fixture(actor=b"x" * 16385),
                      native_fixture(progress=b"x" * (1024 * 1024 + 1)), native_fixture(name=b"bad|name"),
                      native_fixture(name=b"x" * 64), native_fixture(section=b"")):
            with self.assertRaises(Invalid):
                parse_native_save(value)
        corrupted = bytearray(raw)
        corrupted[corrupted.index(b"actor-position-state")] ^= 1
        with self.assertRaises(Invalid):
            parse_native_save(bytes(corrupted))

    def test_empty_opaque_packets_are_supported(self):
        saved = parse_native_save(native_fixture(actor=b"", progress=b"", state=b""))
        self.assertEqual((saved.actor_bytes, saved.progress_bytes), (0, 0))

    def test_stable_identity_is_world_seed_account_and_slot_bound(self):
        expected = identity(42, 7, "Alice", 1)
        self.assertEqual(expected, identity(42, 7, "alice", 1))
        self.assertNotEqual(expected, identity(43, 7, "Alice", 1))
        self.assertNotEqual(expected, identity(42, 8, "Alice", 1))
        self.assertNotEqual(expected, identity(42, 7, "Alice", 2))
        for args in ((True, 7, "Alice", 1), (42, False, "Alice", 1), (42, 7, "../alice", 1),
                     (42, 7, "x" * 21, 1), (42, 7, "Alice", 0), (42, 7, "Alice", True)):
            with self.assertRaises(Invalid):
                identity(*args)

    def test_directory_scan_checks_sections_and_excludes_temporary_commits(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            good = root / "netcoop_character_alice_1.bin"
            good.write_bytes(native_fixture())
            original = good.read_bytes()
            (root / "netcoop_character_bob_1.bin.99.tmp").write_bytes(b"partial")
            plan = scan_directory(root, 42, 7, "cordon", {"wpn_pm"})
            self.assertEqual(len(plan), 1)
            self.assertEqual(plan[0]["save"].raw, original)
            with self.assertRaises(Invalid):
                scan_directory(root, 42, 7, "cordon", {"other"})
            (root / "netcoop_character_bob_1.bin").write_bytes(b"broken")
            with self.assertRaises(Invalid):
                scan_directory(root, 42, 7, "cordon")
            self.assertEqual(good.read_bytes(), original)

    def test_offline_staging_is_atomic_idempotent_and_preserves_native_sources(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source"
            source.mkdir()
            alice = source / "netcoop_character_alice_1.bin"
            alice.write_bytes(native_fixture())
            (source / "netcoop_character_bob_1.bin").write_bytes(native_fixture(7, ieee=True))
            database = root / "world.sqlite"
            with contextlib.closing(Store(database)) as store:
                World(store, world_id=42, seed=7)
            plan = scan_directory(source, 42, 7, "cordon")
            with contextlib.closing(Store(database)) as store:
                result = stage_import(store, plan)
                self.assertEqual(result["staged"], 2)
                self.assertFalse(result["live_authority_changed"])
                self.assertEqual(stage_import(store, plan)["unchanged"], 2)
                self.assertEqual(store.db.execute("SELECT COUNT(*) FROM entity").fetchone()[0], 0)
                self.assertEqual(store.db.execute("SELECT epoch FROM world").fetchone()[0], 1)
                archived = store.db.execute("SELECT payload_base64 FROM native_player_import WHERE account='alice'").fetchone()[0]
                self.assertEqual(base64.b64decode(archived), alice.read_bytes())
                self.assertEqual(read_import(store, plan[0]["id"]).raw, alice.read_bytes())
                alice.write_bytes(native_fixture(progress=b"new task state"))
                conflict_plan = scan_directory(source, 42, 7, "cordon")
                with self.assertRaises(Conflict):
                    stage_import(store, conflict_plan)
                self.assertEqual(store.db.execute("SELECT COUNT(*) FROM native_player_import").fetchone()[0], 2)
                wrong = scan_directory(source, 99, 7, "cordon")
                with self.assertRaises(Conflict):
                    stage_import(store, wrong)
                World(store, world_id=42, seed=7)
                with self.assertRaises(Conflict):
                    stage_import(store, plan)
                snapshot = store.read_snapshot(store.snapshot()["id"])
                self.assertEqual(len(snapshot["records"]["native_player_import"]), 2)

    def test_archive_read_rejects_corruption_without_minting_a_session(self):
        from lostzone import Unavailable
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "netcoop_character_alice_1.bin").write_bytes(native_fixture())
            db = root / "world.sqlite"
            with contextlib.closing(Store(db)) as store:
                World(store, world_id=42, seed=7)
            with contextlib.closing(Store(db)) as store:
                plan = scan_directory(root, 42, 7, "cordon")
                stage_import(store, plan)
                store.db.execute("UPDATE native_player_import SET payload_base64='broken'")
                with self.assertRaises(Unavailable):
                    read_import(store, plan[0]["id"])
                self.assertEqual(store.db.execute("SELECT COUNT(*) FROM player_session").fetchone()[0], 0)

    def test_conflict_after_first_row_rolls_back_the_whole_new_batch(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "netcoop_character_bob_1.bin").write_bytes(native_fixture())
            db = root / "world.sqlite"
            with contextlib.closing(Store(db)) as store:
                World(store, world_id=42, seed=7)
            with contextlib.closing(Store(db)) as store:
                stage_import(store, scan_directory(root, 42, 7, "cordon"))
                (root / "netcoop_character_alice_1.bin").write_bytes(native_fixture())
                (root / "netcoop_character_bob_1.bin").write_bytes(native_fixture(progress=b"changed"))
                with self.assertRaises(Conflict):
                    stage_import(store, scan_directory(root, 42, 7, "cordon"))
                self.assertEqual(store.db.execute("SELECT COUNT(*) FROM native_player_import").fetchone()[0], 1)

    def test_schema4_upgrade_preserves_world_and_refuses_parallel_master(self):
        with tempfile.TemporaryDirectory() as folder:
            db = Path(folder) / "world.sqlite"
            with contextlib.closing(Store(db)) as store:
                World(store, world_id=42, seed=7)
                before = tuple(store.db.execute("SELECT * FROM world").fetchone())
                store.db.execute("DROP TABLE native_player_import")
                store.db.execute("DROP TABLE native_player_part")
                store.db.execute("DROP TABLE native_player_upload")
                store.db.execute("DROP TABLE native_player_save")
                store.db.execute("UPDATE metadata SET value='4' WHERE key='schema'")
            with contextlib.closing(Store(db)) as store:
                self.assertEqual(tuple(store.db.execute("SELECT * FROM world").fetchone()), before)
                self.assertEqual(store.db.execute("SELECT value FROM metadata WHERE key='schema'").fetchone()[0], "6")
                with self.assertRaises((OSError, BlockingIOError)):
                    Store(db)

    def test_cli_dry_run_is_read_only_and_never_prints_private_payload(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            config = root / "config.json"
            create_config(config, ["cordon"], world_id=42, seed=7)
            original = config.read_bytes()
            save = root / "netcoop_character_alice_1.bin"
            save.write_bytes(native_fixture())
            with patch("lostzone.__main__.Store", side_effect=AssertionError("dry run opened DB")), contextlib.redirect_stdout(io.StringIO()) as output:
                result = player_migration(config, root, "cordon", 42, 7)
            self.assertEqual(result["validated"], 1)
            self.assertFalse(result["committed"])
            self.assertNotIn("alice", output.getvalue())
            self.assertNotIn("actor-position-state", output.getvalue())
            self.assertEqual(config.read_bytes(), original)
            self.assertFalse((root / "world.sqlite").exists())
            with self.assertRaises(Invalid):
                player_migration(config, root, "garbage", 42, 7)
            with self.assertRaises(Invalid):
                player_migration(config, root, "cordon", 43, 7)


if __name__ == "__main__":
    unittest.main()
