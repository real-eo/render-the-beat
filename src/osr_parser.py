from __future__ import annotations

import lzma
import struct
from pathlib import Path
from typing import List

from .models import ReplayFrame, ReplayInfo


class _BinaryReader:
    def __init__(self, data: bytes) -> None:
        self._data = data
        self._offset = 0

    @property
    def remaining(self) -> int:
        return len(self._data) - self._offset

    def _read(self, size: int) -> bytes:
        if self._offset + size > len(self._data):
            raise ValueError("Unexpected end of .osr file")
        chunk = self._data[self._offset : self._offset + size]
        self._offset += size
        return chunk

    def _unpack(self, fmt: str) -> int:
        size = struct.calcsize(fmt)
        return struct.unpack(fmt, self._read(size))[0]

    def read_u8(self) -> int:
        return self._unpack("<B")

    def read_i16(self) -> int:
        return self._unpack("<h")

    def read_i32(self) -> int:
        return self._unpack("<i")

    def read_i64(self) -> int:
        return self._unpack("<q")

    def read_string(self) -> str:
        marker = self.read_u8()
        if marker == 0x00:
            return ""
        if marker != 0x0B:
            raise ValueError(f"Invalid osu! string marker: {marker}")

        length = 0
        shift = 0
        while True:
            byte = self.read_u8()
            length |= (byte & 0x7F) << shift
            if (byte & 0x80) == 0:
                break
            shift += 7

        return self._read(length).decode("utf-8", errors="replace")



def _parse_replay_frames(replay_data: bytes) -> List[ReplayFrame]:
    if not replay_data:
        return []

    try:
        text = lzma.decompress(replay_data).decode("utf-8", errors="replace")
    except lzma.LZMAError:
        return []

    frames: List[ReplayFrame] = []
    current_time = 0

    for entry in text.strip(",").split(","):
        if not entry:
            continue

        parts = entry.split("|")
        if len(parts) < 4:
            continue

        try:
            delta = int(parts[0])
            x = float(parts[1])
            y = float(parts[2])
            keys = int(parts[3])
        except ValueError:
            continue

        # Sentinel frame used by osu! for RNG seed in some contexts.
        if delta == -12345:
            continue

        current_time += delta
        frames.append(ReplayFrame(time_ms=float(current_time), x=x, y=y, keys=keys))

    return frames



def parse_osr(path: Path) -> ReplayInfo:
    data = path.read_bytes()
    reader = _BinaryReader(data)

    mode = reader.read_u8()
    version = reader.read_i32()
    beatmap_hash = reader.read_string()
    username = reader.read_string()
    replay_hash = reader.read_string()
    count_300 = reader.read_i16()
    count_100 = reader.read_i16()
    count_50 = reader.read_i16()
    count_geki = reader.read_i16()
    count_katu = reader.read_i16()
    count_miss = reader.read_i16()
    score = reader.read_i32()
    max_combo = reader.read_i16()
    perfect_combo = bool(reader.read_u8())
    mods = reader.read_i32()
    life_bar_graph = reader.read_string()
    timestamp_ticks = reader.read_i64()

    replay_length = reader.read_i32()
    replay_data = reader._read(replay_length) if replay_length > 0 else b""

    online_score_id = reader.read_i64() if reader.remaining >= 8 else 0

    return ReplayInfo(
        mode=mode,
        version=version,
        beatmap_hash=beatmap_hash,
        username=username,
        replay_hash=replay_hash,
        count_300=count_300,
        count_100=count_100,
        count_50=count_50,
        count_geki=count_geki,
        count_katu=count_katu,
        count_miss=count_miss,
        score=score,
        max_combo=max_combo,
        perfect_combo=perfect_combo,
        mods=mods,
        life_bar_graph=life_bar_graph,
        timestamp_ticks=timestamp_ticks,
        online_score_id=online_score_id,
        frames=_parse_replay_frames(replay_data),
    )
