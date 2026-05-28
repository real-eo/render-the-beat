from __future__ import annotations

import configparser
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PIL import Image, ImageFont

Color = Tuple[int, int, int]


@dataclass
class Skin:
    root: Optional[Path]
    combo_colors: List[Color]
    background_top: Color
    background_bottom: Color
    playfield_color: Color
    hud_text_color: Color
    catcher_color: Color
    fruit_color: Color
    droplet_color: Color
    banana_color: Color
    catcher_sprite: Optional[Image.Image] = None
    fruit_sprite: Optional[Image.Image] = None
    droplet_sprite: Optional[Image.Image] = None
    banana_sprite: Optional[Image.Image] = None
    result_panel_sprite: Optional[Image.Image] = None
    _font_path: Optional[Path] = None
    _font_cache: Dict[int, ImageFont.FreeTypeFont] = field(default_factory=dict)

    def get_font(self, size: int) -> ImageFont.ImageFont:
        if self._font_path is None:
            return ImageFont.load_default()

        cached = self._font_cache.get(size)
        if cached is not None:
            return cached

        try:
            font = ImageFont.truetype(str(self._font_path), size=size)
        except OSError:
            return ImageFont.load_default()

        self._font_cache[size] = font
        return font



def _parse_color(raw: Optional[str], fallback: Color) -> Color:
    if not raw:
        return fallback

    parts = [part.strip() for part in raw.split(",")]
    if len(parts) < 3:
        return fallback

    try:
        red = max(0, min(255, int(parts[0])))
        green = max(0, min(255, int(parts[1])))
        blue = max(0, min(255, int(parts[2])))
    except ValueError:
        return fallback

    return red, green, blue


def _load_first_existing(root: Path, candidates: List[str]) -> Optional[Image.Image]:
    for candidate in candidates:
        candidate_path = root / candidate
        if candidate_path.exists() and candidate_path.is_file():
            try:
                return Image.open(candidate_path).convert("RGBA")
            except OSError:
                continue
    return None


def load_skin(skin_path: Optional[Path]) -> Skin:
    defaults = Skin(
        root=None,
        combo_colors=[(255, 153, 84), (96, 204, 145), (98, 164, 255), (255, 218, 94)],
        background_top=(14, 24, 38),
        background_bottom=(8, 10, 18),
        playfield_color=(32, 40, 55),
        hud_text_color=(240, 240, 240),
        catcher_color=(255, 214, 130),
        fruit_color=(255, 132, 98),
        droplet_color=(124, 206, 255),
        banana_color=(255, 231, 103),
    )

    if skin_path is None:
        return defaults

    if not skin_path.exists() or not skin_path.is_dir():
        return defaults

    config = configparser.ConfigParser()
    ini_path = skin_path / "skin.ini"
    if ini_path.exists():
        try:
            config.read(ini_path, encoding="utf-8")
        except UnicodeDecodeError:
            config.read(ini_path, encoding="cp932")

    colours = config["Colours"] if "Colours" in config else {}

    combo_colors: List[Color] = []
    for index in range(1, 9):
        key = f"Combo{index}"
        value = colours.get(key)
        if value:
            combo_colors.append(_parse_color(value, defaults.combo_colors[(index - 1) % len(defaults.combo_colors)]))

    if not combo_colors:
        combo_colors = defaults.combo_colors

    font_path: Optional[Path] = None
    for candidate in ["default.ttf", "aller.ttf", "score.ttf", "main.ttf"]:
        possible = skin_path / candidate
        if possible.exists() and possible.is_file():
            font_path = possible
            break

    skin = Skin(
        root=skin_path,
        combo_colors=combo_colors,
        background_top=_parse_color(colours.get("MenuGlow"), defaults.background_top),
        background_bottom=_parse_color(colours.get("SliderBorder"), defaults.background_bottom),
        playfield_color=_parse_color(colours.get("InputOverlayText"), defaults.playfield_color),
        hud_text_color=_parse_color(colours.get("SongSelectActiveText"), defaults.hud_text_color),
        catcher_color=_parse_color(colours.get("Combo1"), defaults.catcher_color),
        fruit_color=_parse_color(colours.get("Combo2"), defaults.fruit_color),
        droplet_color=_parse_color(colours.get("Combo3"), defaults.droplet_color),
        banana_color=_parse_color(colours.get("Combo4"), defaults.banana_color),
        catcher_sprite=_load_first_existing(
            skin_path,
            ["fruit-catcher-idle.png", "fruit-catcher.png", "catcher-idle.png", "catcher.png"],
        ),
        fruit_sprite=_load_first_existing(skin_path, ["fruit-apple.png", "fruit-orange.png", "fruit.png"]),
        droplet_sprite=_load_first_existing(skin_path, ["fruit-drop.png", "droplet.png"]),
        banana_sprite=_load_first_existing(skin_path, ["banana.png", "spinner-rpm.png"]),
        result_panel_sprite=_load_first_existing(skin_path, ["ranking-panel.png", "result-panel.png"]),
        _font_path=font_path,
    )

    return skin
