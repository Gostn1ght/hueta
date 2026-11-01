"""MI24 (owner's commissioned model) textures for X-Ray.

The body uses an Unreal layered material: no albedo, only masks (MA, MAH)
over tiling paint/metal/rust. A plausible albedo is baked from the masks:
two-tone camouflage (MAH.G), edge wear to bare metal (MA.G), grime in
cavities (MA.B), rust/stains (MA.R), ambient occlusion (MA.A). Details and
rotor have real albedo maps. Output: DXT DDS with full mip chains.
"""
import struct
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

SRC = Path(r"J:\LostZone_Work\_work\mi24_src\MI24\Textures")
OUT = Path(sys.argv[1] if len(sys.argv) > 1 else r"J:\LostZone_Work\_work\mi24_src\out\textures\veh")
OUT.mkdir(parents=True, exist_ok=True)
SIZE = 4096        # albedo (owner 2026-10-18: the 2K port looked blurred)
BUMP = 2048        # X-Ray bump pairs from the source normal maps


def load(name, size=SIZE):
    im = Image.open(SRC / f"T_{name}_MIP0.png").convert("RGBA").resize((size, size), Image.LANCZOS)
    return np.asarray(im).astype(np.float32) / 255.0


def lerp(a, b, t):
    return a + (b - a) * t[..., None]


def bake_body(index):
    ma, mah = load(f"air_mi24_base_{index}_MA"), load(f"air_mi24_base_{index}_MAH")
    light = np.array([0.47, 0.43, 0.31], np.float32)   # sand
    dark = np.array([0.25, 0.29, 0.19], np.float32)    # olive
    metal = np.array([0.52, 0.52, 0.50], np.float32)
    grime = np.array([0.17, 0.15, 0.11], np.float32)
    rust = np.array([0.34, 0.22, 0.14], np.float32)
    color = lerp(np.broadcast_to(light, ma.shape[:2] + (3,)), dark, mah[..., 1])
    color = lerp(color, rust, ma[..., 0] * 0.22)
    color = lerp(color, grime, ma[..., 2] * 0.45)
    color = lerp(color, metal, np.clip(ma[..., 1] * 1.3 - 0.35, 0, 1) * 0.7)
    color *= (0.35 + 0.65 * ma[..., 3])[..., None]
    return np.clip(color, 0, 1)


def mip_chain(image):
    levels = [image]
    while min(levels[-1].size) > 4:
        w, h = levels[-1].size
        levels.append(levels[-1].resize((max(1, w // 2), max(1, h // 2)), Image.LANCZOS))
    return levels


def write_dds(path, image, fmt):
    """DXT1/DXT5 with a full mip chain: each level is compressed by Pillow
    and the payloads are joined under one header."""
    image = image.convert("RGBA")
    payloads = []
    with tempfile.TemporaryDirectory() as tmp:
        for i, level in enumerate(mip_chain(image)):
            p = Path(tmp) / f"{i}.dds"
            level.save(p, pixel_format=fmt)
            payloads.append(p.read_bytes()[128:])
    header = bytearray(128)
    w, h = image.size
    block = 8 if fmt == "DXT1" else 16
    struct.pack_into("<4sIIIIIII", header, 0, b"DDS ", 124, 0x1 | 0x2 | 0x4 | 0x1000 | 0x20000 | 0x80000,
                     h, w, max(1, (w + 3) // 4) * max(1, (h + 3) // 4) * block, 0, len(payloads))
    struct.pack_into("<II4s", header, 76, 32, 0x4, fmt.encode())
    struct.pack_into("<I", header, 108, 0x1000 | 0x8 | 0x400000)
    path.write_bytes(bytes(header) + b"".join(payloads))
    return len(payloads)


def save(name, array_or_image, fmt="DXT1"):
    image = array_or_image if isinstance(array_or_image, Image.Image) else Image.fromarray((array_or_image * 255).astype(np.uint8))
    image.save(OUT.parent.parent / f"preview_{name}.png") if image.mode != "RGBA" else None
    mips = write_dds(OUT / f"{name}.dds", image, fmt)
    print(name, image.size, fmt, "mips", mips, (OUT / f"{name}.dds").stat().st_size)


def write_thm(path, fmt, size, bump):
    """X-Ray texture description (ETextureParams.cpp): image type, Blinn-Phong
    material, bump mode "use" naming the bump texture. Anomaly reads only .thm
    descriptors for bumps (DCP's .ltx ones are a Lost Alpha DC feature)."""
    def chunk(cid, data):
        return struct.pack("<II", cid, len(data)) + data
    params = struct.pack("<IIIIIIII", fmt, 0x0100 | 0x0200, 0, 0, 0, 5, size, size)
    data = (chunk(0x0813, struct.pack("<I", 1)) + chunk(0x0812, params) + chunk(0x0814, struct.pack("<I", 0)) +
            chunk(0x0816, struct.pack("<If", 1, 0.5)) +
            chunk(0x0817, struct.pack("<fI", 0.05, 2) + bump.encode("ascii") + b"\0"))
    path.write_bytes(data)


def save_bump(name, normal_src, gloss):
    """X-Ray bump pair: <name>_bump (DXT5: R gloss, G normal z, B normal y,
    A normal x - the shaders read .wzy) and a neutral <name>_bump# (the
    error term, 0.5). DCP's textures use the same layout. A per-texture .ltx
    (Modded Exes texture descriptor) names the bump for the diffuse."""
    # Preserve the source normal-map resolution: the body has 4K normals,
    # details/rotors have 2K. Neither downsample detail nor upscale missing data.
    with Image.open(SRC / f"T_{normal_src}_MIP0.png") as source:
        side = source.width
        assert source.width == source.height and side <= SIZE
    n = load(normal_src, side)
    if np.ndim(gloss) and gloss.shape != n.shape[:2]:
        gloss = np.asarray(Image.fromarray(gloss.astype(np.float32)).resize((side,side),Image.LANCZOS))
    g = np.clip(gloss if np.ndim(gloss) else np.full(n.shape[:2], gloss, np.float32), 0, 1)
    bump = np.stack([g, n[..., 2], n[..., 1], n[..., 0]], axis=-1)
    write_dds(OUT / f"{name}_bump.dds", Image.fromarray((bump * 255).astype(np.uint8), "RGBA"), "DXT5")
    neutral = bytearray(128)
    struct.pack_into("<4sIIIIIII", neutral, 0, b"DDS ", 124, 0x1 | 0x2 | 0x4 | 0x1000, 1, 1, 4, 0, 0)
    struct.pack_into("<IIIIIIII", neutral, 76, 32, 0x41, 0, 32, 0xff0000, 0xff00, 0xff, 0xff000000)
    struct.pack_into("<I", neutral, 108, 0x1000)
    (OUT / f"{name}_bump#.dds").write_bytes(bytes(neutral) + bytes([128, 128, 128, 128]))
    write_thm(OUT / f"{name}.thm", fmt=0, size=SIZE, bump="veh" + chr(92) + name + "_bump")
    print(name, "bump", side)


def roughness_gloss(name, scale=0.6):
    rma = load(name, BUMP)
    return (1.0 - rma[..., 0]) * scale


save("veh_mi24_lz_body1", bake_body(1))
save("veh_mi24_lz_body2", bake_body(2))
details = Image.open(SRC / "T_air_mi24_details_D_MIP0.png").convert("RGB").resize((SIZE, SIZE), Image.LANCZOS)
save("veh_mi24_lz_details", details)
rotor = Image.open(SRC / "T_air_mi24_rotor_D_MIP0.png").convert("RGBA").resize((SIZE, SIZE), Image.LANCZOS)
save("veh_mi24_lz_rotor", rotor, "DXT5")
# Painted body: low gloss, more on worn edges (MA.G).
for index in (1, 2):
    wear = load(f"air_mi24_base_{index}_MA", BUMP)[..., 1]
    save_bump(f"veh_mi24_lz_body{index}", f"air_mi24_base_{index}_N", 0.18 + 0.35 * np.clip(wear * 1.3 - 0.35, 0, 1))
save_bump("veh_mi24_lz_details", "air_mi24_details_N", roughness_gloss("air_mi24_details_RMA"))
save_bump("veh_mi24_lz_rotor", "air_mi24_rotor_N", roughness_gloss("air_mi24_rotor_RMA"))
# Glass: tinted, partly transparent (models\transparent uses the alpha).
glass = Image.new("RGBA", (64, 64), (52, 62, 66, 110))
save("veh_mi24_lz_glass", glass, "DXT5")
