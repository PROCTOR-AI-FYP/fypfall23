"""Short HTTP delivery for bounded, server-verified camera object checks.

There is no inference queue: one task uses the shared object model, and every
camera retains at most its latest result. Polling renews a short expiry timer;
abandoned/stopped cameras cannot keep private results or save late evidence.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException

logger = logging.getLogger('proctorai.device-camera-jobs')


@dataclass
class ObjectJob:
    job_id: str
    run: Any
    owner_id: str
    frame_index: int
    stop_run: Callable[[], None]
    touched: float
    task: asyncio.Task | None = None
    timer: asyncio.TimerHandle | None = None
    result: dict | None = None
    error: HTTPException | None = None


class ObjectJobs:
    def __init__(self, *, max_jobs=16, idle_seconds=90.):
        self.max_jobs = max_jobs
        self.idle_seconds = idle_seconds
        self.jobs: dict[str, ObjectJob] = {}
        self.by_run: dict[str, str] = {}
        self.tasks: set[asyncio.Task] = set()

    def _touch(self, job):
        job.touched = time.monotonic()
        if job.timer is not None:
            job.timer.cancel()
        job.timer = asyncio.get_running_loop().call_later(
            self.idle_seconds, self._expire, job.job_id)

    def _expire(self, job_id):
        job = self.jobs.get(job_id)
        if job is not None:
            try:
                job.stop_run()
            except Exception:
                logger.exception('Could not close expired camera %s', job.run.run_id)
            finally:
                self.discard_run(job.run.run_id)

    def discard_run(self, run_id):
        job_id = self.by_run.pop(run_id, None)
        job = self.jobs.pop(job_id, None)
        if job is not None:
            if job.timer is not None:
                job.timer.cancel()
            if job.task is not None and not job.task.done():
                job.task.cancel()
            job.result = None
            job.error = None

    def _prune(self):
        now = time.monotonic()
        for job in list(self.jobs.values()):
            if job.run.stopped or now - job.touched >= self.idle_seconds:
                self._expire(job.job_id)

    def ensure_available(self, run, frame_index):
        self._prune()
        if run.stopped:
            raise HTTPException(410, 'Camera was stopped.')
        existing = self.jobs.get(self.by_run.get(run.run_id))
        if existing is not None and existing.task is not None and not existing.task.done():
            raise HTTPException(429, 'This object check is still running; poll its result.',
                                headers={'Retry-After': '1'})
        if frame_index <= run.frame_index:
            raise HTTPException(409, 'Camera sample is out of order.')
        # Cancelling a thread-backed inference does not immediately stop its
        # thread. Keep that task counted until it releases the model lock.
        if any(not task.done() for task in self.tasks):
            raise HTTPException(429, 'Object checker is busy; the camera preview continues.',
                                headers={'Retry-After': '1'})
        if existing is None and len(self.jobs) >= self.max_jobs:
            raise HTTPException(429, 'Object result capacity is busy. Retry shortly.',
                                headers={'Retry-After': '1'})

    def submit(self, run, frame_index, work: Callable[[], Awaitable[dict]], stop_run):
        self.ensure_available(run, frame_index)
        self.discard_run(run.run_id)
        job = ObjectJob(str(uuid.uuid4()), run, run.owner_id, frame_index,
                        stop_run, time.monotonic())
        self.jobs[job.job_id] = job
        self.by_run[run.run_id] = job.job_id
        self._touch(job)
        job.task = asyncio.create_task(self._execute(job, work),
                                       name='proctorai-object-check')
        self.tasks.add(job.task)
        job.task.add_done_callback(self.tasks.discard)
        return job

    async def _execute(self, job, work):
        # Own the entire operation, including evidence upload and its database
        # transaction. A stopped delivery must not cancel between uploading a
        # snapshot and persist's normal cleanup/commit boundaries.
        operation = asyncio.create_task(work(), name='proctorai-object-operation')
        try:
            try:
                result = await asyncio.shield(operation)
            except asyncio.CancelledError:
                # stop_run has already revoked the camera. Its existing checks
                # prevent new evidence; an upload or committed transaction must
                # finish its own cleanup before another model job is accepted.
                await asyncio.gather(operation, return_exceptions=True)
                raise
            if self.jobs.get(job.job_id) is job and not job.run.stopped:
                job.result = result
        except asyncio.CancelledError:
            raise
        except HTTPException as error:
            if self.jobs.get(job.job_id) is job:
                job.error = HTTPException(error.status_code, error.detail,
                                          headers=error.headers)
        except Exception:
            logger.exception('Object check failed for camera %s', job.run.run_id)
            if self.jobs.get(job.job_id) is job:
                job.error = HTTPException(503, 'Object check failed. Retry shortly.')

    def get(self, job_id, run, owner_id):
        self._prune()
        job = self.jobs.get(job_id)
        if job is None or job.run is not run or job.owner_id != owner_id:
            raise HTTPException(404, 'Object result expired. Capture a new sample.')
        self._touch(job)
        return job

    async def close(self):
        tasks = list(self.tasks)
        for job in list(self.jobs.values()):
            self._expire(job.job_id)
        for task in tasks:
            if not task.done() and not task.cancelling():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


object_jobs = ObjectJobs()
