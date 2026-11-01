"""Lossless NCH3..9 admission for staged player migration, never live authority.

Actor, progress and item-state packets stay opaque. Decoding native runtime
positions, task objects and persistent item IDs belongs to the engine adapter.
The file has no WorldID, seed, account or slot: these must be bound explicitly.
"""
import base64
from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
import struct
import uuid
import zlib

from .store import Conflict, Invalid, Unavailable, canonical, identifier

FILE_LIMIT = 20 * 1024 * 1024
BATCH_LIMIT = 64 * 1024 * 1024
PACKET_LIMIT = 16 * 1024


def _crc_table():
    table = []
    for value in range(256):
        for _ in range(8):
            value = (value >> 1) ^ (0x82f63b78 if value & 1 else 0)
        table.append(value)
    return tuple(table)


CRC_TABLE = _crc_table()


def crc32c(data):
    # Native SSE4.2 starts at ~0U and does not apply a final XOR.
    crc = 0xffffffff
    for byte in data:
        crc = (crc >> 8) ^ CRC_TABLE[(crc ^ byte) & 255]
    return crc


class Reader:
    def __init__(self, data, version):
        self.data, self.version, self.offset = data, version, 4

    def take(self, size):
        if size < 0 or size > len(self.data) - self.offset:
            raise Invalid("truncated native player save")
        start = self.offset
        self.offset += size
        return self.data[start:self.offset]

    def number(self, fmt):
        return struct.unpack(fmt, self.take(struct.calcsize(fmt)))[0]

    def text(self, limit):
        end = self.data.find(b"\0", self.offset, self.offset + limit + 1)
        if end < 0:
            raise Invalid("unterminated native save string")
        raw = self.take(end - self.offset)
        self.take(1)
        # Preserve undefined CP1251 byte 0x98 losslessly too. These decoded
        # strings are metadata, never re-encoded to replace the original file.
        return raw.decode("cp1251", errors="surrogateescape")

    def packet(self, limit):
        size, expected = self.number("<I"), self.number("<I")
        if size > limit:
            raise Invalid("native save packet exceeds format bounds")
        data = self.take(size)
        if crc32c(data) != expected and not (self.version < 8 and zlib.crc32(data) == expected):
            raise Invalid("native save checksum mismatch")
        return data

    def items(self):
        count = self.number("<I")
        if count > 512:
            raise Invalid("native save item count exceeds format bounds")
        sections = []
        for index in range(count):
            section = self.text(128)
            if not section:
                raise Invalid("empty native item section")
            if self.number("<H") > index:
                raise Invalid("native item parent is forward or cyclic")
            if self.version >= 4:
                self.number("<H")  # packed runtime place; remains opaque
            self.packet(PACKET_LIMIT)
            if self.version >= 7:
                size = self.number("<H")
                if size > 512:
                    raise Invalid("native item state exceeds format bounds")
                self.take(size)
            sections.append(section)
        return sections


@dataclass(frozen=True)
class NativeSave:
    raw: bytes
    version: int
    sha256: str
    item_count: int
    safe_count: int
    progress_bytes: int
    actor_bytes: int
    sections: tuple
    inventory_cells: int
    lives_remaining: int = 5

    def summary(self):
        result = {"format": "NCHA" if self.version == 10 else "NCH" + str(self.version), "sha256": self.sha256,
                  "bytes": len(self.raw), "items": self.item_count, "safe_items": self.safe_count,
                  "actor_bytes": self.actor_bytes, "progress_bytes": self.progress_bytes}
        if self.version >= 9:
            result["inventory_cells"] = self.inventory_cells
        if self.version >= 10:
            result["lives_remaining"] = self.lives_remaining
        return result


def parse_native_save(data):
    if type(data) is not bytes or not 4 <= len(data) <= FILE_LIMIT:
        raise Invalid("native player save exceeds admission bounds")
    if data[:3] != b"NCH" or data[3] not in b"3456789A":
        raise Invalid("unsupported native player save format")
    version = 10 if data[3] == ord("A") else data[3] - ord("0")
    reader = Reader(data, version)
    name = reader.text(63)
    if not name or any(ord(char) < 32 or char == "|" for char in name):
        raise Invalid("invalid native character name")
    reader.text(32)  # faction
    reader.text(4096)  # loadout
    if version >= 5:
        reader.text(512)
        reader.text(1536)
    reader.number("<B")  # native loader permits legacy economy values
    initialized, respawn = reader.number("<B"), reader.number("<B")
    if initialized not in (0, 1) or respawn not in (0, 1):
        raise Invalid("invalid native player flags")
    actor = reader.packet(PACKET_LIMIT)
    sections = reader.items()
    progress = reader.packet(1024 * 1024) if version >= 4 else b""
    safe_sections = []
    if version >= 6:
        if reader.number("<I") == 0:
            raise Invalid("invalid native storage revision")
        reader.text(32)
        reader.text(80)
        safe_sections = reader.items()
    inventory_cells = reader.number("<I") if version >= 9 else 0
    if inventory_cells > 512:
        raise Invalid("native inventory capacity exceeds format bounds")
    lives_remaining = reader.number("<B") if version >= 10 else (4 if respawn else 5)
    if lives_remaining > 5:
        raise Invalid("native lives counter exceeds format bounds")
    if reader.offset != len(data):
        raise Invalid("native player save has trailing data")
    return NativeSave(data, version, hashlib.sha256(data).hexdigest(), len(sections),
                      len(safe_sections), len(progress), len(actor), tuple(sections + safe_sections), inventory_cells, lives_remaining)


def identity(world_id, seed, account, slot):
    if type(world_id) is not int or not 0 < world_id < 2**64 or type(seed) is not int or not 0 <= seed < 2**64:
        raise Invalid("explicit WorldID and seed are required")
    if not isinstance(account, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{3,20}", account):
        raise Invalid("invalid native account identity")
    if type(slot) is not int or not 1 <= slot <= 10:
        raise Invalid("invalid native character slot")
    return uuid.uuid5(uuid.NAMESPACE_URL, f"lostzone:native-player:{world_id}:{seed}:{account.lower()}:{slot}").hex


def scan_directory(source, world_id, seed, location, known_sections=None):
    """Read only final .bin files; no temporary commits or recursive guessing."""
    identifier(location)
    source = Path(source).resolve(strict=True)
    if not source.is_dir():
        raise Invalid("native save source is not a directory")
    plan, seen, total = [], set(), 0
    for path in sorted(source.glob("netcoop_character_*.bin")):
        match = re.fullmatch(r"netcoop_character_([A-Za-z0-9_.-]{3,20})_(10|[1-9])\.bin", path.name)
        if not match or path.is_symlink() or path.resolve().parent != source:
            raise Invalid("invalid native character filename")
        account, slot = match[1].lower(), int(match[2])
        player_id = identity(world_id, seed, account, slot)
        if player_id in seen or len(plan) >= 1024:
            raise Invalid("duplicate or excessive native character slots")
        before = path.stat()
        if before.st_size > FILE_LIMIT or total + before.st_size > BATCH_LIMIT:
            raise Invalid("native migration batch exceeds admission bounds")
        with path.open("rb") as stream:
            raw = stream.read(FILE_LIMIT + 1)
        after = path.stat()
        if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
            raise Conflict("native save changed during migration scan; stop all writers first")
        saved = parse_native_save(raw)
        if known_sections is not None and any(section not in known_sections for section in saved.sections):
            raise Invalid("native save references an unavailable item section")
        seen.add(player_id)
        total += len(raw)
        plan.append({"id": player_id, "account": account, "slot": slot, "location": location,
                     "world_id": str(world_id), "seed": str(seed), "save": saved})
    if not plan:
        raise Invalid("no final native player saves found")
    return plan


def stage_import(store, plan):
    """Archive an entire batch atomically without replacing an existing slot.

    OS store lock excludes a running master. Native locations must be stopped
    separately. No entities/sessions/items are minted: M2 owns live admission.
    """
    if store.epoch is not None:
        raise Conflict("staged migration requires an offline master")
    if not plan or len(plan) > 1024 or sum(len(record["save"].raw) for record in plan) > BATCH_LIMIT:
        raise Invalid("invalid native migration batch")
    with store.transaction() as tx:
        world = tx.execute("SELECT world_id,seed FROM world WHERE singleton=1").fetchone()
        if world is None:
            raise Conflict("initialize the intended master world before staging player saves")
        inserted = 0
        seen = set()
        for record in plan:
            player_id = identity(int(record["world_id"]), int(record["seed"]), record["account"], record["slot"])
            if player_id != record["id"] or player_id in seen:
                raise Invalid("invalid or duplicate player identity")
            seen.add(player_id)
            identifier(record["location"])
            if (record["world_id"], record["seed"]) != tuple(world):
                raise Conflict("native import belongs to another world")
            saved = parse_native_save(record["save"].raw)
            old = tx.execute("SELECT sha256,location FROM native_player_import WHERE id=?", (player_id,)).fetchone()
            if old:
                if (old["sha256"], old["location"]) != (saved.sha256, record["location"]):
                    raise Conflict("staged player slot already contains a different save")
                continue
            tx.execute("INSERT INTO native_player_import VALUES(?,?,?,?,?,?,?,?,?)",
                       (player_id, record["account"].lower(), record["slot"], record["location"],
                        record["world_id"], record["seed"], saved.sha256,
                        canonical(saved.summary()), base64.b64encode(saved.raw).decode("ascii")))
            inserted += 1
        return {"staged": inserted, "unchanged": len(plan) - inserted,
                "bytes": sum(len(record["save"].raw) for record in plan), "live_authority_changed": False}


def read_import(store, player_id):
    """Return verified original bytes; never turn a staged slot into a session."""
    with store.lock:
        row = store.db.execute("SELECT * FROM native_player_import WHERE id=?", (player_id,)).fetchone()
        if row is None:
            raise Invalid("unknown staged native player slot")
        try:
            raw = base64.b64decode(row["payload_base64"], validate=True)
            saved = parse_native_save(raw)
            if saved.sha256 != row["sha256"] or canonical(saved.summary()) != row["summary"]:
                raise Invalid("staged native save checksum mismatch")
            if identity(int(row["world_id"]), int(row["seed"]), row["account"], row["slot"]) != player_id:
                raise Invalid("staged native identity mismatch")
            return saved
        except (ValueError, Invalid) as error:
            raise Unavailable("staged native player save failed integrity validation") from error
