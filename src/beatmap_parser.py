from __future__ import annotations

import math
import re
import random
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from .models import BeatmapData, CatchObject, TimingPoint
from .mods import Mod, apply_difficulty_mods


_IMAGE_PATTERN = re.compile(r'"([^"]+\.(?:jpg|jpeg|png|bmp|webp))"', re.IGNORECASE)
_VERSION_PATTERN = re.compile(r"osu file format v(\d+)", re.IGNORECASE)

TAIL_LENIENCY = -36.0
BASE_SCORING_DISTANCE = 100.0


def _read_beatmap_text(path: Path) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp932", "latin-1"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError(f"Unable to decode beatmap file: {path}")


def _parse_beatmap_version(text: str) -> int:
    first_line = text.splitlines()[0].strip() if text else ""
    match = _VERSION_PATTERN.match(first_line)
    return int(match.group(1)) if match else 14


def _parse_key_value(lines: Iterable[str]) -> Dict[str, str]:
    values: Dict[str, str] = {}
    for line in lines:
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        values[key.strip()] = value.strip()
    return values


def _parse_timing_points(lines: Iterable[str]) -> List[TimingPoint]:
    points: List[TimingPoint] = []
    for line in lines:
        if not line or line.startswith("//"):
            continue
        parts = line.split(",")
        if len(parts) < 2:
            continue
        try:
            time_ms = float(parts[0])
            beat_length = float(parts[1])
            uninherited = len(parts) > 6 and parts[6].strip() == "1"
        except ValueError:
            continue
        points.append(TimingPoint(time_ms=time_ms, beat_length=beat_length, uninherited=uninherited))

    points.sort(key=lambda point: point.time_ms)
    return points


def _extract_background_filename(lines: Iterable[str]) -> Optional[str]:
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("//"):
            continue

        match = _IMAGE_PATTERN.search(line)
        if match:
            return match.group(1)

    return None


def _find_timing_state(timing_points: List[TimingPoint], object_time: float) -> Tuple[float, float]:
    base_beat_length = 500.0
    slider_velocity_multiplier = 1.0

    for point in timing_points:
        if point.time_ms > object_time:
            break
        if point.uninherited:
            base_beat_length = point.beat_length
        elif point.beat_length < 0:
            slider_velocity_multiplier = -100.0 / point.beat_length

    return base_beat_length, slider_velocity_multiplier


def _parse_slider_points(start_x: float, start_y: float, control_string: str) -> List[Tuple[float, float]]:
    points: List[Tuple[float, float]] = [(start_x, start_y)]

    segments = control_string.split("|")
    for segment in segments[1:]:
        if ":" not in segment:
            continue
        try:
            point_x_str, point_y_str = segment.split(":", 1)
            point_x = float(point_x_str)
            point_y = float(point_y_str)
        except ValueError:
            continue
        points.append((point_x, point_y))

    if len(points) == 1:
        points.append((start_x, start_y))

    return points


def _position_along_path(points: List[Tuple[float, float]], progress: float) -> Tuple[float, float]:
    if not points:
        return 0.0, 0.0

    if progress <= 0:
        return points[0]
    if progress >= 1:
        return points[-1]

    segment_lengths: List[float] = []
    total_length = 0.0

    for index in range(len(points) - 1):
        segment = math.dist(points[index], points[index + 1])
        segment_lengths.append(segment)
        total_length += segment

    if total_length <= 1e-6:
        return points[0]

    target = progress * total_length
    traversed = 0.0

    for index, segment in enumerate(segment_lengths):
        if traversed + segment >= target:
            local = (target - traversed) / segment if segment > 1e-6 else 0.0
            x1, y1 = points[index]
            x2, y2 = points[index + 1]
            return x1 + (x2 - x1) * local, y1 + (y2 - y1) * local
        traversed += segment

    return points[-1]


def _sample_path_x(points: List[Tuple[float, float]], progress: float) -> float:
    return _position_along_path(points, progress)[0]


def _generate_slider_events(
    start_time: float,
    span_duration: float,
    velocity: float,
    tick_distance: float,
    total_distance: float,
    span_count: int,
) -> List[Tuple[str, float, int, float, float]]:
    length = min(100000.0, max(0.0, total_distance))
    tick_distance = min(max(0.0, tick_distance), length)
    min_distance_from_end = velocity * 10.0

    events: List[Tuple[str, float, int, float, float]] = [("head", start_time, 0, start_time, 0.0)]

    def generate_ticks(span_index: int, span_start_time: float, reversed_span: bool) -> List[Tuple[str, float, int, float, float]]:
        if tick_distance == 0 or length <= 0:
            return []

        ticks: List[Tuple[str, float, int, float, float]] = []
        d = tick_distance

        while d <= length:
            if d >= length - min_distance_from_end:
                break

            path_progress = d / length
            time_progress = 1.0 - path_progress if reversed_span else path_progress
            ticks.append(("tick", span_start_time + time_progress * span_duration, span_index, span_start_time, path_progress))
            d += tick_distance

        return ticks

    for span in range(span_count):
        span_start_time = start_time + span * span_duration
        reversed_span = (span % 2) == 1

        ticks = generate_ticks(span, span_start_time, reversed_span)
        if reversed_span:
            ticks.reverse()
        events.extend(ticks)

        if span < span_count - 1:
            events.append(("repeat", span_start_time + span_duration, span, span_start_time, float((span + 1) % 2)))

    total_duration = span_count * span_duration
    final_span_index = span_count - 1
    final_span_start_time = start_time + final_span_index * span_duration

    legacy_last_tick_time = max(start_time + total_duration / 2.0, (final_span_start_time + span_duration) + TAIL_LENIENCY)
    if math.isclose(span_duration, 0.0):
        legacy_last_tick_progress = float(span_count % 2)
    else:
        legacy_last_tick_progress = (legacy_last_tick_time - final_span_start_time) / span_duration
        if span_count % 2 == 0:
            legacy_last_tick_progress = 1.0 - legacy_last_tick_progress

    events.append(("legacy_last_tick", legacy_last_tick_time, final_span_index, final_span_start_time, legacy_last_tick_progress))
    events.append(("tail", start_time + total_duration, final_span_index, final_span_start_time, float(span_count % 2)))
    return events


def _clamp_x(value: float) -> float:
    return max(0.0, min(512.0, value))


def _convert_hit_objects_to_catch(
    hit_object_lines: Iterable[str],
    timing_points: List[TimingPoint],
    slider_multiplier: float,
    slider_tick_rate: float,
    clock_rate: float,
    beatmap_version: int,
) -> List[CatchObject]:
    objects: List[CatchObject] = []
    banana_rng = random.Random(1337)

    for line in hit_object_lines:
        if not line or line.startswith("//"):
            continue

        parts = line.split(",")
        if len(parts) < 5:
            continue

        try:
            x = float(parts[0])
            start_time = float(parts[2]) / clock_rate
            object_type = int(parts[3])
        except ValueError:
            continue

        params = parts[5:]

        if object_type & 1:
            objects.append(CatchObject(time_ms=start_time, x=_clamp_x(x), kind="fruit", radius=17.0))
            continue

        if object_type & 2:
            if len(params) < 3:
                continue

            control_string = params[0]
            try:
                # In .osu files this value is the number of spans ("slides"), not repeat count.
                span_count = max(1, int(params[1]))
                pixel_length = max(0.0, float(params[2]))
            except ValueError:
                continue

            base_beat_length, sv_multiplier = _find_timing_state(timing_points, start_time * clock_rate)
            effective_sv = max(0.1, sv_multiplier)
            velocity = BASE_SCORING_DISTANCE * max(0.1, slider_multiplier) / base_beat_length
            span_duration = 0.0 if pixel_length <= 0 else pixel_length / max(0.0001, velocity * effective_sv) / clock_rate

            control_points = _parse_slider_points(x, 0.0, control_string)
            tick_distance_multiplier = 1.0 if beatmap_version >= 8 else 1.0 / effective_sv
            scoring_distance = BASE_SCORING_DISTANCE * max(0.1, slider_multiplier) * effective_sv
            tick_distance = scoring_distance / max(0.1, slider_tick_rate) * tick_distance_multiplier
            slider_events = _generate_slider_events(start_time, span_duration, velocity, tick_distance, pixel_length, span_count)

            last_event: Optional[Tuple[str, float, int, float, float]] = None
            for event_type, event_time, span_index, span_start_time, path_progress in slider_events:
                if last_event is not None:
                    since_last_tick = int(event_time) - int(last_event[1])
                    if since_last_tick > 80:
                        time_between_tiny = float(since_last_tick)
                        while time_between_tiny > 100:
                            time_between_tiny /= 2.0

                        t = time_between_tiny
                        while t < since_last_tick:
                            progress = last_event[4] + (t / since_last_tick) * (path_progress - last_event[4])
                            point_x = _sample_path_x(control_points, progress)
                            objects.append(
                                CatchObject(
                                    time_ms=last_event[1] + t,
                                    x=_clamp_x(point_x),
                                    kind="tiny_droplet",
                                    radius=8.0,
                                )
                            )
                            t += time_between_tiny

                if event_type == "tick":
                    point_x = _sample_path_x(control_points, path_progress)
                    objects.append(CatchObject(time_ms=event_time, x=_clamp_x(point_x), kind="droplet", radius=10.0))
                elif event_type in {"head", "repeat", "tail"}:
                    point_x = _sample_path_x(control_points, path_progress)
                    objects.append(CatchObject(time_ms=event_time, x=_clamp_x(point_x), kind="fruit", radius=17.0))

                last_event = (event_type, event_time, span_index, span_start_time, path_progress)

            continue

        if object_type & 8:
            if not params:
                continue

            try:
                end_time = float(params[0]) / clock_rate
            except ValueError:
                continue

            spacing = end_time - start_time
            while spacing > 100:
                spacing /= 2.0

            if spacing <= 0:
                continue

            banana_index = 0
            sample_time = int(start_time)
            end_time_int = int(end_time)

            while sample_time <= end_time_int:
                banana_x = banana_rng.random() * 512.0
                objects.append(
                    CatchObject(
                        time_ms=float(sample_time),
                        x=_clamp_x(banana_x),
                        kind="banana",
                        radius=12.0,
                    )
                )
                banana_index += 1
                banana_rng.random()
                banana_rng.random()
                sample_time = int(sample_time + spacing)

    objects.sort(key=lambda item: item.time_ms)
    return objects


def parse_beatmap(path: Path, mods: int) -> BeatmapData:
    text = _read_beatmap_text(path)
    beatmap_version = _parse_beatmap_version(text)

    sections: Dict[str, List[str]] = {}
    active_section = ""

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("[") and line.endswith("]"):
            active_section = line[1:-1].strip()
            sections.setdefault(active_section, [])
            continue

        if not line:
            continue

        sections.setdefault(active_section, []).append(line)

    general = _parse_key_value(sections.get("General", []))
    metadata = _parse_key_value(sections.get("Metadata", []))
    difficulty_section = _parse_key_value(sections.get("Difficulty", []))

    mode = int(general.get("Mode", "0"))
    hp = float(difficulty_section.get("HPDrainRate", "5"))
    cs = float(difficulty_section.get("CircleSize", "5"))
    od = float(difficulty_section.get("OverallDifficulty", "5"))
    ar = float(difficulty_section.get("ApproachRate", str(od)))
    slider_multiplier = float(difficulty_section.get("SliderMultiplier", "1.4"))
    slider_tick_rate = float(difficulty_section.get("SliderTickRate", "1"))

    difficulty = apply_difficulty_mods(ar=ar, od=od, cs=cs, hp=hp, mods=mods)
    timing_points = _parse_timing_points(sections.get("TimingPoints", []))
    objects = _convert_hit_objects_to_catch(
        sections.get("HitObjects", []),
        timing_points=timing_points,
        slider_multiplier=slider_multiplier,
        slider_tick_rate=slider_tick_rate,
        clock_rate=difficulty.clock_rate,
        beatmap_version=beatmap_version,
    )

    if Mod(mods) & Mod.MIRROR:
        objects = [
            CatchObject(time_ms=obj.time_ms, x=512.0 - obj.x, kind=obj.kind, radius=obj.radius)
            for obj in objects
        ]

    return BeatmapData(
        path=path,
        mode=mode,
        audio_filename=general.get("AudioFilename", ""),
        title=metadata.get("TitleUnicode") or metadata.get("Title", "Unknown Title"),
        artist=metadata.get("ArtistUnicode") or metadata.get("Artist", "Unknown Artist"),
        version=metadata.get("Version", "Unknown Difficulty"),
        creator=metadata.get("Creator", "Unknown Mapper"),
        background_filename=_extract_background_filename(sections.get("Events", [])),
        timing_points=timing_points,
        objects=objects,
        difficulty=difficulty,
    )