from __future__ import annotations

from enum import IntFlag
from typing import List

from .models import DifficultyValues


class Mod(IntFlag):
    NO_FAIL = 1 << 0
    EASY = 1 << 1
    TOUCH_DEVICE = 1 << 2
    HIDDEN = 1 << 3
    HARD_ROCK = 1 << 4
    SUDDEN_DEATH = 1 << 5
    DOUBLE_TIME = 1 << 6
    RELAX = 1 << 7
    HALF_TIME = 1 << 8
    NIGHTCORE = 1 << 9
    FLASHLIGHT = 1 << 10
    AUTOPLAY = 1 << 11
    SPUN_OUT = 1 << 12
    AUTOPILOT = 1 << 13
    PERFECT = 1 << 14
    FADE_IN = 1 << 20
    RANDOM = 1 << 21
    CINEMA = 1 << 22
    TARGET = 1 << 23
    SCORE_V2 = 1 << 29
    MIRROR = 1 << 30


SHORT_NAMES = {
    Mod.NO_FAIL: "NF",
    Mod.EASY: "EZ",
    Mod.HIDDEN: "HD",
    Mod.HARD_ROCK: "HR",
    Mod.SUDDEN_DEATH: "SD",
    Mod.DOUBLE_TIME: "DT",
    Mod.NIGHTCORE: "NC",
    Mod.HALF_TIME: "HT",
    Mod.FLASHLIGHT: "FL",
    Mod.RELAX: "RX",
    Mod.AUTOPLAY: "AU",
    Mod.PERFECT: "PF",
    Mod.FADE_IN: "FI",
    Mod.MIRROR: "MR",
}


def has_mod(mods: int, mod: Mod) -> bool:
    return bool(Mod(mods) & mod)


def clock_rate_from_mods(mods: int) -> float:
    mod_bits = Mod(mods)
    if mod_bits & (Mod.DOUBLE_TIME | Mod.NIGHTCORE):
        return 1.5
    if mod_bits & Mod.HALF_TIME:
        return 0.75
    return 1.0


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def ar_to_preempt_ms(ar: float) -> float:
    if ar < 5.0:
        return 1800.0 - 120.0 * ar
    return 1200.0 - 150.0 * (ar - 5.0)


def apply_difficulty_mods(ar: float, od: float, cs: float, hp: float, mods: int) -> DifficultyValues:
    mod_bits = Mod(mods)

    if mod_bits & Mod.EASY:
        ar *= 0.5
        od *= 0.5
        cs *= 0.5
        hp *= 0.5

    if mod_bits & Mod.HARD_ROCK:
        ar *= 1.4
        od *= 1.4
        cs *= 1.3
        hp *= 1.4

    ar = _clamp(ar, 0.0, 10.0)
    od = _clamp(od, 0.0, 10.0)
    cs = _clamp(cs, 0.0, 10.0)
    hp = _clamp(hp, 0.0, 10.0)

    clock_rate = clock_rate_from_mods(mods)
    preempt_ms = ar_to_preempt_ms(ar) / clock_rate

    return DifficultyValues(
        ar=ar,
        od=od,
        cs=cs,
        hp=hp,
        preempt_ms=preempt_ms,
        clock_rate=clock_rate,
    )


def mods_to_short_names(mods: int) -> List[str]:
    if mods == 0:
        return ["NM"]

    mod_bits = Mod(mods)
    names: List[str] = []

    for mod in [
        Mod.NO_FAIL,
        Mod.EASY,
        Mod.HIDDEN,
        Mod.HARD_ROCK,
        Mod.SUDDEN_DEATH,
        Mod.DOUBLE_TIME,
        Mod.NIGHTCORE,
        Mod.HALF_TIME,
        Mod.FLASHLIGHT,
        Mod.RELAX,
        Mod.AUTOPLAY,
        Mod.PERFECT,
        Mod.FADE_IN,
        Mod.MIRROR,
    ]:
        if mod_bits & mod:
            names.append(SHORT_NAMES[mod])

    if not names:
        names.append("NM")

    return names
