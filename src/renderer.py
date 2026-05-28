from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

import imageio.v2 as imageio
import numpy as np
from PIL import Image, ImageDraw, ImageEnhance

from .models import BeatmapData, CatchObject, ReplayFrame, ReplayInfo
from .mods import Mod, has_mod, mods_to_short_names
from .skin import Skin


@dataclass
class RenderOptions:
    width: int = 1280
    height: int = 720
    fps: int = 60
    show_results: bool = True
    results_duration_ms: float = 4500.0
    output_path: Path = Path("out/render.mp4")


@dataclass
class _ScoreState:
    score: int = 0
    combo: int = 0
    max_combo: int = 0
    misses: int = 0


_RESAMPLE = Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS


class CatchReplayRenderer:
    def __init__(self, beatmap: BeatmapData, replay: ReplayInfo, skin: Skin, options: RenderOptions) -> None:
        self.beatmap = beatmap
        self.replay = replay
        self.skin = skin
        self.options = options

        self.playfield_left = int(self.options.width * 0.28)
        self.playfield_right = int(self.options.width * 0.72)
        self.playfield_top = int(self.options.height * 0.08)
        self.playfield_bottom = int(self.options.height * 0.9)
        self.catcher_y = int(self.playfield_bottom - self.options.height * 0.11)

        self.playfield_width = max(1, self.playfield_right - self.playfield_left)
        self.playfield_height = max(1, self.catcher_y - self.playfield_top)

        cs = self.beatmap.difficulty.cs
        self.catcher_half_world = max(22.0, min(70.0, 44.0 * (1.0 + (5.0 - cs) * 0.08)))

        self.object_states: List[Optional[bool]] = [None] * len(self.beatmap.objects)
        self.score_state = _ScoreState()

        self.frame_replay_index = 0
        self.judge_replay_index = 0
        self.resolve_index = 0
        self.visible_start = 0
        self.visible_end = 0

        self.background = self._build_background()

    def render(self) -> Path:
        objects = self.beatmap.objects
        replay_frames = self.replay.frames

        gameplay_end = 2000.0
        if objects:
            gameplay_end = max(gameplay_end, objects[-1].time_ms + 1600.0)
        if replay_frames:
            gameplay_end = max(gameplay_end, replay_frames[-1].time_ms + 1200.0)

        total_duration = gameplay_end
        if self.options.show_results:
            total_duration += self.options.results_duration_ms

        frame_count = int(total_duration * self.options.fps / 1000.0) + 1
        mods_text = "".join(mods_to_short_names(self.replay.mods))

        self.options.output_path.parent.mkdir(parents=True, exist_ok=True)

        with imageio.get_writer(
            str(self.options.output_path),
            fps=self.options.fps,
            codec="libx264",
            pixelformat="yuv420p",
            quality=8,
        ) as writer:
            for frame_index in range(frame_count):
                time_ms = frame_index * 1000.0 / self.options.fps

                if time_ms <= gameplay_end:
                    frame = self._render_gameplay_frame(time_ms, mods_text)
                else:
                    frame = self._render_results_frame(time_ms - gameplay_end, mods_text)

                writer.append_data(np.asarray(frame.convert("RGB"), dtype=np.uint8))

        return self.options.output_path

    def _build_background(self) -> Image.Image:
        base = Image.new("RGBA", (self.options.width, self.options.height), (0, 0, 0, 255))
        draw = ImageDraw.Draw(base)

        top = self.skin.background_top
        bottom = self.skin.background_bottom

        for y in range(self.options.height):
            ratio = y / max(1, self.options.height - 1)
            red = int(top[0] * (1.0 - ratio) + bottom[0] * ratio)
            green = int(top[1] * (1.0 - ratio) + bottom[1] * ratio)
            blue = int(top[2] * (1.0 - ratio) + bottom[2] * ratio)
            draw.line([(0, y), (self.options.width, y)], fill=(red, green, blue, 255))

        background_path = None
        if self.beatmap.background_filename:
            possible = self.beatmap.path.parent / self.beatmap.background_filename
            if possible.exists() and possible.is_file():
                background_path = possible

        if background_path is not None:
            try:
                image = Image.open(background_path).convert("RGBA")
                image = self._fit_cover(image, (self.options.width, self.options.height))
                image = ImageEnhance.Brightness(image).enhance(0.48)
                image = ImageEnhance.Contrast(image).enhance(0.9)
                base = Image.blend(base, image, alpha=0.4)
            except OSError:
                pass

        vignette = Image.new("RGBA", (self.options.width, self.options.height), (0, 0, 0, 0))
        vignette_draw = ImageDraw.Draw(vignette)
        vignette_draw.rectangle(
            [(0, 0), (self.options.width, self.options.height)],
            fill=(0, 0, 0, 65),
        )
        base.alpha_composite(vignette)

        return base

    def _fit_cover(self, image: Image.Image, size: Tuple[int, int]) -> Image.Image:
        target_w, target_h = size
        src_w, src_h = image.size
        scale = max(target_w / src_w, target_h / src_h)
        resized = image.resize((int(src_w * scale), int(src_h * scale)), _RESAMPLE)

        left = (resized.width - target_w) // 2
        top = (resized.height - target_h) // 2
        return resized.crop((left, top, left + target_w, top + target_h))

    def _render_gameplay_frame(self, time_ms: float, mods_text: str) -> Image.Image:
        frame = self.background.copy()
        draw = ImageDraw.Draw(frame, "RGBA")

        self._draw_playfield(frame, draw)

        catcher_x_world, self.frame_replay_index = self._interpolate_replay_x(
            self.replay.frames, time_ms, self.frame_replay_index
        )
        catcher_x_px = self._to_screen_x(catcher_x_world)

        self._resolve_objects_until(time_ms)
        self._draw_objects(frame, draw, time_ms)
        self._draw_catcher(frame, draw, catcher_x_px)

        if has_mod(self.replay.mods, Mod.FLASHLIGHT):
            self._draw_flashlight(frame, catcher_x_px)

        self._draw_hud(draw, time_ms, mods_text)
        return frame

    def _draw_playfield(self, frame: Image.Image, draw: ImageDraw.ImageDraw) -> None:
        field_fill = (*self.skin.playfield_color, 70)
        draw.rounded_rectangle(
            [(self.playfield_left, self.playfield_top), (self.playfield_right, self.playfield_bottom)],
            radius=24,
            fill=field_fill,
            outline=(255, 255, 255, 90),
            width=2,
        )

        draw.line(
            [(self.playfield_left, self.catcher_y), (self.playfield_right, self.catcher_y)],
            fill=(255, 255, 255, 130),
            width=2,
        )

        overlay = Image.new("RGBA", (self.options.width, self.options.height), (0, 0, 0, 0))
        overlay_draw = ImageDraw.Draw(overlay, "RGBA")
        overlay_draw.rounded_rectangle(
            [(self.playfield_left, self.playfield_top), (self.playfield_right, self.playfield_bottom)],
            radius=24,
            fill=(255, 255, 255, 12),
        )
        frame.alpha_composite(overlay)

    def _draw_objects(self, frame: Image.Image, draw: ImageDraw.ImageDraw, time_ms: float) -> None:
        preempt = self.beatmap.difficulty.preempt_ms
        objects = self.beatmap.objects

        while self.visible_start < len(objects) and objects[self.visible_start].time_ms < time_ms - 260.0:
            self.visible_start += 1

        while self.visible_end < len(objects) and objects[self.visible_end].time_ms - preempt <= time_ms + 16.0:
            self.visible_end += 1

        for index in range(self.visible_start, self.visible_end):
            obj = objects[index]
            spawn_time = obj.time_ms - preempt
            life_progress = (time_ms - spawn_time) / max(1.0, preempt)
            y_px = self.playfield_top + life_progress * self.playfield_height

            if y_px < self.playfield_top - 40 or y_px > self.playfield_bottom + 40:
                continue

            alpha = 1.0
            if has_mod(self.replay.mods, Mod.HIDDEN):
                fade_start = obj.time_ms - preempt * 0.58
                fade_end = obj.time_ms - preempt * 0.12
                if time_ms >= fade_start:
                    alpha = max(0.0, min(1.0, 1.0 - (time_ms - fade_start) / max(1.0, fade_end - fade_start)))

            state = self.object_states[index]
            missed = state is False and time_ms <= obj.time_ms + 180.0
            if missed:
                alpha = max(alpha, 0.2)

            self._draw_single_object(frame, draw, obj, y_px, alpha, missed)

    def _draw_single_object(
        self,
        frame: Image.Image,
        draw: ImageDraw.ImageDraw,
        obj: CatchObject,
        y_px: float,
        alpha: float,
        missed: bool,
    ) -> None:
        x_px = self._to_screen_x(obj.x)
        base_radius = int(obj.radius * (self.playfield_width / 512.0))
        radius = max(3, base_radius)

        sprite = None
        if obj.kind == "fruit":
            sprite = self.skin.fruit_sprite
            fallback = self.skin.fruit_color
        elif obj.kind == "droplet":
            sprite = self.skin.droplet_sprite
            fallback = self.skin.droplet_color
        elif obj.kind == "tiny_droplet":
            sprite = self.skin.droplet_sprite
            fallback = self.skin.droplet_color
            radius = max(2, int(obj.radius))
        else:
            sprite = self.skin.banana_sprite
            fallback = self.skin.banana_color

        if missed:
            fallback = (255, 85, 85)

        if sprite is not None:
            size = radius * 2
            sprite_frame = sprite.resize((size, size), _RESAMPLE)
            if alpha < 0.999:
                sprite_frame = sprite_frame.copy()
                sprite_alpha = sprite_frame.getchannel("A")
                sprite_alpha = sprite_alpha.point(lambda value: int(value * alpha))
                sprite_frame.putalpha(sprite_alpha)
            frame.alpha_composite(sprite_frame, (int(x_px - radius), int(y_px - radius)))
        else:
            fill = (*fallback, int(255 * alpha))
            outline = (255, 255, 255, int(180 * alpha))
            draw.ellipse(
                [(x_px - radius, y_px - radius), (x_px + radius, y_px + radius)],
                fill=fill,
                outline=outline,
                width=2,
            )

    def _draw_catcher(self, frame: Image.Image, draw: ImageDraw.ImageDraw, catcher_x: int) -> None:
        half_width = int(self.catcher_half_world / 512.0 * self.playfield_width)
        width = max(24, half_width * 2)
        height = max(12, int(width * 0.28))

        if self.skin.catcher_sprite is not None:
            sprite = self.skin.catcher_sprite.resize((width, int(height * 2.2)), _RESAMPLE)
            frame.alpha_composite(sprite, (catcher_x - width // 2, self.catcher_y - sprite.height + 6))
        else:
            draw.rounded_rectangle(
                [(catcher_x - width // 2, self.catcher_y - height), (catcher_x + width // 2, self.catcher_y + 4)],
                radius=10,
                fill=(*self.skin.catcher_color, 240),
                outline=(255, 255, 255, 190),
                width=2,
            )

    def _draw_flashlight(self, frame: Image.Image, catcher_x: int) -> None:
        radius = int(max(100, self.playfield_width * 0.23))

        mask = Image.new("L", (self.options.width, self.options.height), 185)
        mask_draw = ImageDraw.Draw(mask)
        mask_draw.ellipse(
            [(catcher_x - radius, self.catcher_y - radius), (catcher_x + radius, self.catcher_y + radius)],
            fill=0,
        )

        overlay = Image.new("RGBA", (self.options.width, self.options.height), (0, 0, 0, 0))
        overlay.putalpha(mask)
        frame.alpha_composite(overlay)

    def _draw_hud(self, draw: ImageDraw.ImageDraw, time_ms: float, mods_text: str) -> None:
        primary_font = self.skin.get_font(30)
        secondary_font = self.skin.get_font(22)

        color = self.skin.hud_text_color

        draw.text((30, 20), f"{self.score_state.score:08d}", fill=color, font=primary_font)
        draw.text((30, 58), f"Combo x{self.score_state.combo}", fill=color, font=secondary_font)
        draw.text((30, 88), f"Max x{self.score_state.max_combo}", fill=color, font=secondary_font)

        draw.text((self.options.width - 240, 20), f"Mods: {mods_text}", fill=color, font=secondary_font)
        draw.text(
            (self.options.width - 240, 52),
            f"Time: {time_ms / 1000.0:06.2f}s",
            fill=color,
            font=secondary_font,
        )

        draw.text(
            (30, self.options.height - 42),
            f"{self.beatmap.artist} - {self.beatmap.title} [{self.beatmap.version}]",
            fill=color,
            font=secondary_font,
        )

    def _render_results_frame(self, result_time_ms: float, mods_text: str) -> Image.Image:
        frame = self.background.copy()
        draw = ImageDraw.Draw(frame, "RGBA")

        fade = min(1.0, result_time_ms / 600.0)
        panel_alpha = int(180 * fade)
        draw.rectangle(
            [(0, 0), (self.options.width, self.options.height)],
            fill=(4, 6, 10, panel_alpha),
        )

        panel_w = int(self.options.width * 0.72)
        panel_h = int(self.options.height * 0.68)
        panel_x = (self.options.width - panel_w) // 2
        panel_y = int(self.options.height * 0.16)

        if self.skin.result_panel_sprite is not None:
            panel = self.skin.result_panel_sprite.resize((panel_w, panel_h), _RESAMPLE)
            frame.alpha_composite(panel, (panel_x, panel_y))
        else:
            draw.rounded_rectangle(
                [(panel_x, panel_y), (panel_x + panel_w, panel_y + panel_h)],
                radius=28,
                fill=(20, 28, 40, int(220 * fade)),
                outline=(255, 255, 255, int(120 * fade)),
                width=2,
            )

        acc = self._calculate_accuracy()
        grade = self._grade(acc)

        title_font = self.skin.get_font(42)
        heading_font = self.skin.get_font(30)
        body_font = self.skin.get_font(24)

        text_color = self.skin.hud_text_color
        score_left = panel_x + 48
        score_top = panel_y + 38

        draw.text((score_left, score_top), "Results", fill=text_color, font=title_font)
        draw.text(
            (score_left, score_top + 58),
            f"Player: {self.replay.username}",
            fill=text_color,
            font=body_font,
        )
        draw.text(
            (score_left, score_top + 92),
            f"{self.beatmap.artist} - {self.beatmap.title} [{self.beatmap.version}]",
            fill=text_color,
            font=body_font,
        )

        draw.text((score_left, score_top + 150), f"Score: {self.replay.score}", fill=text_color, font=heading_font)
        draw.text(
            (score_left, score_top + 194),
            f"Max Combo: x{self.replay.max_combo}",
            fill=text_color,
            font=heading_font,
        )
        draw.text((score_left, score_top + 238), f"Accuracy: {acc:.2f}%", fill=text_color, font=heading_font)
        draw.text((score_left, score_top + 282), f"Mods: {mods_text}", fill=text_color, font=heading_font)

        counts_x = panel_x + panel_w - 300
        counts_y = score_top + 148
        draw.text((counts_x, counts_y), f"300: {self.replay.count_300}", fill=text_color, font=body_font)
        draw.text((counts_x, counts_y + 34), f"100: {self.replay.count_100}", fill=text_color, font=body_font)
        draw.text((counts_x, counts_y + 68), f"50: {self.replay.count_50}", fill=text_color, font=body_font)
        draw.text((counts_x, counts_y + 102), f"Miss: {self.replay.count_miss}", fill=text_color, font=body_font)

        grade_font = self.skin.get_font(92)
        draw.text((panel_x + panel_w - 200, panel_y + 36), grade, fill=(255, 225, 130), font=grade_font)

        return frame

    def _calculate_accuracy(self) -> float:
        c300 = self.replay.count_300
        c100 = self.replay.count_100
        c50 = self.replay.count_50
        miss = self.replay.count_miss

        total = c300 + c100 + c50 + miss
        if total <= 0:
            return 0.0

        value = (300 * c300 + 100 * c100 + 50 * c50) / (300 * total)
        return value * 100.0

    def _grade(self, accuracy: float) -> str:
        if self.replay.count_miss == 0 and accuracy >= 100.0:
            return "SS"
        if self.replay.count_miss == 0 and accuracy >= 98.0:
            return "S"
        if accuracy >= 95.0:
            return "A"
        if accuracy >= 90.0:
            return "B"
        if accuracy >= 80.0:
            return "C"
        return "D"

    def _resolve_objects_until(self, time_ms: float) -> None:
        objects = self.beatmap.objects

        while self.resolve_index < len(objects) and objects[self.resolve_index].time_ms <= time_ms:
            obj = objects[self.resolve_index]
            catcher_x_world, self.judge_replay_index = self._interpolate_replay_x(
                self.replay.frames, obj.time_ms, self.judge_replay_index
            )

            catch_window = self.catcher_half_world + obj.radius * 0.72
            caught = abs(catcher_x_world - obj.x) <= catch_window

            self.object_states[self.resolve_index] = caught

            if caught:
                self.score_state.combo += 1
                self.score_state.max_combo = max(self.score_state.max_combo, self.score_state.combo)

                if obj.kind == "fruit":
                    self.score_state.score += 300 + self.score_state.combo // 4
                elif obj.kind == "droplet":
                    self.score_state.score += 100 + self.score_state.combo // 6
                else:
                    self.score_state.score += 110
            else:
                self.score_state.combo = 0
                self.score_state.misses += 1

            self.resolve_index += 1

    def _interpolate_replay_x(self, frames: List[ReplayFrame], time_ms: float, hint_index: int) -> Tuple[float, int]:
        if not frames:
            return 256.0, hint_index

        if len(frames) == 1:
            return max(0.0, min(512.0, frames[0].x)), hint_index

        index = max(0, min(hint_index, len(frames) - 2))

        while index < len(frames) - 2 and frames[index + 1].time_ms < time_ms:
            index += 1

        while index > 0 and frames[index].time_ms > time_ms:
            index -= 1

        left = frames[index]
        right = frames[index + 1]

        if right.time_ms <= left.time_ms:
            return max(0.0, min(512.0, left.x)), index

        ratio = (time_ms - left.time_ms) / (right.time_ms - left.time_ms)
        ratio = max(0.0, min(1.0, ratio))
        x = left.x + (right.x - left.x) * ratio

        return max(0.0, min(512.0, x)), index

    def _to_screen_x(self, world_x: float) -> int:
        return int(self.playfield_left + (world_x / 512.0) * self.playfield_width)


def render_replay_video(beatmap: BeatmapData, replay: ReplayInfo, skin: Skin, options: RenderOptions) -> Path:
    renderer = CatchReplayRenderer(beatmap=beatmap, replay=replay, skin=skin, options=options)
    return renderer.render()
