from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


@dataclass(frozen=True)
class ReplayFrame:
    time_ms: float
    x: float
    y: float
    keys: int


@dataclass
class ReplayInfo:
    mode: int
    version: int
    beatmap_hash: str
    username: str
    replay_hash: str
    count_300: int
    count_100: int
    count_50: int
    count_geki: int
    count_katu: int
    count_miss: int
    score: int
    max_combo: int
    perfect_combo: bool
    mods: int
    life_bar_graph: str
    timestamp_ticks: int
    online_score_id: int
    frames: List[ReplayFrame] = field(default_factory=list)


@dataclass(frozen=True)
class TimingPoint:
    time_ms: float
    beat_length: float
    uninherited: bool


@dataclass(frozen=True)
class CatchObject:
    time_ms: float
    x: float
    kind: str
    radius: float


@dataclass
class DifficultyValues:
    ar: float
    od: float
    cs: float
    hp: float
    preempt_ms: float
    clock_rate: float


@dataclass
class BeatmapData:
    path: Path
    mode: int
    audio_filename: str
    title: str
    artist: str
    version: str
    creator: str
    background_filename: Optional[str]
    timing_points: List[TimingPoint]
    objects: List[CatchObject]
    difficulty: DifficultyValues
