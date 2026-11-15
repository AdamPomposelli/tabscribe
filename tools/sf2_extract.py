"""Extract one preset from a SoundFont 2 file into a small standalone .sf2.

The kept preset is renumbered to bank 0 / program 24 (the program Tabscribe's scores use), so
the app can swap guitar sounds by just loading a different file, without regenerating MIDI.

    python tools/sf2_extract.py in.sf2 out.sf2 --bank 0 --program 25 --name "Steel Guitar"
"""
from __future__ import annotations

import argparse
import struct


def _chunks(b: bytes, off: int, end: int):
    while off < end:
        cid = b[off:off + 4].decode("latin1")
        size = struct.unpack("<I", b[off + 4:off + 8])[0]
        yield cid, off + 8, size
        off += 8 + size + (size & 1)


def _records(data: bytes, size: int):
    return [data[i:i + size] for i in range(0, len(data), size)]


def _riff(cid: str, payload: bytes) -> bytes:
    pad = b"\0" if len(payload) & 1 else b""
    return cid.encode() + struct.pack("<I", len(payload)) + payload + pad


def _list(typ: str, *subs: bytes) -> bytes:
    return _riff("LIST", typ.encode() + b"".join(subs))


def _zstr(s: str, n: int = 0) -> bytes:
    raw = s.encode("latin1", "replace")[: (n - 1) if n else None] + b"\0"
    if n:
        return raw.ljust(n, b"\0")
    return raw + (b"\0" if len(raw) & 1 else b"")


def extract(src: str, dst: str, bank: int, program: int, name: str, out_program: int = 24, copyright: str = "",
            gain: float = 1.0, preset_att: int | None = None) -> None:
    b = open(src, "rb").read()
    assert b[:4] == b"RIFF" and b[8:12] == b"sfbk", "not a SoundFont 2 file"
    parts: dict[tuple[str, str], bytes] = {}
    for cid, o, s in _chunks(b, 12, len(b)):
        if cid == "LIST":
            typ = b[o:o + 4].decode()
            for c2, o2, s2 in _chunks(b, o + 4, o + s):
                parts[(typ, c2)] = b[o2:o2 + s2]
    smpl = parts[("sdta", "smpl")]
    pd = {k[1]: v for k, v in parts.items() if k[0] == "pdta"}
    phdr = _records(pd["phdr"], 38)
    pbag = [struct.unpack("<HH", r) for r in _records(pd["pbag"], 4)]
    pmod = _records(pd["pmod"], 10)
    pgen = [struct.unpack("<Hh", r) for r in _records(pd["pgen"], 4)]
    inst = _records(pd["inst"], 22)
    ibag = [struct.unpack("<HH", r) for r in _records(pd["ibag"], 4)]
    imod = _records(pd["imod"], 10)
    igen = [struct.unpack("<Hh", r) for r in _records(pd["igen"], 4)]
    shdr = _records(pd["shdr"], 46)

    pi = next(i for i, r in enumerate(phdr[:-1]) if struct.unpack("<HH", r[20:24]) == (program, bank))
    pb0, pb1 = struct.unpack("<H", phdr[pi][24:26])[0], struct.unpack("<H", phdr[pi + 1][24:26])[0]

    # preset zones -> instruments used
    new_pbag, new_pgen, new_pmod, inst_map = [], [], [], {}
    for z in range(pb0, pb1):
        g0, m0 = pbag[z]
        g1, m1 = pbag[z + 1]
        new_pbag.append((len(new_pgen), len(new_pmod)))
        for oper, amt in pgen[g0:g1]:
            if oper == 41:
                amt = inst_map.setdefault(amt & 0xFFFF, len(inst_map))
            elif oper == 48 and preset_att is not None:  # initialAttenuation (cB): level-matching
                amt = preset_att
            new_pgen.append((oper, amt))
        new_pmod.extend(pmod[m0:m1])
    new_pbag.append((len(new_pgen), len(new_pmod)))

    # instruments -> samples used
    new_inst, new_ibag, new_igen, new_imod, samp_map = [], [], [], [], {}
    for old in sorted(inst_map, key=inst_map.get):
        ib0 = struct.unpack("<H", inst[old][20:22])[0]
        ib1 = struct.unpack("<H", inst[old + 1][20:22])[0]
        new_inst.append(inst[old][:20] + struct.pack("<H", len(new_ibag)))
        for z in range(ib0, ib1):
            g0, m0 = ibag[z]
            g1, m1 = ibag[z + 1]
            new_ibag.append((len(new_igen), len(new_imod)))
            for oper, amt in igen[g0:g1]:
                if oper == 53:
                    amt = samp_map.setdefault(amt & 0xFFFF, len(samp_map))
                new_igen.append((oper, amt))
            new_imod.extend(imod[m0:m1])
    new_inst.append(_zstr("EOI", 20) + struct.pack("<H", len(new_ibag)))
    new_ibag.append((len(new_igen), len(new_imod)))

    # stereo partners must come along too
    changed = True
    while changed:
        changed = False
        for old in list(samp_map):
            link, stype = struct.unpack("<HH", shdr[old][42:46])
            if stype in (2, 4, 8) and link not in samp_map and link < len(shdr) - 1:
                samp_map[link] = len(samp_map)
                changed = True

    # copy sample data, rebasing offsets
    data = bytearray()
    new_shdr = [b""] * len(samp_map)
    for old, new in samp_map.items():
        r = shdr[old]
        start, end, ls, le, rate = struct.unpack("<IIIII", r[20:40])
        pitch, corr = r[40], r[41]
        link, stype = struct.unpack("<HH", r[42:46])
        base = len(data) // 2
        data += smpl[start * 2:end * 2] + b"\0" * 92  # 46 zero samples after each sample (spec)
        d = base - start
        new_link = samp_map.get(link, 0)
        new_shdr[new] = (r[:20] + struct.pack("<IIIII", start + d, end + d, ls + d, le + d, rate)
                         + bytes([pitch, corr]) + struct.pack("<HH", new_link, stype))
    new_shdr.append(_zstr("EOS", 20) + b"\0" * 26)

    if gain != 1.0:  # level-match libraries: scale the samples, never past full scale
        import array
        pcm = array.array("h")
        pcm.frombytes(bytes(data))
        peak = max(1, max(abs(v) for v in pcm))
        g = min(gain, 32000 / peak)
        pcm = array.array("h", (int(v * g) for v in pcm))
        data = bytearray(pcm.tobytes())
        print(f"gain x{g:.2f} (asked x{gain}, peak {peak})")

    ph = (_zstr(name, 20) + struct.pack("<HHH", out_program, 0, 0) + phdr[pi][26:38])
    eop = _zstr("EOP", 20) + struct.pack("<HHH", 0, 0, len(new_pbag) - 1) + b"\0" * 12
    term_mod = b"\0" * 10
    term_gen = struct.pack("<Hh", 0, 0)

    info = _list("INFO",
                 _riff("ifil", struct.pack("<HH", 2, 1)),
                 _riff("isng", _zstr("EMU8000")),
                 _riff("INAM", _zstr(name)),
                 *([_riff("ICOP", _zstr(copyright))] if copyright else []),
                 _riff("ICMT", _zstr(f"Extracted from {src.split('/')[-1]} (bank {bank}, program {program}) for Tabscribe")))
    sdta = _list("sdta", _riff("smpl", bytes(data)))
    pdta = _list("pdta",
                 _riff("phdr", ph + eop),
                 _riff("pbag", b"".join(struct.pack("<HH", *x) for x in new_pbag)),
                 _riff("pmod", b"".join(new_pmod) + term_mod),
                 _riff("pgen", b"".join(struct.pack("<Hh", o, a if a < 32768 else a - 65536) for o, a in new_pgen) + term_gen),
                 _riff("inst", b"".join(new_inst)),
                 _riff("ibag", b"".join(struct.pack("<HH", *x) for x in new_ibag)),
                 _riff("imod", b"".join(new_imod) + term_mod),
                 _riff("igen", b"".join(struct.pack("<Hh", o, a if a < 32768 else a - 65536) for o, a in new_igen) + term_gen),
                 _riff("shdr", b"".join(new_shdr)))
    body = b"sfbk" + info + sdta + pdta
    with open(dst, "wb") as f:
        f.write(b"RIFF" + struct.pack("<I", len(body)) + body)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--bank", type=int, default=0)
    ap.add_argument("--program", type=int, required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--copyright", default="")
    ap.add_argument("--gain", type=float, default=1.0, help="scale the samples (level-matching)")
    ap.add_argument("--preset-att", type=int, help="override the preset's attenuation in centibels (level-matching)")
    a = ap.parse_args()
    extract(a.src, a.dst, a.bank, a.program, a.name, copyright=a.copyright, gain=a.gain, preset_att=a.preset_att)
