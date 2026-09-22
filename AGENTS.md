# AGENTS.md — ProctorAI

Read this file in full at the start of every session before writing any code. It is the persistent source of truth across sessions — the build prompt you were given is the kickoff instruction; this file is what keeps every session after that consistent with it. If something here conflicts with an instruction given mid-session, this file wins unless the person explicitly says they're changing a decision recorded here — if they do, update this file in the same session so the change persists.

Reference docs in `/docs/` (read these too if present): `master-plan.md` (full project scope, backend architecture, infra decisions), `frontend-spec.html` (exhaustive page/element inventory — nothing on it may be dropped). This file is the condensed, always-loaded version of both.

---

## 1. What this product is

ProctorAI is an AI exam-proctoring platform for a university pilot. A ceiling-mounted camera per exam hall detects five behaviors (gaze deviation, head-pose violation, lip movement during silent exams, phone detection, unauthorised objects), and confirmed incidents move through a real academic-integrity workflow: teacher review → HOD penalty → automated notice → student appeal.

Five user roles, real institutional stakes: **Teacher** (invigilating, needs calm clarity under pressure), **HOD** (issues consequences that affect a student's record), **Exam Controller** (schedules exams, assigns invigilators), **Admin** (configures system sensitivity), **Student** (can be wrongly accused — the system must feel fair, not punitive by default).

Design tone: closer to an instrument panel for a high-stakes, evidentiary process than a generic SaaS dashboard. Never default to a template look — see §4.

---

## 2. Current phase — do not skip ahead

**Phase 1 (active): Frontend only, against a mock API layer.** No backend exists yet. Every screen must be fully functional against `src/lib/api.ts` mock implementations that mirror the real contract in §6 exactly, so Phase 2 (backend) is a swap of the implementation behind that interface, not a rewrite of any component.

**Phase 2 (later): Backend integration.** Do not start building FastAPI/Postgres/Redis/Mosquitto code unless explicitly asked — that phase begins only once the frontend is approved.

---

## 3. Tech stack (locked — do not substitute)

Vite + React 18 + TypeScript + Tailwind CSS · React Router · React Three Fiber + drei (3D, §5 only) · Recharts · Socket.io-client (mocked event emitter in Phase 1) · `src/lib/api.ts` as the single typed boundary between UI and data — nothing outside this file knows whether data is mocked or real.

---

## 4. Design mandate (condensed — full detail in the build prompt)

- No cream+terracotta, no near-black+acid-green, no identical-rounded-card SaaS kit, no ALL-CAPS eyebrows, no middle-dot meta strings, no spaced-em-dash labels, no decorative monospace, no "→" on every button, no fade-slide-up on every card.
- A 4–6 color token system + two typefaces with distinct roles must be defined in `/docs/design-tokens.md` before component work starts. If that file doesn't exist yet, write it first.
- Status/behavior colors (§7 glossary) must be distinguishable without relying on color alone (pair with icon/shape).
- Respect `prefers-reduced-motion` everywhere; visible keyboard focus on every interactive element.
- Light/Dark/System theme toggle, persisted, no flash-of-wrong-theme on load. Both modes designed together, not dark-as-inverted-light.

---

## 5. 3D elements — exactly three places, nowhere else

1. Login screen hero (signature moment, sets tone)
2. Live Monitor seat grid — optional 3D/perspective mode, 2D flat grid remains default
3. Confirmation moments on Penalty Modal and Appeal resolution — brief, restrained, skipped under reduced-motion

Do not add 3D anywhere not listed here.

---

## 6. Data contracts — build the mock layer to match these exactly

**Roles:** Admin, HOD, Teacher, Exam Controller, Student

**Case status:** Pending Review, Confirmed, Dismissed, Escalated

**Behavior types:** Gaze Deviation, Head Pose Violation, Lip Movement, Phone Detected, Unauthorised Object

**Penalty types:** Formal Warning, Mark Deduction, Exam Voidance, Disciplinary Referral, Suspension, Other

**Appeal status:** Open, Accepted, Rejected

**Exam session status:** Scheduled, In Progress, Completed, Cancelled

**Notice reference format:** `AU-CS-INT-2026-014` style

**Core detection event shape** (mock this; real backend will emit the same shape later):
```jsonc
{
  "session_id": "uuid", "seat_number": 14,
  "behaviour_types": ["PHONE_DETECTED", "HEAD_POSE_VIOLATION"],
  "per_signal": { "PHONE_DETECTED": 0.91, "HEAD_POSE_VIOLATION": 0.68 },
  "composite_score": 0.90,
  "snapshot_path": "snapshots/<session>/<uuid>.jpg",
  "detected_at": "ISO timestamp"
}
```
Case, appeal, and user objects should carry the fields implied by the pages in §7 (student name/reg. no., seat, course, room, teacher note, timeline entries, etc.) — infer full shapes from what each page in the spec needs to render, and keep them consistent across every screen that reuses the same entity.

---

## 7. Full page manifest (24 screens — none are stubs)

**Global:** Login · App Shell (role-aware sidebar/header, notification bell, user menu) · Notifications Panel

**Admin:** Dashboard · User Management · Classroom Management · Seat Polygon Editor · Threshold Configuration · Audit Log Viewer

**HOD:** Dashboard · Case Management · Case Detail · Penalty Modal · Appeal Review

**Teacher:** Session Setup · Live Monitor · Alert Inbox · Session Report

**Student:** My Cases · Case Detail (read-only) · Appeal Form

**Exam Controller:** Exam Schedule · Invigilator Assignment · Session History · Statistical Reports

---

## 8. Hard rules

- Frontend route guards enforce role access even in Phase 1 (mirrors the backend RBAC that's coming — don't build screens a role shouldn't reach and leave them reachable).
- Every table/list/form has real empty, loading, and error states — not just the happy path.
- No Lorem Ipsum, no "Item 1/2/3" — use realistic ProctorAI-context fixture data (real-sounding names, course codes, case IDs).
- Commit after each portal is fully working end to end against the mock layer — not one commit for the whole app.
- Never mark a page "done" if any element from the §7 manifest (or the fuller `/docs/frontend-spec.html`) is missing from it.
- Update this file when a locked decision changes (stack, contract shape, design tokens finalized) — future sessions read this file, not the chat history.

---

## 9. Commands

`npm install` · `npm run dev` · `npm run build` · `npm run lint` — add test commands here once tests exist.
