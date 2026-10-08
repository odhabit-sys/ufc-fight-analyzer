# UFC / MMA Fight Analyzer

Turns a prerecorded fight video into a computer-vision "fight analysis" video: a pose skeleton on each
fighter, persistent Fighter 1 / Fighter 2 identities, live signals, and an **experimental momentum
index** (e.g. `63% / 37%`) that comes from things the system actually measures. It is **not** a win probability.

```
video ──► Stage 1: EXTRACT (slow, cached)          ──► Stage 2: RENDER (fast, re-run freely)
          YOLO11-pose: boxes + 17 keypoints/person      two-fighter identity tracking
          camera motion (optical flow on background)    keypoint smoothing (One Euro)
          scene-cut detection                           signals → events → momentum
                                                        HUD → H.264 mp4 (+ original audio)
                                                        CSV + JSON data export
```

## Web app (main experience)
```bash
./run.sh
```
This opens http://127.0.0.1:8000. Upload a fight. After pose detection you click Fighter 1 (red) and
Fighter 2 (blue) on a frame from the fight; the analysis then opens in the interactive viewer. Skeletons,
stats, momentum and events are all drawn live from the analysis data, synced to the frame the video is showing.

```
Browser ─upload─▶ webapp/server.py (FastAPI) ─queue─▶ webapp/jobs.py worker
   1 prepare   ffmpeg → H.264, constant frame rate   (frame N is at N/fps everywhere)
   2 detect    fight_analyzer/extract.py   YOLO pose + camera motion  → pose_cache.pkl
     select    you pick F1/F2 on candidate frames  (webapp/selection.py, from the cache, no inference)
   3 track     fight_analyzer/pipeline.py  identity, signals, momentum
   4 build     fight_analyzer/webexport.py → analysis.json + pose.bin
Viewer (webapp/static): frame on screen = floor(video time × fps) → look up every array at [frame]
```
"Change fighters" on the analysis page re-runs only steps 3–4 on the cached poses (seconds, no re-upload).
Jobs are stored in `data/jobs/<id>/` and listed on the upload page, so you can reopen them without reprocessing.
Keyboard: Space play/pause · ←/→ 1 s (Shift = 5 s) · `,` / `.` one frame · `S` toggle skeletons.
The CLI below still works and is useful for debugging. It produces an MP4 with the HUD burned in.

## Step-by-step (CLI)

### 1. Setup (already done in this folder)
```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```
Python 3.13 is used because 3.14 is too new for parts of the CV stack. The pose model downloads
automatically on the first run, and ffmpeg comes bundled through `imageio-ffmpeg`.

### 2. Get a test clip
Put a fight clip in `videos/`. For tuning, start with **30–60 s** of a clean, wide angle, with no replays
and no picture-in-picture graphics.

### 3. Run it
```bash
source .venv/bin/activate
python analyze.py videos/fight.mp4 --start 0 --end 60 --pick --names "Smith" "Jones"
```
- `--pick` opens a window. Click Fighter 1, then Fighter 2, and press Enter (`n`/`p` jump ±1 s if the first frame is bad).
  The choice is saved, so later runs reuse it. Without `--pick` the analyzer picks the two largest shirtless people
  automatically, which skips the referee.
- The output goes to `output/fight_analyzed.mp4`, along with `_signals.csv` (per-frame data) and `_events.json`.
- Re-running is fast because pose data is cached. Use `--reextract` after changing the model.

Useful flags: `--layout overlay` (HUD on top of the video instead of around it), `--swap`, `--preview`,
`--model yolo11x-pose.pt --imgsz 1280` (most accurate skeletons, about 3–4× slower).

### 4. Tune
All thresholds are in [fight_analyzer/config.py](fight_analyzer/config.py) and are commented. Watch the output, then check
`_events.json` and the CSV to see why something did or did not fire.

## What is measured, and how honest it is

| Signal | How | Reliability |
|---|---|---|
| Skeleton / pose | YOLO11-pose, 17 COCO keypoints, smoothed | Good on clear frames. Degrades in tight clinches and on the ground (limbs get swapped or lost) |
| Fighter identity | Fixed 2-slot assignment: shorts/torso colour + position + overlap, Hungarian matching. Appearance-only after camera cuts | Good when shorts differ in colour. Can swap in long clinches when both fighters wear similar shorts |
| Camera compensation | Optical flow on the background (fighters masked) gives a similarity transform per frame | Good for pans and zooms. Cuts are detected and reset motion |
| Forward pressure / retreat | Hip velocity toward the opponent after removing camera motion, in body-lengths/s | **Moderate.** Only the 2D component; movement toward or away from the camera is invisible |
| Activity / speed | Limb speed relative to the hips | Good |
| Punch / kick **attempts** | Fast wrist (ankle) burst relative to the shoulder (hip) + limb extension + travelling toward the opponent + within range | **Moderate.** Catches most straight shots. Feints and hand-fighting can count; some hooks and occluded strikes get missed |
| "On target?" | Fist or foot inside the opponent's head circle or torso box at peak extension | **Weak, so it is labeled with "?".** 2D overlap is not contact. Blocked shots look the same |
| Knockdown | Torso goes from vertical to horizontal suddenly, within 1.5 s of an "on target?" strike, while the opponent stays standing | Labeled "POSSIBLE". Can't tell a flash KD from a slip with certainty |
| Takedown | Drop at close range, credited to whoever ends up on top within 2 s | Moderate. Rolls and scrambles are ambiguous |
| Control | Standing over, or higher than, a downed opponent at close range | Moderate. Depends on camera angle |
| **Not attempted** | Landed vs. blocked strikes, damage, significant strikes, submissions, cage position, judging criteria | Not reliable from monocular broadcast video |

## The momentum index
Each fighter earns points (weights are in `config.py`):
strike attempts 1.0, kicks 1.3, "on target?" bonus +1.5, pressure 0.5/s per BL/s, opponent retreating
0.25/s, control 0.8/s, takedown 3, possible knockdown 10, plus a small activity term.

Points decay with a **20 s half-life**, so the number reflects *recent* momentum. The share is
`(m1 + 4) / (m1 + m2 + 8)`, where the prior of 4 keeps the bar near 50/50 until there is real evidence.
The side panel shows where each fighter's current momentum comes from, so you can explain any number on camera.

## Tested on real footage (videos/fight.mp4, 2:17, 854×480, broadcast)
Checked by eye on 110 frames sampled every 2.5 s, with two interleaved sets: one for tuning, one held out.
- **Identity:** no spectator or referee lock-ons. In stand-up there are no F1/F2 swaps in either set.
  The remaining errors happen right after a camera cut where a fighter is only partly in frame, and in a
  pile-up on the ground. In both cases the colour descriptor itself gives the wrong answer.
  When identity is unclear the tracker now shows "SEARCHING" rather than guessing.
- **Ground:** the top fighter is tracked reliably. The bottom fighter is usually hidden and gets no skeleton.
  For that reason control time and ground-and-pound strikes are **undercounted**.
- **Strike attempts:** about 70% of sampled detections were real strikes. False ones came from blocks and
  parries, and from the referee's arm when he stood between the fighters.
- **Big events:** the one real knockdown (105.6 s) is detected and credited correctly. No false
  takedowns or knockdowns remain. A real slip (~79 s) is no longer announced, which is the price of
  suppressing false "fighter down" banners during ground-and-pound.
- To QA a new clip: `python tools/review_grid.py output/<clip>...pose.pkl --step 2.5`, then repeat with `--offset 1.25`.

## Known limitations / next upgrades
- **Appearance re-ID** is the main limit: colour histograms at 480p can't tell two bare backs apart, and they
  misread partial bodies at the frame edge. A learned re-identification model (e.g. OSNet via `torchreid`/`boxmot`)
  is the next tracking upgrade.
- Broadcast **replays** double-count actions. Trim them out, or use `--start/--end` around live action.
- Tight clinches and ground fighting hurt pose accuracy. The `yolo11x-pose` model at `--imgsz 1280` helps;
  RTMPose / ViTPose via `rtmlib` are stronger next steps.
- Identity is most robust when the two fighters' shorts differ in colour (they almost always do in the UFC).
