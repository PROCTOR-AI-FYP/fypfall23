"""Role-gated, preview-first CSV setup imports. No schema migrations required."""
from __future__ import annotations

import secrets

import asyncpg
from fastapi import APIRouter, Depends, Form, HTTPException, Request

from app.deps import CurrentUser, get_db, require_role
from app.models import Role
from app.services.csv_imports import HEADERS, MAX_BYTES, apply_plan, build_plan

router = APIRouter(prefix="/api/imports",tags=["imports"])
require_importer = require_role(Role.ADMIN, Role.EXAM_CONTROLLER)


async def _files(request: Request, actor: CurrentUser) -> dict[str, bytes]:
    form = await request.form(max_files=4,max_fields=4,max_part_size=MAX_BYTES)
    files = {}
    for key,value in form.multi_items():
        if key == "preview_hash" and isinstance(value,str):
            continue
        if key not in HEADERS or key in files or not hasattr(value,"read"):
            raise HTTPException(422,"Use one CSV file per supported template type.")
        if actor.role != Role.ADMIN and key in ("student_roster","classroom_inventory"):
            raise HTTPException(403,"Only administrators can import student accounts or classrooms.")
        if not (value.filename or "").lower().endswith('.csv'):
            raise HTTPException(422,"Upload CSV files only.")
        raw = await value.read(MAX_BYTES+1)
        if len(raw)>MAX_BYTES:
            raise HTTPException(413,"Each CSV must be at most 256 KB.")
        files[key] = raw
    if not files:
        raise HTTPException(422,"Choose at least one CSV file.")
    return files


@router.post('/preview')
async def preview_import(request: Request, actor: CurrentUser = Depends(require_importer), conn:asyncpg.Connection=Depends(get_db)):
    files = await _files(request,actor)
    async with conn.transaction(isolation="repeatable_read",readonly=True):
        return (await build_plan(conn,files)).public()


@router.post('/commit')
async def commit_import(request: Request, preview_hash:str=Form(min_length=64,max_length=64),
                        actor:CurrentUser=Depends(require_importer),conn:asyncpg.Connection=Depends(get_db)):
    files = await _files(request,actor)
    async with conn.transaction():
        # Serializes overlapping imports and existing CRUD writes until the complete
        # validated batch commits. These are short bounded administration operations.
        await conn.execute('LOCK TABLE users,classrooms,exam_sessions IN SHARE ROW EXCLUSIVE MODE')
        plan = await build_plan(conn,files)
        if plan.public()['counts']['error']:
            raise HTTPException(409,"The batch contains errors. Preview again and fix every rejected row; nothing was imported.")
        if not secrets.compare_digest(plan.fingerprint,preview_hash):
            raise HTTPException(409,"Files or related records changed since preview. Preview again before importing; nothing was imported.")
        try:
            created = await apply_plan(conn,plan,actor,request)
        except asyncpg.IntegrityConstraintViolationError as exc:
            raise HTTPException(409,"A conflicting record was found. Preview again; the complete batch was rolled back.") from exc
    return {"created":created,"skipped":plan.public()['counts']['skip'],"message":"Import completed."}
