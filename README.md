> [!WARNING]
> The project is currently heavily WIP

# Render the beat
_Render the beat_ is a hobby project which aims to render `.osr` files played in osu!ctb into video. 

## For contributers
> [!IMPORTANT]
> Contributions are welcomed.

I want to release v1.0.0 with C++ for processing, and general backend, and Python as a higher level interface for non-preforamce critical tasks


## Features

- Mod-aware timing and difficulty handling (`EZ`, `HR`, `DT`/`NC`, `HT`, `HD`, `FL`)
- Skin support (sprite + color + font fallbacks)
- Gameplay HUD and simulated catcher/object interaction
- End result screen with replay score breakdown


## Install

```bash
pip install -r requirements.txt
```

## Usage

### 1) Replay + explicit beatmap

```bash
python main.py --replay "path/to/replay.osr" --beatmap "path/to/beatmap.osu" --output out/render.mp4
```

### 2) Replay + Songs directory hash lookup

```bash
python main.py --replay "path/to/replay.osr" --songs-dir "C:/Users/<you>/AppData/Local/osu!/Songs" --output out/render.mp4
```

### 3) With a skin

```bash
python main.py --replay "path/to/replay.osr" --beatmap "path/to/beatmap.osu" --skin "path/to/skin" --fps 60 --width 1920 --height 1080
```

## Notes

- Beatmap discovery requires the matching `.osu` file (provided directly or found by hash in Songs).
- Slider conversion is approximated as of now.

