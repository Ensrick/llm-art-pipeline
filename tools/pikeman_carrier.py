"""The Pikeman carrier's sprite slots and animation tables, measured from the installed game (see
docs/SHCDE.md section 3). Pure Python (no bpy, no Pillow), shared by the renderer, the finisher, the
packer and the validator - every number here is a fact about the shipped game, not a guess, and none
of it is decompiled code or an extracted file (see docs/RUNTIME.md section 1 for that line).

Slot formulas (slot = native image number - 1):
  8-facing blocks:   slot = base + 8 x phase + facing
  1-facing blocks:   slot = base + phase                (front only, facing 3)
The walk's `x` alternates (0x-127x) use the walk formula with the halfway pose between phase p and p + 1.

This is one carrier (the one docs/SHCDE.md has a full worked example for, via the Hoplite-style
unit built on it). Building the same module for another carrier means transcribing its own slot
table from docs/SHCDE.md section 3 into a `BLOCKS` dict shaped like this one's.
"""

FACINGS = range(8)
FRONT = 3
FACING_NAMES = ("right-back", "right", "right-front", "front", "left-front", "left", "left-back", "back")
UPDATES_PER_SECOND = 40          # measured from the game: the default engine step is 40 updates/second
PRIMARY_SLOTS = 1142             # 0-253 and 290-1177
ALT_SLOTS = 128                  # 0x-127x
TOTAL_SLOTS = PRIMARY_SLOTS + ALT_SLOTS

# name: (first slot, last slot, base, phases, facings, alt)
BLOCKS = {
    "walk":             dict(first=0, last=127, base=0, phases=range(0, 16), facings=FACINGS, alt=False),
    "walk_x":           dict(first=0, last=127, base=0, phases=range(0, 16), facings=FACINGS, alt=True),
    "celebrate":        dict(first=128, last=191, base=120, phases=range(1, 9), facings=FACINGS, alt=False),
    "idle":             dict(first=192, last=221, base=191, phases=range(1, 31), facings=(FRONT,), alt=False),
    "sit":              dict(first=222, last=253, base=221, phases=range(1, 33), facings=(FRONT,), alt=False),
    "melee_up":         dict(first=290, last=353, base=282, phases=range(1, 9), facings=FACINGS, alt=False),
    "melee_level":      dict(first=354, last=417, base=346, phases=range(1, 9), facings=FACINGS, alt=False),
    "melee_down":       dict(first=418, last=481, base=410, phases=range(1, 9), facings=FACINGS, alt=False),
    "dig":              dict(first=482, last=601, base=474, phases=range(1, 16), facings=FACINGS, alt=False),
    "death_back":       dict(first=602, last=793, base=594, phases=range(1, 25), facings=FACINGS, alt=False),
    "death_back_arrow": dict(first=794, last=985, base=786, phases=range(1, 25), facings=FACINGS, alt=False),
    "death_forward":    dict(first=986, last=1177, base=978, phases=range(1, 25), facings=FACINGS, alt=False),
}

# Native rect sizes per block, in pixels, measured directly from the installed game's own shipped
# sprites (min/median/max height, median/max width, median/max top-above-pivot, max below-pivot -
# see docs/SHCDE.md section 5). Useful as a sanity comparison: a custom render wildly outside these
# ranges is worth a second look, though matching them exactly isn't a goal in itself.
NATIVE_FRAME_SIZES_PX = {
    "walk":             dict(height=(88, 127, 171), width=(108, 160), top=(89.5, 120), below=49),
    "walk_x":           dict(height=(88, 125.5, 168), width=(110, 163), top=(89.5, 120), below=54),
    "celebrate":        dict(height=(111, 138, 169), width=(55, 112), top=(111, 135), below=32),
    "idle":             dict(height=(123, 134, 154), width=(89, 116), top=(108, 110), below=13),
    "sit":              dict(height=(114, 132.5, 164), width=(63, 72), top=(98, 102), below=30),
    "melee_up":         dict(height=(87, 123, 167), width=(96, 138), top=(91.5, 130), below=42),
    "melee_level":      dict(height=(83, 117, 166), width=(84, 160), top=(80.5, 128), below=42),
    "melee_down":       dict(height=(86, 109, 177), width=(94.5, 182), top=(79, 128), below=37),
    "dig":              dict(height=(63, 91.5, 137), width=(63.5, 139), top=(72, 95), below=26),
    "death_back":       dict(height=(39, 93.5, 162), width=(104, 175), top=(50.5, 118), below=58),
    "death_back_arrow": dict(height=(39, 93.5, 167), width=(105.5, 175), top=(50.5, 118), below=55),
    "death_forward":    dict(height=(44, 90, 158), width=(97.5, 192), top=(50, 120), below=54),
}


def slot(block, phase, facing):
    b = BLOCKS[block]
    if tuple(b["facings"]) == (FRONT,):
        assert facing == FRONT, (block, facing)
        return b["base"] + phase
    return b["base"] + 8 * phase + facing


def slot_name(block, phase, facing, file="body_pikeman"):
    """The carrier sprite this frame replaces: <file>-N, or <file>-Nx for a walk alternate."""
    return f"{file}-{slot(block, phase, facing)}{'x' if BLOCKS[block]['alt'] else ''}"


def all_slot_names(file="body_pikeman"):
    """The 1,270 names the native file holds: 0-253 and 290-1177, plus 0x-127x."""
    names = [f"{file}-{n}" for n in range(0, 254)] + [f"{file}-{n}" for n in range(290, 1178)]
    names += [f"{file}-{n}x" for n in range(0, 128)]
    assert len(names) == TOTAL_SLOTS
    return names


def block_frames(block, file="body_pikeman"):
    """(phase, facing, slot name) for every frame of a block."""
    b = BLOCKS[block]
    return [(p, f, slot_name(block, p, f, file)) for p in b["phases"] for f in b["facings"]]


def _self_check():
    seen = {}
    for block in BLOCKS:
        for p, f, name in block_frames(block):
            assert name not in seen, (name, block, seen.get(name))
            seen[name] = block
        b = BLOCKS[block]
        slots = [slot(block, p, f) for p, f, _n in block_frames(block)]
        assert min(slots) == b["first"] and max(slots) == b["last"], (block, min(slots), max(slots))
    assert sorted(seen) == sorted(all_slot_names()), "blocks do not tile the carrier's 1,270 slots exactly"


_self_check()


# --------------------------------------------------------------------------- timing (review movies)
# Each table entry shows for delay + 1 updates. Tables list phases in play order, measured from the
# game (docs/SHCDE.md section 3's "Delay" and "Play order" columns give the same facts in prose).

def _r(a, b):
    step = 1 if b >= a else -1
    return list(range(a, b + step, step))


IDLE_TABLES = {   # delay 0; a per-unit variation bit picks the table
    "variant_a": _r(1, 15) + _r(15, 1) + _r(1, 30) + _r(30, 15) + _r(16, 30) + _r(29, 1),
    "variant_b": _r(1, 30) + _r(30, 1) + [1] * 36,
}
assert len(IDLE_TABLES["variant_a"]) == 120 and len(IDLE_TABLES["variant_b"]) == 96

CELEBRATE_TABLES = {   # delay 4
    "variant_a": [5, 5, 6, 6, 7, 7, 8, 8] * 2,
    "variant_b": [1, 2, 3, 4, 3, 2, 1, 2, 3, 4, 3, 2],
}

SIT_TABLES = {   # delay 2; sub-state order sit down, rest A, rest B, (rest A, rest B ...), stand up
    "sit_down": _r(1, 15) + [14, 13, 12],
    "rest_a": _r(12, 17) + [17, 17] + _r(18, 27) + [27, 27, 27] + _r(28, 32) + [32] * 34,
    "rest_b": (_r(12, 22) + [22] * 6 + _r(23, 26) + _r(28, 32) + _r(12, 17) + [17] * 5 + _r(18, 26) + _r(28, 32)
               + [32] + [12, 12, 12] + _r(13, 27) + [27] * 3 + _r(28, 32)),
    "stand_up": _r(12, 1),
}
assert [len(SIT_TABLES[k]) for k in ("sit_down", "rest_a", "rest_b", "stand_up")] == [18, 60, 78, 12]

MELEE_VARIANTS = [   # delay 2; variants 0, 1, 2, 3 in turn
    [2, 3, 4, 4, 3, 2, 1],
    [1, 2, 3, 4, 4, 4, 4, 3, 3, 2, 2, 1, 1, 1, 1],
    [2, 3, 4, 4, 3, 2, 1],
    [5, 6, 6, 7, 7, 8, 8, 8, 8, 8, 8, 3, 2, 1, 1],
]
assert sum(len(v) for v in MELEE_VARIANTS) == 44

DIG_TABLE = _r(1, 15)                      # delay 3; fill plays _r(15, 1)
DEATH_TABLE = _r(1, 23) + [24] * 60        # delay 2; 83 entries: 1-23 once, the corpse (24) for 60 entries
assert len(DEATH_TABLE) == 83


def timeline(block):
    """[(phase, updates), ...] for one pass of a block's review movie at carrier timing."""
    if block == "idle":
        return [(p, 1) for p in IDLE_TABLES["variant_a"]]
    if block == "celebrate":
        return [(p, 5) for p in CELEBRATE_TABLES["variant_b"] + CELEBRATE_TABLES["variant_a"]]
    if block == "sit":
        seq = SIT_TABLES["sit_down"] + SIT_TABLES["rest_a"] + SIT_TABLES["rest_b"] + SIT_TABLES["stand_up"]
        return [(p, 3) for p in seq]
    if block.startswith("melee_"):
        return [(p, 3) for v in MELEE_VARIANTS for p in v]
    if block == "dig":
        return [(p, 4) for p in DIG_TABLE]
    if block.startswith("death_"):
        return [(p, 3) for p in DEATH_TABLE]
    if block == "walk":
        # One phase per movement step, about 3 updates at the carrier's default speed. The
        # primary/x split on screen isn't pinned down here: shown as 2 updates on the primary and
        # 1 on the x halfway frame (see timeline_walk_with_x).
        return [(p, 3) for p in range(16)]
    raise KeyError(block)


def timeline_walk_with_x():
    """[(block, phase, updates)]: each walk phase for 2 updates, then its x alternate for 1."""
    out = []
    for p in range(16):
        out += [("walk", p, 2), ("walk_x", p, 1)]
    return out
