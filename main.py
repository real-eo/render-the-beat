from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path
from typing import Optional

from src import RenderOptions, load_skin, parse_beatmap, parse_osr, render_replay_video
from src.mods import mods_to_short_names


def _hash_file_md5(path: Path) -> str:
	digest = hashlib.md5()
	with path.open("rb") as file_handle:
		while True:
			chunk = file_handle.read(1024 * 1024)
			if not chunk:
				break
			digest.update(chunk)
	return digest.hexdigest()


def _find_beatmap_by_hash(songs_dir: Path, beatmap_hash: str) -> Optional[Path]:
	target_hash = beatmap_hash.lower().strip()
	if not target_hash:
		return None

	if not songs_dir.exists() or not songs_dir.is_dir():
		return None

	for beatmap_file in songs_dir.rglob("*.osu"):
		try:
			candidate_hash = _hash_file_md5(beatmap_file)
		except OSError:
			continue
		if candidate_hash.lower() == target_hash:
			return beatmap_file

	return None


def _infer_beatmap_argument(replay_path: Path, explicit_beatmap: Optional[Path]) -> Optional[Path]:
	if explicit_beatmap is not None:
		return explicit_beatmap

	local_osu_files = list(replay_path.parent.glob("*.osu"))
	if len(local_osu_files) == 1:
		return local_osu_files[0]

	return None


def _build_parser() -> argparse.ArgumentParser:
	parser = argparse.ArgumentParser(
		description=(
			"Render an osu!catch replay (.osr) to video with skin assets, mod-aware timing, and result screen."
		)
	)
	parser.add_argument("--replay", required=True, type=Path, help="Path to the .osr replay file")
	parser.add_argument("--beatmap", type=Path, help="Path to the matching .osu beatmap file")
	parser.add_argument(
		"--songs-dir",
		type=Path,
		help="Path to osu!/Songs for beatmap hash lookup when --beatmap is not supplied",
	)
	parser.add_argument("--skin", type=Path, help="Path to an osu! skin folder")
	parser.add_argument("--output", type=Path, default=Path("out/render.mp4"), help="Output mp4 path")
	parser.add_argument("--fps", type=int, default=60, help="Frames per second")
	parser.add_argument("--width", type=int, default=1280, help="Output width")
	parser.add_argument("--height", type=int, default=720, help="Output height")
	parser.add_argument(
		"--no-results",
		action="store_true",
		help="Skip the result screen and stop after gameplay",
	)
	parser.add_argument(
		"--results-ms",
		type=float,
		default=4500.0,
		help="Result screen duration in milliseconds",
	)
	return parser


def main() -> int:
	parser = _build_parser()
	args = parser.parse_args()

	replay_path: Path = args.replay
	if not replay_path.exists() or not replay_path.is_file():
		print(f"Replay file not found: {replay_path}")
		return 1

	replay = parse_osr(replay_path)
	if replay.mode != 2:
		print(
			f"Replay mode is {replay.mode}, but this renderer currently supports osu!catch only (mode 2)."
		)
		return 1

	beatmap_path = _infer_beatmap_argument(replay_path, args.beatmap)
	if beatmap_path is None and args.songs_dir is not None:
		print("Searching Songs directory for beatmap hash match...")
		beatmap_path = _find_beatmap_by_hash(args.songs_dir, replay.beatmap_hash)

	if beatmap_path is None:
		print("Unable to locate beatmap. Provide --beatmap or --songs-dir.")
		return 1

	if not beatmap_path.exists() or not beatmap_path.is_file():
		print(f"Beatmap file not found: {beatmap_path}")
		return 1

	beatmap = parse_beatmap(beatmap_path, mods=replay.mods)
	if beatmap.mode == 0:
		print(f"Converts temporarily disabled until we can verify correct conversion of osu!standard")
		return 1
	if beatmap.mode != 2:
		print(f"Beatmap mode is {beatmap.mode}, expected osu!catch mode (2)") # or osu!standard mode (0).") 	# <-- Temporarily disable osu!standard support until we can verify correct handling
		return 1

	mods_text = "".join(mods_to_short_names(replay.mods))
	print(f"Loaded replay by {replay.username} | Mods: {mods_text}")
	print(f"Beatmap: {beatmap.artist} - {beatmap.title} [{beatmap.version}] by {beatmap.creator}")

	skin = load_skin(args.skin)
	render_options = RenderOptions(
		width=args.width,
		height=args.height,
		fps=max(1, args.fps),
		show_results=not args.no_results,
		results_duration_ms=max(0.0, args.results_ms),
		output_path=args.output,
	)

	try:
		output_path = render_replay_video(beatmap=beatmap, replay=replay, skin=skin, options=render_options)
	except Exception as exc:  # pylint: disable=broad-except
		print(f"Rendering failed: {exc}")
		return 1

	print(f"Render complete: {output_path}")
	return 0


if __name__ == "__main__":
	sys.exit(main())
