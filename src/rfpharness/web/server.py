"""데모 웹 서버: 업로드 → 단계 진행(SSE) → 결과 탭. 프런트는 app.html 하나."""
from __future__ import annotations

import json
import os
import queue
import shutil
import threading
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse

from ..llm import LLM
from ..pipeline import STAGES, Pipeline, format_summary

WEB_DIR = Path(__file__).parent
ROOT = Path(__file__).resolve().parents[3]
SAMPLES = ROOT / "samples"
JOBS_DIR = ROOT / "out" / "web"


class Job:
    def __init__(self, job_id: str, pdf: Path, draft: Path | None, llm_mode: str | None):
        self.id = job_id
        self.pdf = pdf
        self.draft = draft
        self.out = JOBS_DIR / job_id
        self.q: queue.Queue = queue.Queue()
        self.events: list[dict] = []
        self.done = False
        self.error: str | None = None
        self.llm = LLM(mode=llm_mode) if llm_mode else LLM()
        self.started = time.time()

    def emit(self, ev: dict) -> None:
        ev["t"] = round(time.time() - self.started, 1)
        self.events.append(ev)
        self.q.put(ev)

    def run(self) -> None:
        delay = float(os.environ.get("RFPHARNESS_DEMO_DELAY", "0") or 0)  # 데모 녹화 때 단계 진행이 보이게 하는 지연(초)

        def progress(stage: str, status: str, done: int, total: int) -> None:
            self.emit({"type": "stage", "stage": stage, "status": status, "done": done, "total": total})
            if delay and status in ("done", "running") and total:
                time.sleep(delay / max(total, 1))
            elif delay and status == "done":
                time.sleep(delay)

        try:
            pipe = Pipeline(self.pdf, self.out, draft=self.draft, llm=self.llm, progress=progress)
            report = pipe.run(fresh=True)
            (self.out / "run.log").write_text(format_summary(report), encoding="utf-8")
            self.emit({"type": "done", "summary": report.summary.model_dump(), "llm_mode": self.llm.mode,
                       "llm_calls": self.llm.usage.calls, "tokens": [self.llm.usage.input_tokens, self.llm.usage.output_tokens]})
        except Exception as e:  # noqa: BLE001
            self.error = f"{type(e).__name__}: {e}"
            self.emit({"type": "error", "message": self.error})
        finally:
            self.done = True
            self.q.put(None)


def create_app(llm_mode: str | None = None) -> FastAPI:
    app = FastAPI(title="RFP Compass")
    jobs: dict[str, Job] = {}
    JOBS_DIR.mkdir(parents=True, exist_ok=True)

    @app.get("/", response_class=HTMLResponse)
    def index():
        return (WEB_DIR / "app.html").read_text(encoding="utf-8")

    @app.get("/api/samples")
    def samples():
        pdfs = sorted(p.name for p in SAMPLES.glob("*.pdf"))
        drafts = sorted(p.name for p in SAMPLES.glob("*.md")) + sorted(p.name for p in SAMPLES.glob("*.docx"))
        return {"pdfs": pdfs, "drafts": drafts, "llm_mode": (llm_mode or LLM().mode)}

    def _start(pdf: Path, draft: Path | None, mode: str | None) -> Job:
        job = Job(uuid.uuid4().hex[:8], pdf, draft, mode)
        jobs[job.id] = job
        threading.Thread(target=job.run, daemon=True).start()
        return job

    @app.post("/api/jobs")
    async def create_job(pdf: UploadFile = File(...), draft: UploadFile | None = File(None), llm: str | None = Form(None)):
        job_id = uuid.uuid4().hex[:8]
        d = JOBS_DIR / job_id
        d.mkdir(parents=True, exist_ok=True)
        pdf_path = d / (Path(pdf.filename).name or "rfp.pdf")
        pdf_path.write_bytes(await pdf.read())
        draft_path = None
        if draft and draft.filename:
            draft_path = d / Path(draft.filename).name
            draft_path.write_bytes(await draft.read())
        job = Job(job_id, pdf_path, draft_path, llm or llm_mode)
        jobs[job.id] = job
        threading.Thread(target=job.run, daemon=True).start()
        return {"job_id": job.id}

    @app.post("/api/jobs/sample")
    def create_sample_job(pdf: str = Form(...), draft: str | None = Form(None), llm: str | None = Form(None)):
        src = SAMPLES / Path(pdf).name
        if not src.exists():
            raise HTTPException(404, "샘플 PDF 없음")
        job_id = uuid.uuid4().hex[:8]
        d = JOBS_DIR / job_id
        d.mkdir(parents=True, exist_ok=True)
        pdf_path = d / src.name
        shutil.copy(src, pdf_path)
        draft_path = None
        if draft:
            ds = SAMPLES / Path(draft).name
            if ds.exists():
                draft_path = d / ds.name
                shutil.copy(ds, draft_path)
        job = Job(job_id, pdf_path, draft_path, llm or llm_mode)
        jobs[job.id] = job
        threading.Thread(target=job.run, daemon=True).start()
        return {"job_id": job.id}

    @app.get("/api/jobs/{job_id}/events")
    def events(job_id: str):
        job = jobs.get(job_id)
        if not job:
            raise HTTPException(404)

        def gen():
            for ev in list(job.events):
                yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
            if job.done:
                return
            while True:
                ev = job.q.get()
                if ev is None:
                    return
                yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"

        return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})

    @app.get("/api/jobs/{job_id}/report")
    def report(job_id: str):
        job = jobs.get(job_id)
        if not job:
            raise HTTPException(404)
        p = job.out / "report.json"
        if not p.exists():
            raise HTTPException(409, "아직 결과가 없다")
        return JSONResponse(json.loads(p.read_text(encoding="utf-8")))

    @app.get("/api/jobs/{job_id}/pages")
    def pages(job_id: str):
        job = jobs.get(job_id)
        if not job:
            raise HTTPException(404)
        p = job.out / "checkpoints" / "parse.json"
        if not p.exists():
            raise HTTPException(409)
        doc = json.loads(p.read_text(encoding="utf-8"))
        return {str(pg["number"]): pg["text"] for pg in doc["pages"]}

    @app.get("/api/jobs/{job_id}/download/{kind}")
    def download(job_id: str, kind: str):
        job = jobs.get(job_id)
        if not job:
            raise HTTPException(404)
        name = {"xlsx": "traceability.xlsx", "docx": "toc_draft.docx", "json": "report.json", "html": "dashboard.html"}.get(kind)
        if not name or not (job.out / name).exists():
            raise HTTPException(404)
        return FileResponse(job.out / name, filename=name)

    @app.get("/api/stages")
    def stages():
        return STAGES

    return app
