"""Local web server: upload -> background analysis -> interactive viewer."""
from pathlib import Path

import re

from fastapi import Body, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .jobs import JobManager

ROOT = Path(__file__).resolve().parent.parent
STATIC = Path(__file__).resolve().parent / "static"
ALLOWED = {".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi"}
SERVED = {"video.mp4": "video/mp4", "analysis.json": "application/json",
          "pose.bin": "application/octet-stream"}

app = FastAPI(title="Fight Analyzer")
jobs = JobManager(ROOT / "data" / "jobs")


@app.middleware("http")
async def revalidate_app_files(request, call_next):
    """Make browsers revalidate the app's HTML/JS/CSS on every load, so an updated
    frontend is never mixed with stale cached modules (cheap: unchanged files get 304)."""
    response = await call_next(request)
    if request.url.path == "/" or request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache"
    return response


def public(job):
    out = {k: v for k, v in job.items() if not k.startswith("_")}
    out["has_poses"] = jobs.path(job["id"], "pose_cache.pkl").exists()
    return out


@app.post("/api/jobs")
def create_job(file: UploadFile = File(...)):
    if Path(file.filename or "").suffix.lower() not in ALLOWED:
        raise HTTPException(400, "Please upload a video file (MP4 or MOV).")
    return public(jobs.create(file.filename, file.file))


@app.get("/api/jobs")
def list_jobs():
    return [public(j) for j in jobs.list()]


@app.get("/api/jobs/{jid}")
def get_job(jid: str):
    job = jobs.get(jid)
    if not job:
        raise HTTPException(404, "No such analysis.")
    return public(job)


@app.get("/api/jobs/{jid}/selection")
def get_selection(jid: str):
    """Candidate frames + detected people for picking F1/F2 (built from the pose cache)."""
    if not jobs.get(jid):
        raise HTTPException(404, "No such analysis.")
    sel = jobs.selection(jid)
    if sel is None:
        raise HTTPException(409, "Fighter detection has not finished yet.")
    return sel


@app.post("/api/jobs/{jid}/selection")
def post_selection(jid: str, frame: int = Body(...), dets: list[int] = Body(...)):
    try:
        return public(jobs.submit_selection(jid, frame, dets))
    except KeyError:
        raise HTTPException(404, "No such analysis.")
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/jobs/{jid}/{name}")
def job_file(jid: str, name: str):
    job = jobs.get(jid)
    if job and re.fullmatch(r"select_\d+\.jpg", name):
        path = jobs.path(jid, name)
        if path.exists():
            return FileResponse(path, media_type="image/jpeg")
    if not job or name not in SERVED:
        raise HTTPException(404)
    if name != "video.mp4" and job["status"] != "done":
        raise HTTPException(409, "Analysis not finished yet.")
    path = jobs.path(jid, name)
    if not path.exists():
        raise HTTPException(404)
    # FileResponse answers HTTP Range requests, which the <video> element needs to seek
    return FileResponse(path, media_type=SERVED[name], headers={"Cache-Control": "no-cache"})


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
