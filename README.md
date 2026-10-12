# UFC / MMA Fight Analyzer

A local web app that analyses a prerecorded MMA fight video with computer vision. You upload a fight,
click which person is Fighter 1 (red) and Fighter 2 (blue), and then watch the fight in the browser with
pose skeletons, per-fighter stats, detected events and an **experimental momentum index**
(e.g. `63% / 37%`) synced to the video. The momentum index comes only from things the system measures;
it is **not** a win probability or an official result.

Everything runs on your own computer. Nothing is uploaded anywhere.

## Requirements

| | |
|---|---|
| **Operating system** | Windows 10/11 (64-bit, x64), macOS 14+ on Apple Silicon (M1 or newer), or 64-bit Linux |
| **Python** | 3.12, 3.13 or 3.14, 64-bit (3.13 recommended). Python 3.15 is not supported yet: PyTorch has no 3.15 build |
| **Disk space** | about 3 GB (Python packages ~2 GB, model 40 MB, plus your analysed videos) |
| **Internet** | needed on the first start only (downloads ~1 GB of packages and the 40 MB pose model) |
| **FFmpeg** | nothing to install: it is bundled with the Python packages |

Not supported: Intel Macs (PyTorch no longer publishes Intel-Mac builds) and Windows on ARM.

Speed: on an Apple M1, detection runs at about 9 video frames per second (a 2-minute fight takes about 8
minutes). Windows and Linux run the pose model on the CPU (NVIDIA GPUs are not used yet), which is much
slower: on 4-core Windows cloud machines detection ran at about 1.2 to 3 frames per second, so a 2-minute
fight takes roughly 20 to 50 minutes there. A recent desktop CPU with more cores will be faster. Detection
runs only once per video: picking different fighters afterwards takes seconds.

## Windows

1. **Install Python 3.13.** On https://www.python.org/downloads/windows/ find the newest **Python 3.13.x**
   release (the "Latest Python 3 Release" at the top is 3.15, which PyTorch does not support yet) and
   download its **Windows installer (64-bit)**. Run it, tick **"Add python.exe to PATH"** on the first
   screen, then click *Install Now*.
   If you use the newer *Python install manager* instead, run `py install 3.13` in a terminal (with no
   Python installed at all, `run.bat` lets the install manager fetch 3.13 by itself).
   Other Python versions can stay installed; `run.bat` picks 3.13 automatically.
2. **Download the project.** Either
   - on the GitHub page click **Code → Download ZIP**, then right-click the ZIP and choose
     **Extract All…** (do not run it from inside the ZIP), or
   - with Git: `git clone https://github.com/odhabit-sys/ufc-fight-analyzer.git`

   Keep the folder somewhere with a short path, such as `C:\Users\<you>\Downloads` or `C:\ufc-fight-analyzer`.
3. **Start it.** Open the project folder and double-click **`run.bat`**.
   If Windows shows "Windows protected your PC", click *More info → Run anyway* (`run.bat` is a short text
   file you can open in Notepad to check first). From a terminal you can also run:
   ```bat
   cd path\to\ufc-fight-analyzer
   run.bat
   ```
4. **Wait for the first-time setup.** A console window creates a private Python environment in the `.venv`
   folder, installs the packages (about 1 GB, several minutes) and downloads the pose model. This happens only once.
5. **Use the app.** When setup finishes, your browser opens the app at its local address
   **http://127.0.0.1:8000**. That address is served by the program running in the console window: it only
   works on this computer, and only while that window stays open. It is not a public link.
6. **Stop it** by closing the console window, or press `Ctrl+C` in it and answer `Y` to Windows' question
   *"Terminate batch job (Y/N)?"*. Next time, double-click `run.bat` again; it starts in a few seconds.

## macOS / Linux

1. **Install Python 3.13** (3.12 and 3.14 also work; 3.15 is not supported yet).
   - macOS (Apple Silicon): the installer from https://www.python.org/downloads/macos/ , or `brew install python@3.13`
   - Linux (Debian/Ubuntu): `sudo apt install python3.12 python3.12-venv` (or newer)
2. **Download the project.**
   ```bash
   git clone https://github.com/odhabit-sys/ufc-fight-analyzer.git
   cd ufc-fight-analyzer
   ```
   Or on the GitHub page click **Code → Download ZIP**, unzip it, and open a terminal in that folder.
3. **Start it.**
   ```bash
   ./run.sh
   ```
   If you downloaded the ZIP and get "permission denied", run `bash run.sh` instead.
4. **Wait for the first-time setup.** It creates a private Python environment in `.venv`, installs the
   packages (about 1 GB, several minutes) and downloads the pose model. This happens only once.
5. **Use the app.** Your browser opens the app at its local address **http://127.0.0.1:8000**. That
   address is served by the program running in your terminal: it only works on this computer, and only
   while that terminal keeps running. It is not a public link.
6. **Stop it** with `Ctrl+C` in the terminal. Next time, run `./run.sh` again; it starts in a few seconds.

## Start options and troubleshooting

`run.bat` / `run.sh` accept these options (they are passed to `launch.py`):

| Option | Effect |
|---|---|
| `--port 8080` | use another port (if 8000 is busy the next free port is chosen automatically and printed) |
| `--no-browser` | don't open the browser; open the printed local address yourself |
| `--setup-only` | install/check everything without starting the app |
| `--reinstall` | reinstall the Python packages (fixes a damaged installation) |

The start script checks everything it needs and stops with an explanation instead of failing silently:

| Message | What to do |
|---|---|
| *Python 3.12 or newer was not found* / *is too old* | Install Python as in step 1 and start again. |
| *Python 3.15 … is newer than PyTorch supports* | Also install Python 3.13 as in step 1 (it can sit next to 3.15); the start script then uses 3.13. |
| *This is a 32-bit Python* | Install the 64-bit Python from python.org. |
| *Installing the dependencies failed* | Check the internet connection and free disk space, then start again. |
| *The project folder path is too long for Windows* | Move the folder to a shorter path (e.g. `C:\ufc-fight-analyzer`) or enable Windows long paths. |
| *FFmpeg is not usable* | Start with `--reinstall`. |
| *Could not download the model weights* | Check the internet connection, or download the file shown in the message manually into the project folder. |
| *The existing '.venv' environment is broken* | Delete the `.venv` folder and start again. |
| Browser shows "can't connect" | The program isn't running: start `run.bat` / `run.sh` again and keep its window open. |

The pose model (`yolo11m-pose.pt`) is downloaded automatically from the official
[Ultralytics releases](https://github.com/ultralytics/assets/releases) on the first start. It is not part
of this repository. Ultralytics' code and models are licensed under AGPL-3.0.

## How the web app works

Upload a fight. After pose detection you click Fighter 1 (red) and Fighter 2 (blue) on a frame from the
fight; the analysis then opens in the interactive viewer. Skeletons, stats, momentum and events are all
drawn live from the analysis data, synced to the frame the video is showing.

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

## Command-line analyzer (optional, for debugging)

The original CLI produces an MP4 with the analysis HUD burned in, plus CSV/JSON exports. It uses the same
environment as the web app, so start the app once first (or run `python launch.py --setup-only`), then
activate the environment:

```bash
source .venv/bin/activate            # macOS / Linux
.venv\Scripts\activate               # Windows (Command Prompt or PowerShell)
```

Put a fight clip in `videos/` (for tuning, start with 30–60 s of a clean, wide angle without replays) and run:
```bash
python analyze.py videos/fight.mp4 --start 0 --end 60 --pick --names "Smith" "Jones"
```
- `--pick` opens a window. Click Fighter 1, then Fighter 2, and press Enter (`n`/`p` jump ±1 s if the first frame is bad).
  The choice is saved, so later runs reuse it. Without `--pick` the analyzer picks the two largest shirtless people
  automatically, which skips the referee.
- The output goes to `output/fight_analyzed.mp4`, along with `_signals.csv` (per-frame data) and `_events.json`.
- Re-running is fast because pose data is cached. Use `--reextract` after changing the model.

Useful flags: `--layout overlay` (HUD on top of the video instead of around it), `--swap`, `--preview`,
`--model yolo11x-pose.pt --imgsz 1280` (most accurate skeletons, about 3–4× slower).

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
