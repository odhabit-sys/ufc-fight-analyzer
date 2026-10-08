"""Background processing of uploaded fights.

One worker thread processes jobs in order (the pose model uses the whole GPU anyway).
Each job lives in data/jobs/<id>/:

    upload.<ext>      the file as uploaded
    video.mp4         web-ready copy (H.264, constant frame rate, faststart) - what the
                      browser plays AND what the analyzer reads, so frame N is at N/fps in both
    pose_cache.pkl    stage-1 cache (same format as the CLI's)
    selection.json    candidate frames + detected people for picking the fighters
    select_<n>.jpg    those frames
    pick.json         the user's choice {frame, dets:[F1, F2]}
    analysis.json     \\  the viewer's data (see fight_analyzer/webexport.py)
    pose.bin          /
    job.json          status/progress, so finished jobs survive a server restart

Flow: detect phase (prepare + pose, slow) -> status "needs_selection" -> the user picks
F1/F2 in the browser -> analyze phase (track + build, seconds) -> "done". "Change fighters"
just submits a new pick, re-running only the analyze phase on the cached poses.

Progress is real: ffmpeg's own progress output for "prepare", frames processed for
"detect" and "track". Nothing is simulated.
"""
import json
import queue
import re
import shutil
import subprocess
import threading
import time
import traceback
import uuid
from pathlib import Path

import cv2
import imageio_ffmpeg

from fight_analyzer.config import Config
from fight_analyzer.extract import extract
from fight_analyzer.extract import load_cache
from fight_analyzer.webexport import export

from .selection import build_selection

STAGES = [
    ("prepare", "Preparing video"),
    ("detect", "Detecting fighters & body poses"),
    ("select", "Select the fighters"),
    ("track", "Tracking fighters · detecting strikes · scoring momentum"),
    ("build", "Building the interactive timeline"),
]
MAX_HEIGHT = 1080


class JobManager:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.jobs, self.lock, self.q = {}, threading.Lock(), queue.Queue()
        for jf in sorted(self.root.glob("*/job.json")):
            try:
                job = json.loads(jf.read_text())
            except Exception:
                continue
            if not any(st["key"] == "select" for st in job["stages"]):   # jobs from before selection existed
                job["stages"].insert(2, dict(key="select", label="Select the fighters", progress=1.0, state="done"))
            if job["status"] in ("queued", "running"):
                if (jf.parent / "pose_cache.pkl").exists():
                    # detection finished earlier: resume at fighter selection instead of failing
                    job["status"], job["error"] = "needs_selection", None
                else:
                    job["status"], job["error"] = "error", "Interrupted: the server stopped while processing."
                self._save(job)
            self.jobs[job["id"]] = job
        threading.Thread(target=self._worker, daemon=True).start()

    # ---- public ------------------------------------------------------------------------
    def create(self, filename: str, fileobj) -> dict:
        jid = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
        d = self.root / jid
        d.mkdir()
        ext = (Path(filename).suffix or ".mp4").lower()
        with open(d / f"upload{ext}", "wb") as fh:
            shutil.copyfileobj(fileobj, fh, 4 << 20)
        job = dict(id=jid, name=Path(filename).name, created=time.time(), status="queued",
                   stage=None, error=None, eta=None, upload=f"upload{ext}",
                   stages=[dict(key=k, label=l, progress=0.0, state="pending") for k, l in STAGES])
        with self.lock:
            self.jobs[jid] = job
        self._save(job)
        self.q.put((jid, "detect"))
        return job

    def selection(self, jid):
        d = self.root / jid
        if not (d / "pose_cache.pkl").exists():
            return None
        return build_selection(load_cache(d / "pose_cache.pkl"), Config(), d)

    def submit_selection(self, jid, frame, dets):
        """Validate a pick against the offered frames, then queue the fast analyze phase."""
        with self.lock:
            job = self.jobs.get(jid)
            if not job:
                raise KeyError(jid)
            if job["status"] in ("queued", "running"):
                raise ValueError("This fight is still being processed.")
        sel = self.selection(jid)
        if sel is None:
            raise ValueError("Fighter detection has not finished for this video.")
        fr = next((f for f in sel["frames"] if f["frame"] == frame), None)
        n_people = len(fr["people"]) if fr else 0
        if (fr is None or len(dets) != 2 or dets[0] == dets[1]
                or not all(isinstance(i, int) and 0 <= i < n_people for i in dets)):
            raise ValueError("Invalid selection.")
        pick = dict(frame=frame, dets=dets, from_start=True)
        (self.root / jid / "pick.json").write_text(json.dumps(pick))
        with self.lock:
            job.update(status="queued", error=None, eta=None, pick=pick)
            for s in job["stages"]:
                if s["key"] == "select":
                    s.update(state="done", progress=1.0)
                elif s["key"] in ("track", "build"):
                    s.update(state="pending", progress=0.0)
        self._save(job)
        self.q.put((jid, "analyze"))
        return job

    def get(self, jid):
        with self.lock:
            job = self.jobs.get(jid)
            return json.loads(json.dumps(job)) if job else None

    def list(self):
        with self.lock:
            return sorted((json.loads(json.dumps(j)) for j in self.jobs.values()),
                          key=lambda j: -j["created"])

    def path(self, jid, name):
        return self.root / jid / name

    # ---- internals -------------------------------------------------------------------------
    def _save(self, job):
        tmp = self.root / job["id"] / "job.json.tmp"
        tmp.write_text(json.dumps(job, indent=1))
        tmp.replace(self.root / job["id"] / "job.json")

    def _stage(self, job, key, progress=None, state=None, eta=None):
        with self.lock:
            for s in job["stages"]:
                if s["key"] == key:
                    if progress is not None:
                        s["progress"] = round(min(1.0, progress), 4)
                    if state:
                        s["state"] = state
            if state == "running":
                job["stage"] = key
            job["eta"] = eta
        now = time.time()
        if state or now - job.get("_saved", 0) > 1.0:
            job["_saved"] = now
            self._save(job)

    def _worker(self):
        while True:
            jid, phase = self.q.get()
            job = self.jobs[jid]
            try:
                job["status"] = "running"
                if phase == "detect":
                    self._run_detect(job)
                    self._stage(job, "select", 0, "running")
                    job["status"] = "needs_selection"
                else:
                    self._run_analyze(job)
                    job["status"] = "done"
                    job["stage"] = None
            except Exception as e:  # report, keep the server alive
                traceback.print_exc()
                job["status"], job["error"] = "error", f"{type(e).__name__}: {e}"
            job["eta"] = None
            self._save(job)

    def _run_detect(self, job):
        d = self.root / job["id"]
        src, video = d / job["upload"], d / "video.mp4"
        cfg = Config()

        # 1. prepare: web-playable, constant-frame-rate H.264
        self._stage(job, "prepare", 0, "running")
        cap = cv2.VideoCapture(str(src))
        if not cap.isOpened():
            raise ValueError("This file could not be read as a video.")
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        n_src = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        cap.release()
        duration = n_src / fps if n_src > 0 else None
        self._transcode(job, src, video, h, duration)
        self._stage(job, "prepare", 1, "done")

        # 2. detect: pose + camera motion (the slow stage)
        self._stage(job, "detect", 0, "running")
        t0 = time.time()

        def on_detect(done, total, last=None):
            rate = done / max(time.time() - t0, 1e-6)
            if last is not None:
                job["preview"] = dict(_preview(done - 1, last, cfg.kp_conf), t=(done - 1) / fps, total=total)
            self._stage(job, "detect", done / total, eta=round((total - done) / max(rate, 1e-6)))

        cache_path = d / "pose_cache.pkl"
        extract(str(video), cache_path, cfg, progress=on_detect)
        job.pop("preview", None)
        self._stage(job, "detect", 1, "done")
        # candidate frames for the selection screen (from the cache, no inference)
        build_selection(load_cache(cache_path), cfg, d)

    def _run_analyze(self, job):
        d = self.root / job["id"]
        cfg = Config()
        cache = load_cache(d / "pose_cache.pkl")
        pick = json.loads((d / "pick.json").read_text())

        # 3+4. track/score, then write the viewer data
        self._stage(job, "track", 0, "running")
        n = len(cache["frames"])

        def on_track(done, total):
            self._stage(job, "track", done / total)
            if done >= total - 15:
                self._stage(job, "track", 1, "done")
                self._stage(job, "build", 0, "running")

        export(cache, cfg, d, pick=pick, progress=on_track)
        self._stage(job, "track", 1, "done")
        self._stage(job, "build", 1, "done")
        job["result"] = dict(frames=n, duration=round(n / cache["fps"], 2), fps=cache["fps"],
                             width=cache["width"], height=cache["height"])

    def _transcode(self, job, src, dst, height, duration):
        ff = imageio_ffmpeg.get_ffmpeg_exe()
        vf = f"scale=-2:{MAX_HEIGHT}" if height > MAX_HEIGHT else "scale=trunc(iw/2)*2:trunc(ih/2)*2"
        cmd = [ff, "-y", "-loglevel", "error", "-i", str(src), "-map", "0:v:0", "-map", "0:a:0?",
               "-vf", vf, "-fps_mode", "cfr", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
               "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart",
               "-progress", "pipe:1", "-nostats", str(dst)]
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        for line in p.stdout:
            m = re.match(r"out_time_us=(\d+)", line.strip())
            if m and duration:
                self._stage(job, "prepare", int(m.group(1)) / 1e6 / duration)
        if p.wait() != 0:
            raise RuntimeError("ffmpeg could not convert this video: " + p.stderr.read()[-300:])


def _preview(frame, fd, kp_conf, max_people=6):
    """The people just detected on `frame` (largest first) for the processing screen's live
    view: exactly what the pose model returned, nothing inferred."""
    people = []
    for box, kxy, kc in zip(fd["boxes"], fd["kxy"], fd["kc"]):
        if (kc > kp_conf).sum() < 6:
            continue
        people.append(dict(box=[round(float(v)) for v in box],
                           kp=[[round(float(x)), round(float(y)), round(float(c), 2)] for (x, y), c in zip(kxy, kc)]))
    people.sort(key=lambda p: -(p["box"][2] - p["box"][0]) * (p["box"][3] - p["box"][1]))
    return dict(frame=int(frame), people=people[:max_people])
