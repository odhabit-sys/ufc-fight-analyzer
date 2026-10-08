#!/usr/bin/env python3
"""UFC / MMA Fight Analyzer.

    python analyze.py videos/fight.mp4                     # auto-pick fighters
    python analyze.py videos/fight.mp4 --pick              # click the two fighters
    python analyze.py videos/fight.mp4 --start 30 --end 90 --names "SMITH" "JONES"

Stage 1 (pose extraction) is cached in output/, so re-running with different HUD
or scoring settings only redoes the fast stage 2.
"""
import argparse
import json
from pathlib import Path

from fight_analyzer.config import Config
from fight_analyzer.extract import extract, load_cache
from fight_analyzer.render import interactive_pick, render


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video")
    ap.add_argument("-o", "--out", help="output .mp4 (default output/<name>_analyzed.mp4)")
    ap.add_argument("--start", type=float, default=0.0, help="start time in seconds")
    ap.add_argument("--end", type=float, default=None, help="end time in seconds")
    ap.add_argument("--model", default=None, help="pose model, e.g. yolo11x-pose.pt")
    ap.add_argument("--imgsz", type=int, default=None)
    ap.add_argument("--device", default=None, help="mps | cpu")
    ap.add_argument("--names", nargs=2, default=["FIGHTER 1", "FIGHTER 2"])
    ap.add_argument("--layout", choices=["frame", "overlay"], default="frame",
                    help="frame = 1920x1080 HUD around the footage; overlay = HUD on top of it")
    ap.add_argument("--pick", action="store_true", help="click the two fighters yourself")
    ap.add_argument("--swap", action="store_true", help="swap which fighter is F1/F2")
    ap.add_argument("--preview", action="store_true", help="show a live preview window")
    ap.add_argument("--reextract", action="store_true", help="ignore cached pose data")
    args = ap.parse_args()

    cfg = Config()
    if args.model:
        cfg.pose_model = args.model
    if args.imgsz:
        cfg.imgsz = args.imgsz
    if args.device:
        cfg.device = args.device

    video = Path(args.video).resolve()
    outdir = Path(__file__).resolve().parent / "output"
    outdir.mkdir(exist_ok=True)
    rng = f"{args.start:g}-{'end' if args.end is None else f'{args.end:g}'}"
    stem = f"{video.stem}_{rng}"
    cache_path = outdir / f"{stem}_{Path(cfg.pose_model).stem}_{cfg.imgsz}.pose.pkl"
    pick_path = outdir / f"{stem}.pick.json"
    out_path = Path(args.out) if args.out else outdir / f"{video.stem}_analyzed.mp4"

    if cache_path.exists() and not args.reextract:
        print(f"[cache] using {cache_path.name}")
        cache = load_cache(cache_path)
    else:
        cache = extract(video, cache_path, cfg, args.start, args.end)

    pick = None
    if args.pick:
        pick = interactive_pick(cache, cfg)
        if pick is None:
            return
        pick_path.write_text(json.dumps(pick))
    elif pick_path.exists():
        pick = json.loads(pick_path.read_text())
        print(f"[pick] reusing fighter selection from {pick_path.name} (use --pick to redo)")

    summary = render(cache, out_path, cfg, [n.upper() for n in args.names], args.layout, pick,
                     args.swap, args.preview, data_prefix=str(out_path.with_suffix("")))
    print(json.dumps(summary, indent=2))
    print(f"\n[done] {out_path}")


if __name__ == "__main__":
    main()
