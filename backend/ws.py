"""WebSocket progress manager with bounded history replay & multi-subscriber support."""
import asyncio
import json
from collections import deque
from fastapi import WebSocket


class ProgressManager:
    def __init__(self, max_history: int = 200, max_jobs: int = 20):
        self.subscribers: dict[str, set[asyncio.Queue]] = {}
        self.history: dict[str, deque] = {}
        self.terminal: dict[str, dict] = {}
        self.max_history = max_history
        self.max_jobs = max_jobs

    def _ensure_history(self, job_id: str) -> deque:
        if job_id not in self.history:
            if len(self.history) >= self.max_jobs:
                oldest = next(iter(self.history))
                if not self.subscribers.get(oldest):
                    self.history.pop(oldest, None)
                    self.terminal.pop(oldest, None)
            self.history[job_id] = deque(maxlen=self.max_history)
        return self.history[job_id]

    async def send(self, job_id: str, msg: dict):
        hist = self._ensure_history(job_id)
        hist.append(msg)
        if msg.get("type") in ("done", "error"):
            self.terminal[job_id] = msg
        for q in list(self.subscribers.get(job_id, ())):
            await q.put(msg)

    async def stream(self, job_id: str, ws: WebSocket):
        q: asyncio.Queue = asyncio.Queue()
        subs = self.subscribers.setdefault(job_id, set())
        subs.add(q)
        try:
            hist = list(self.history.get(job_id, ()))
            for msg in hist:
                await ws.send_text(json.dumps(msg))
                if msg.get("type") in ("done", "error"):
                    return
            if job_id in self.terminal:
                return
            from backend import db
            job = db.get_job(job_id)
            if job and job.get("status") in ("completed", "failed", "cancelled", "interrupted"):
                m = (
                    {"type": "error", "message": job.get("error") or job["status"]}
                    if job["status"] == "failed"
                    else {"type": "done", "status": job["status"],
                          "total": job.get("total", 0), "scraped": job.get("scraped", 0)}
                )
                await ws.send_text(json.dumps(m))
                return
            while True:
                msg = await q.get()
                await ws.send_text(json.dumps(msg))
                if msg.get("type") in ("done", "error"):
                    break
        finally:
            subs.discard(q)
            if not subs:
                self.subscribers.pop(job_id, None)


manager = ProgressManager()
