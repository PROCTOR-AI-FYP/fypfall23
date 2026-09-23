// ═══════════════════════════════════════════
// ProctorAI API layer — the single typed boundary between the UI and the
// backend. Every exported function keeps the signature and return shape the
// pages were built against; internally each one calls the FastAPI backend
// and maps its snake_case wire format onto the camelCase types in types.ts.
// ═══════════════════════════════════════════

import { io, type Socket } from 'socket.io-client';
import type {
  User, Classroom, ExamSession, Case, Appeal, DetectionEvent,
  ThresholdConfig, AuditLogEntry, Notification, ExamScheduleEntry,
  InvigilatorAssignment, StatisticalReport, Penalty, CaseMedia,
  ApiResponse, PaginatedResponse, TimelineEntry, SeatPolygon,
} from './types';
import {
  Role, CaseStatus, BehaviorType, PenaltyType, AppealStatus, SessionStatus,
} from './types';

// ── HTTP client ────────────────────────────
// Every call sends the httpOnly session cookie (credentials: 'include') and,
// on state-changing methods, the CSRF header the backend requires.

// Empty string = same origin (e.g. a Vercel rewrite proxying /api to the API).
const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000').replace(/\/$/, '');
const CSRF_HEADER = 'X-ProctorAI-CSRF';
// Dispatched on any 401 outside /api/auth so the auth context can drop a dead session.
export const UNAUTHORIZED_EVENT = 'proctorai:unauthorized';

type Query = Record<string, string | number | boolean | undefined | null>;

interface RequestOptions {
  query?: Query;
  body?: unknown;
  form?: FormData;
}

function errorCode(status: number): string {
  if (status === 400 || status === 422) return 'VALIDATION_ERROR';
  if (status === 401) return 'AUTH_ERROR';
  if (status === 403) return 'FORBIDDEN';
  if (status === 404) return 'NOT_FOUND';
  if (status === 409) return 'CONFLICT';
  if (status === 413) return 'TOO_LARGE';
  if (status === 503) return 'UNAVAILABLE';
  return 'INTERNAL_ERROR';
}

function detailMessage(payload: unknown, status: number): string {
  const detail = (payload as { detail?: unknown } | null)?.detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail) && detail.length > 0) {
    const first = detail[0] as { msg?: string; loc?: unknown[] };
    const field = Array.isArray(first.loc) ? first.loc[first.loc.length - 1] : undefined;
    return first.msg ? `${field ? `${String(field)}: ` : ''}${first.msg}` : 'The request was not valid.';
  }
  return status >= 500 ? 'The server ran into a problem. Please try again.' : `Request failed (${status}).`;
}

async function request<T>(method: string, path: string, options: RequestOptions = {}): Promise<T> {
  const url = new URL(`${API_BASE_URL}${path}`, window.location.origin);
  for (const [key, value] of Object.entries(options.query ?? {})) {
    if (value !== undefined && value !== null && value !== '') url.searchParams.set(key, String(value));
  }

  const headers: Record<string, string> = { Accept: 'application/json' };
  if (method !== 'GET') headers[CSRF_HEADER] = '1';
  let body: BodyInit | undefined;
  if (options.form) {
    body = options.form;
  } else if (options.body !== undefined) {
    headers['Content-Type'] = 'application/json';
    body = JSON.stringify(options.body);
  }

  let response: Response;
  try {
    response = await fetch(url, { method, headers, body, credentials: 'include' });
  } catch {
    throw { message: 'Could not reach the ProctorAI server. Check your connection.', code: 'NETWORK_ERROR', status: 0 };
  }

  if (response.status === 204) return undefined as T;
  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    if (response.status === 401 && !path.startsWith('/api/auth/')) {
      window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
    }
    throw { message: detailMessage(payload, response.status), code: errorCode(response.status), status: response.status };
  }
  return payload as T;
}

function paginated<T>(data: T[]): PaginatedResponse<T> {
  return { data, total: data.length, page: 1, pageSize: data.length };
}

// ── Enum mapping ───────────────────────────

function invert<K extends string, V extends string>(map: Record<K, V>): Record<V, K> {
  return Object.fromEntries(Object.entries(map).map(([k, v]) => [v, k])) as Record<V, K>;
}

const ROLE_TO_API: Record<Role, string> = {
  [Role.Admin]: 'admin',
  [Role.HOD]: 'hod',
  [Role.Teacher]: 'teacher',
  [Role.ExamController]: 'exam_controller',
  [Role.Student]: 'student',
};
const ROLE_FROM_API = invert(ROLE_TO_API);

const CASE_STATUS_TO_API: Record<CaseStatus, string> = {
  [CaseStatus.PendingReview]: 'pending_review',
  [CaseStatus.Confirmed]: 'confirmed',
  [CaseStatus.Dismissed]: 'dismissed',
  [CaseStatus.Escalated]: 'escalated',
};
const CASE_STATUS_FROM_API = invert(CASE_STATUS_TO_API);

const BEHAVIOR_TO_API: Record<BehaviorType, string> = {
  [BehaviorType.GazeDeviation]: 'GAZE_DEVIATION',
  [BehaviorType.HeadPoseViolation]: 'HEAD_POSE_VIOLATION',
  [BehaviorType.LipMovement]: 'LIP_MOVEMENT',
  [BehaviorType.PhoneDetected]: 'PHONE_DETECTED',
  [BehaviorType.UnauthorisedObject]: 'UNAUTHORISED_OBJECT',
};
const BEHAVIOR_FROM_API = invert(BEHAVIOR_TO_API);

const PENALTY_TO_API: Record<PenaltyType, string> = {
  [PenaltyType.FormalWarning]: 'formal_warning',
  [PenaltyType.MarkDeduction]: 'mark_deduction',
  [PenaltyType.ExamVoidance]: 'exam_voidance',
  [PenaltyType.DisciplinaryReferral]: 'disciplinary_referral',
  [PenaltyType.Suspension]: 'suspension',
  [PenaltyType.Other]: 'other',
};
const PENALTY_FROM_API = invert(PENALTY_TO_API);

const APPEAL_STATUS_TO_API: Record<AppealStatus, string> = {
  [AppealStatus.Open]: 'open',
  [AppealStatus.Accepted]: 'accepted',
  [AppealStatus.Rejected]: 'rejected',
};
const APPEAL_STATUS_FROM_API = invert(APPEAL_STATUS_TO_API);

const SESSION_STATUS_TO_API: Record<SessionStatus, string> = {
  [SessionStatus.Scheduled]: 'scheduled',
  [SessionStatus.InProgress]: 'in_progress',
  [SessionStatus.Completed]: 'completed',
  [SessionStatus.Cancelled]: 'cancelled',
};
const SESSION_STATUS_FROM_API = invert(SESSION_STATUS_TO_API);

const CAMERA_TO_API: Record<Classroom['cameraStatus'], string> = {
  Online: 'online',
  Offline: 'offline',
  Maintenance: 'maintenance',
};
const CAMERA_FROM_API = invert(CAMERA_TO_API);

const ALERT_STATUS_FROM_API: Record<string, DetectionEvent['status']> = {
  new: 'New',
  reviewed: 'Reviewed',
  confirmed: 'Confirmed',
  dismissed: 'Dismissed',
};

const UNASSIGNED_SEAT = 'Unassigned seat';

// ── Wire formats and mappers ───────────────

interface ApiUser {
  id: string;
  full_name: string;
  email: string;
  role: string;
  department: string;
  registration_or_employee_no: string;
  status: 'active' | 'disabled';
  activated: boolean;
  created_at: string;
}

function toUser(u: ApiUser): User {
  const role = ROLE_FROM_API[u.role];
  return {
    id: u.id,
    name: u.full_name,
    email: u.email,
    role,
    department: u.department,
    registrationNo: role === Role.Student ? u.registration_or_employee_no : undefined,
    status: u.status === 'active' ? 'Active' : 'Inactive',
    emailVerified: true,
    activated: u.activated,
    createdAt: u.created_at,
  };
}

interface ApiSeatPolygon {
  seat_number: number;
  vertices: { x: number; y: number }[];
}

interface ApiClassroom {
  id: string;
  name: string;
  building: string;
  capacity: number;
  camera_id: string | null;
  camera_status: string;
  seat_map: ApiSeatPolygon[] | null;
  created_at: string;
}

function toClassroom(c: ApiClassroom): Classroom {
  return {
    id: c.id,
    name: c.name,
    building: c.building,
    capacity: c.capacity,
    cameraId: c.camera_id ?? undefined,
    cameraStatus: CAMERA_FROM_API[c.camera_status],
    seatMap: c.seat_map ? c.seat_map.map(s => ({ seatNumber: s.seat_number, vertices: s.vertices })) : undefined,
    createdAt: c.created_at,
  };
}

function seatMapToApi(seatMap: SeatPolygon[]): ApiSeatPolygon[] {
  return seatMap.map(s => ({ seat_number: s.seatNumber, vertices: s.vertices.map(v => ({ x: v.x, y: v.y })) }));
}

interface ApiSession {
  id: string;
  course_code: string;
  course_name: string;
  department: string;
  classroom_id: string | null;
  classroom_name: string;
  scheduled_date: string | null;
  start_time: string | null;
  end_time: string | null;
  status: string;
  invigilator_id: string | null;
  invigilator_name: string | null;
  silent_mode: boolean;
  total_seats: number;
  occupied_seats: number;
  alert_count: number;
  case_count: number;
  confirmed_case_count: number;
  created_at: string;
}

function toSession(s: ApiSession): ExamSession {
  return {
    id: s.id,
    courseCode: s.course_code,
    courseName: s.course_name,
    classroomId: s.classroom_id ?? '',
    classroomName: s.classroom_name,
    scheduledDate: s.scheduled_date ?? '',
    startTime: s.start_time ?? '',
    endTime: s.end_time ?? '',
    status: SESSION_STATUS_FROM_API[s.status],
    invigilatorId: s.invigilator_id ?? '',
    invigilatorName: s.invigilator_name ?? '',
    silentMode: s.silent_mode,
    totalSeats: s.total_seats,
    occupiedSeats: s.occupied_seats,
    alertCount: s.alert_count,
    // Session History's column is "Confirmed Cases".
    caseCount: s.confirmed_case_count,
    createdAt: s.created_at,
  };
}

interface ApiPenalty {
  id: string;
  case_id: string;
  penalty_type: string;
  description: string;
  issued_by: string;
  issued_by_name: string;
  notice_reference: string;
  created_at: string;
}

function toPenalty(p: ApiPenalty): Penalty {
  return {
    id: p.id,
    caseId: p.case_id,
    type: PENALTY_FROM_API[p.penalty_type],
    description: p.description,
    issuedBy: p.issued_by,
    issuedByName: p.issued_by_name,
    noticeReference: p.notice_reference,
    createdAt: p.created_at,
  };
}

interface ApiAppeal {
  id: string;
  case_id: string;
  student_id: string;
  student_name: string;
  student_reg_no: string;
  statement: string;
  supporting_info: string | null;
  status: string;
  reviewed_by: string | null;
  reviewer_name: string | null;
  review_note: string | null;
  submitted_at: string;
  resolved_at: string | null;
}

function toAppeal(a: ApiAppeal): Appeal {
  return {
    id: a.id,
    caseId: a.case_id,
    studentId: a.student_id,
    studentName: a.student_name,
    studentRegNo: a.student_reg_no,
    statement: a.statement,
    supportingInfo: a.supporting_info ?? undefined,
    status: APPEAL_STATUS_FROM_API[a.status],
    reviewedBy: a.reviewed_by ?? undefined,
    reviewerName: a.reviewer_name ?? undefined,
    reviewNote: a.review_note ?? undefined,
    submittedAt: a.submitted_at,
    resolvedAt: a.resolved_at ?? undefined,
  };
}

interface ApiTimelineEntry {
  id: string;
  action: string;
  actor_name: string;
  actor_role: string | null;
  details: string | null;
  timestamp: string;
}

function toTimelineEntry(t: ApiTimelineEntry): TimelineEntry {
  return {
    id: t.id,
    action: t.action,
    actorName: t.actor_name,
    actorRole: t.actor_role ? ROLE_FROM_API[t.actor_role] : null,
    details: t.details ?? undefined,
    timestamp: t.timestamp,
  };
}

interface ApiCase {
  id: string;
  reference_no: string;
  session_id: string;
  student_id: string | null;
  student_name: string | null;
  student_reg_no: string | null;
  course_code: string;
  course_name: string;
  classroom_name: string;
  seat_number: number;
  behaviour_types: string[];
  composite_score: number;
  status: string;
  detection_event_id: string | null;
  teacher_note: string | null;
  teacher_id: string | null;
  teacher_name: string | null;
  penalty: ApiPenalty | null;
  appeal: ApiAppeal | null;
  timeline: ApiTimelineEntry[];
  created_at: string;
  updated_at: string;
}

function toCase(c: ApiCase): Case {
  return {
    id: c.id,
    referenceNo: c.reference_no,
    sessionId: c.session_id,
    studentId: c.student_id ?? '',
    studentName: c.student_name ?? UNASSIGNED_SEAT,
    studentRegNo: c.student_reg_no ?? '',
    courseCode: c.course_code,
    courseName: c.course_name,
    classroomName: c.classroom_name,
    seatNumber: c.seat_number,
    behaviourTypes: c.behaviour_types.map(b => BEHAVIOR_FROM_API[b]),
    compositeScore: c.composite_score,
    status: CASE_STATUS_FROM_API[c.status],
    detectionEventId: c.detection_event_id ?? '',
    snapshotPath: '',
    teacherNote: c.teacher_note ?? undefined,
    teacherId: c.teacher_id ?? '',
    teacherName: c.teacher_name ?? '',
    penalty: c.penalty ? toPenalty(c.penalty) : undefined,
    appeal: c.appeal ? toAppeal(c.appeal) : undefined,
    timeline: c.timeline.map(toTimelineEntry),
    createdAt: c.created_at,
    updatedAt: c.updated_at,
  };
}

interface ApiDetection {
  id: string;
  session_id: string;
  seat_number: number;
  student_id: string | null;
  student_name: string | null;
  behaviour_types: string[];
  per_signal: Record<string, number>;
  composite_score: number;
  detected_at: string;
  status: string;
}

function toDetection(d: ApiDetection): DetectionEvent {
  const perSignal: Partial<Record<BehaviorType, number>> = {};
  for (const [signal, score] of Object.entries(d.per_signal)) perSignal[BEHAVIOR_FROM_API[signal]] = score;
  return {
    id: d.id,
    sessionId: d.session_id,
    seatNumber: d.seat_number,
    studentId: d.student_id ?? '',
    studentName: d.student_name ?? UNASSIGNED_SEAT,
    behaviourTypes: d.behaviour_types.map(b => BEHAVIOR_FROM_API[b]),
    perSignal,
    compositeScore: d.composite_score,
    snapshotPath: '',
    detectedAt: d.detected_at,
    status: ALERT_STATUS_FROM_API[d.status] ?? 'New',
  };
}

interface ApiScheduleEntry {
  id: string;
  course_code: string;
  course_name: string;
  department: string;
  date: string | null;
  start_time: string | null;
  end_time: string | null;
  classroom_id: string | null;
  classroom_name: string;
  invigilator_id: string | null;
  invigilator_name: string | null;
  status: string;
  has_conflict: boolean;
  conflict_details: string | null;
}

function toScheduleEntry(e: ApiScheduleEntry): ExamScheduleEntry {
  return {
    id: e.id,
    courseCode: e.course_code,
    courseName: e.course_name,
    department: e.department,
    date: e.date ?? '',
    startTime: e.start_time ?? '',
    endTime: e.end_time ?? '',
    classroomId: e.classroom_id ?? '',
    classroomName: e.classroom_name,
    invigilatorId: e.invigilator_id ?? undefined,
    invigilatorName: e.invigilator_name ?? undefined,
    status: SESSION_STATUS_FROM_API[e.status],
    hasConflict: e.has_conflict,
    conflictDetails: e.conflict_details ?? undefined,
  };
}

interface ApiAssignment {
  id: string;
  exam_id: string;
  teacher_id: string;
  teacher_name: string;
  department: string;
  course_code: string;
  date: string | null;
  start_time: string | null;
  end_time: string | null;
  classroom_name: string;
}

function toAssignment(a: ApiAssignment): InvigilatorAssignment {
  return {
    id: a.id,
    examId: a.exam_id,
    teacherId: a.teacher_id,
    teacherName: a.teacher_name,
    department: a.department,
    courseCode: a.course_code,
    date: a.date ?? '',
    startTime: a.start_time ?? '',
    endTime: a.end_time ?? '',
    classroomName: a.classroom_name,
    status: 'Assigned',
  };
}

// ── Auth API ───────────────────────────────

/** Trades a verified Supabase (Google) access token for the app's session cookie. */
export async function exchangeGoogleSession(supabaseAccessToken: string): Promise<ApiResponse<User>> {
  const user = await request<ApiUser>('POST', '/api/auth/session', { body: { supabase_access_token: supabaseAccessToken } });
  return { data: toUser(user) };
}

/** Who the httpOnly session cookie belongs to; 401 when there is no live session. */
export async function getCurrentUser(): Promise<ApiResponse<User>> {
  return { data: toUser(await request<ApiUser>('GET', '/api/auth/me')) };
}

export async function logout(): Promise<void> {
  await request<void>('POST', '/api/auth/logout');
}

// ── Users API ──────────────────────────────

export async function getUsers(filters?: { role?: Role; status?: string }): Promise<PaginatedResponse<User>> {
  const users = await request<ApiUser[]>('GET', '/api/admin/users', {
    query: {
      role: filters?.role ? ROLE_TO_API[filters.role] : undefined,
      status: filters?.status ? (filters.status === 'Active' ? 'active' : 'disabled') : undefined,
    },
  });
  return paginated(users.map(toUser));
}

function userToApi(data: Partial<User>): Record<string, unknown> {
  const body: Record<string, unknown> = {};
  if (data.name !== undefined) body.full_name = data.name;
  if (data.email !== undefined) body.email = data.email;
  if (data.role !== undefined) body.role = ROLE_TO_API[data.role];
  if (data.department !== undefined) body.department = data.department;
  if (data.status !== undefined) body.status = data.status === 'Inactive' ? 'disabled' : 'active';
  return body;
}

export async function createUser(data: Omit<User, 'id' | 'createdAt'>): Promise<ApiResponse<User>> {
  const user = await request<ApiUser>('POST', '/api/admin/users', { body: userToApi(data) });
  return { data: toUser(user), message: 'User created. The account activates on first Google sign-in.' };
}

export async function updateUser(id: string, data: Partial<User>): Promise<ApiResponse<User>> {
  const user = await request<ApiUser>('PATCH', `/api/admin/users/${id}`, { body: userToApi(data) });
  return { data: toUser(user), message: 'User updated successfully' };
}

export async function deleteUser(id: string): Promise<ApiResponse<null>> {
  await request<void>('DELETE', `/api/admin/users/${id}`);
  return { data: null, message: 'User deleted successfully' };
}

// ── Classrooms API ─────────────────────────

export async function getClassrooms(): Promise<PaginatedResponse<Classroom>> {
  return paginated((await request<ApiClassroom[]>('GET', '/api/classrooms')).map(toClassroom));
}

export async function getClassroom(id: string): Promise<ApiResponse<Classroom>> {
  return { data: toClassroom(await request<ApiClassroom>('GET', `/api/classrooms/${id}`)) };
}

function classroomToApi(data: Partial<Classroom>): Record<string, unknown> {
  const body: Record<string, unknown> = {};
  if (data.name !== undefined) body.name = data.name;
  if (data.building !== undefined) body.building = data.building;
  if (data.capacity !== undefined) body.capacity = data.capacity;
  if (data.cameraId !== undefined) body.camera_id = data.cameraId;
  if (data.cameraStatus !== undefined) body.camera_status = CAMERA_TO_API[data.cameraStatus];
  if (data.seatMap !== undefined) body.seat_map = seatMapToApi(data.seatMap);
  return body;
}

export async function createClassroom(data: Omit<Classroom, 'id' | 'createdAt'>): Promise<ApiResponse<Classroom>> {
  const classroom = await request<ApiClassroom>('POST', '/api/admin/classrooms', { body: classroomToApi(data) });
  return { data: toClassroom(classroom), message: 'Classroom created successfully' };
}

export async function updateClassroom(id: string, data: Partial<Classroom>): Promise<ApiResponse<Classroom>> {
  const classroom = await request<ApiClassroom>('PATCH', `/api/admin/classrooms/${id}`, { body: classroomToApi(data) });
  return { data: toClassroom(classroom), message: 'Classroom updated successfully' };
}

export async function deleteClassroom(id: string): Promise<ApiResponse<null>> {
  await request<void>('DELETE', `/api/admin/classrooms/${id}`);
  return { data: null, message: 'Classroom deleted successfully' };
}

// ── Sessions API ───────────────────────────

export async function getSessions(filters?: { status?: SessionStatus }): Promise<PaginatedResponse<ExamSession>> {
  const sessions = await request<ApiSession[]>('GET', '/api/sessions', {
    query: { status: filters?.status ? SESSION_STATUS_TO_API[filters.status] : undefined },
  });
  return paginated(sessions.map(toSession));
}

export async function getSession(id: string): Promise<ApiResponse<ExamSession>> {
  return { data: toSession(await request<ApiSession>('GET', `/api/sessions/${id}`)) };
}

/**
 * Starts the signed-in teacher's exam scheduled today in `data.classroomId`.
 * Course, times and invigilator come from the schedule, not from `data`.
 * A seat-map CSV, if given, is applied in the same step and must fully resolve.
 */
export async function createSession(data: Partial<ExamSession>, seatMapFile?: File): Promise<ApiResponse<ExamSession>> {
  const form = new FormData();
  form.set('classroom_id', data.classroomId ?? '');
  form.set('silent_mode', String(data.silentMode ?? false));
  if (seatMapFile) form.set('file', seatMapFile);
  const session = await request<ApiSession>('POST', '/api/sessions/start', { form });
  return { data: toSession(session), message: 'Session started' };
}

export async function endSession(id: string): Promise<ApiResponse<ExamSession>> {
  return { data: toSession(await request<ApiSession>('POST', `/api/sessions/${id}/end`)), message: 'Session ended' };
}

export interface SeatMapPreviewRow {
  seatNumber: string;
  studentRegNo: string;
  status: 'Resolved' | 'Unregistered ID' | 'Unverified';
}

/** Resolves a seat-map CSV against registered students; writes nothing. */
export async function previewSeatMap(file: File): Promise<ApiResponse<SeatMapPreviewRow[]>> {
  const form = new FormData();
  form.set('file', file);
  const result = await request<{ rows: { seat_number: number; student_reg_no: string; status: SeatMapPreviewRow['status'] }[] }>(
    'POST', '/api/seatmap/preview', { form },
  );
  return {
    data: result.rows.map(r => ({
      seatNumber: r.seat_number > 0 ? String(r.seat_number) : '—',
      studentRegNo: r.student_reg_no,
      status: r.status,
    })),
  };
}

// ── Cases API ──────────────────────────────

export async function getCases(filters?: {
  status?: CaseStatus;
  behaviorType?: BehaviorType;
  studentId?: string;
  courseCode?: string;
}): Promise<PaginatedResponse<Case>> {
  const cases = await request<ApiCase[]>('GET', '/api/cases', {
    query: {
      status: filters?.status ? CASE_STATUS_TO_API[filters.status] : undefined,
      behaviour_type: filters?.behaviorType ? BEHAVIOR_TO_API[filters.behaviorType] : undefined,
      student_id: filters?.studentId,
      course_code: filters?.courseCode,
    },
  });
  return paginated(cases.map(toCase));
}

export async function getCase(id: string): Promise<ApiResponse<Case>> {
  return { data: toCase(await request<ApiCase>('GET', `/api/cases/${id}`)) };
}

async function transition(id: string, toStatus: CaseStatus, note?: string): Promise<Case> {
  return toCase(await request<ApiCase>('POST', `/api/cases/${id}/transitions`, {
    body: { to_status: CASE_STATUS_TO_API[toStatus], note: note || null },
  }));
}

export async function confirmCase(id: string, note?: string): Promise<ApiResponse<Case>> {
  return { data: await transition(id, CaseStatus.Confirmed, note), message: 'Case confirmed' };
}

export async function dismissCase(id: string, reason?: string): Promise<ApiResponse<Case>> {
  return { data: await transition(id, CaseStatus.Dismissed, reason), message: 'Case dismissed' };
}

export async function escalateCase(id: string, reason?: string): Promise<ApiResponse<Case>> {
  return { data: await transition(id, CaseStatus.Escalated, reason), message: 'Case escalated' };
}

/** The invigilator confirms a live alert as a case; it goes to the HOD with their note. */
export async function createCaseFromDetection(detectionId: string, teacherNote: string): Promise<ApiResponse<Case>> {
  const confirmed = await request<ApiCase>('POST', `/api/detections/${detectionId}/confirm`, { body: { teacher_note: teacherNote } });
  return { data: toCase(confirmed), message: 'Case forwarded to the Head of Department' };
}

// ── Penalties API ──────────────────────────

/**
 * Issues a penalty. The backend only accepts a penalty on a confirmed case,
 * so a pending or escalated case is first confirmed by the HOD (a separate,
 * audited transition), exactly as issuing a decision implies.
 */
export async function issuePenalty(caseId: string, data: {
  type: PenaltyType;
  description: string;
  issuedBy: string;
  issuedByName: string;
}): Promise<ApiResponse<Penalty>> {
  const current = await request<ApiCase>('GET', `/api/cases/${caseId}`);
  if (current.status === 'pending_review' || current.status === 'escalated') {
    await transition(caseId, CaseStatus.Confirmed, 'Confirmed by the Head of Department on issuing a penalty');
  }
  const penalty = await request<ApiPenalty>('POST', `/api/cases/${caseId}/penalty`, {
    body: { penalty_type: PENALTY_TO_API[data.type], description: data.description },
  });
  return { data: toPenalty(penalty), message: 'Penalty issued successfully' };
}

// ── Appeals API ────────────────────────────

export async function getAppeals(filters?: { status?: AppealStatus }): Promise<PaginatedResponse<Appeal>> {
  const appeals = await request<ApiAppeal[]>('GET', '/api/appeals', {
    query: { status: filters?.status ? APPEAL_STATUS_TO_API[filters.status] : undefined },
  });
  return paginated(appeals.map(toAppeal));
}

export async function getAppeal(id: string): Promise<ApiResponse<Appeal>> {
  return { data: toAppeal(await request<ApiAppeal>('GET', `/api/appeals/${id}`)) };
}

/** The student is identified by the session, never by the fields passed here. */
export async function submitAppeal(caseId: string, data: {
  statement: string;
  supportingInfo?: string;
  studentId: string;
  studentName: string;
  studentRegNo: string;
}): Promise<ApiResponse<Appeal>> {
  const appeal = await request<ApiAppeal>('POST', `/api/cases/${caseId}/appeals`, {
    body: { statement: data.statement, supporting_info: data.supportingInfo || null },
  });
  return { data: toAppeal(appeal), message: 'Appeal submitted successfully' };
}

/** The reviewer is identified by the session, never by the fields passed here. */
export async function resolveAppeal(appealId: string, data: {
  status: AppealStatus.Accepted | AppealStatus.Rejected;
  reviewNote: string;
  reviewerName: string;
  reviewerId: string;
}): Promise<ApiResponse<Appeal>> {
  const appeal = await request<ApiAppeal>('POST', `/api/appeals/${appealId}/resolve`, {
    body: { status: APPEAL_STATUS_TO_API[data.status], review_note: data.reviewNote },
  });
  return { data: toAppeal(appeal), message: `Appeal ${data.status.toLowerCase()}` };
}

// ── Detection Events (alerts) API ──────────

/** Alerts for one session, or, without a session, every alert the user may see. */
export async function getDetectionEvents(sessionId?: string): Promise<PaginatedResponse<DetectionEvent>> {
  const detections = await request<ApiDetection[]>('GET', '/api/detections', { query: { session_id: sessionId } });
  return paginated(detections.map(toDetection));
}

export async function dismissDetection(id: string): Promise<ApiResponse<DetectionEvent>> {
  return { data: toDetection(await request<ApiDetection>('POST', `/api/detections/${id}/dismiss`, { body: {} })) };
}

// ── Live alerts (Socket.IO) ────────────────
// One shared connection, authenticated by the same httpOnly cookie. Teachers
// receive every alert from sessions they invigilate; passing a sessionId also
// joins that session's room (the Live Monitor).

let socket: Socket | null = null;

function getSocket(): Socket {
  if (!socket) {
    socket = io(API_BASE_URL || window.location.origin, { withCredentials: true, transports: ['websocket', 'polling'] });
  }
  return socket;
}

export function subscribeToAlerts(onAlert: (event: DetectionEvent) => void, options?: { sessionId?: string }): () => void {
  const connection = getSocket();
  const handler = (payload: ApiDetection) => onAlert(toDetection(payload));
  const join = () => {
    if (options?.sessionId) connection.emit('join_session', { session_id: options.sessionId });
  };
  connection.on('alert:new', handler);
  connection.on('connect', join);
  if (connection.connected) join();
  return () => {
    connection.off('alert:new', handler);
    connection.off('connect', join);
  };
}

// ── Evidence Media API ─────────────────────
// GET /api/cases/{caseId}/media and GET /api/detections/{detectionId}/media
// return short-lived signed Supabase Storage URLs (re-fetched on expiry).

interface ApiMedia {
  case_id: string | null;
  detection_id: string;
  clip_status: CaseMedia['clipStatus'];
  clip: { url: string; expires_in_seconds: number; duration_seconds: number; size_bytes: number; content_type: 'video/mp4' } | null;
  record_image_url: string | null;
  snapshot_url: string | null;
  clip_deleted_at: string | null;
}

function toMedia(m: ApiMedia): CaseMedia {
  return {
    caseId: m.case_id,
    detectionId: m.detection_id,
    clipStatus: m.clip_status,
    clip: m.clip
      ? {
          url: m.clip.url,
          expiresInSeconds: m.clip.expires_in_seconds,
          durationSeconds: m.clip.duration_seconds,
          sizeBytes: m.clip.size_bytes,
          contentType: m.clip.content_type,
        }
      : null,
    recordImageUrl: m.record_image_url,
    snapshotUrl: m.snapshot_url,
    clipDeletedAt: m.clip_deleted_at,
  };
}

export async function getCaseMedia(caseId: string): Promise<ApiResponse<CaseMedia>> {
  return { data: toMedia(await request<ApiMedia>('GET', `/api/cases/${caseId}/media`)) };
}

export async function getDetectionMedia(detectionId: string): Promise<ApiResponse<CaseMedia>> {
  return { data: toMedia(await request<ApiMedia>('GET', `/api/detections/${detectionId}/media`)) };
}

// ── Thresholds API ─────────────────────────

interface ApiThreshold {
  behaviour_type: string;
  sensitivity: number;
  weight: number;
  updated_at: string;
  updated_by_name: string | null;
}

export async function getThresholds(): Promise<ApiResponse<ThresholdConfig[]>> {
  const thresholds = await request<ApiThreshold[]>('GET', '/api/admin/thresholds');
  return {
    data: thresholds.map(t => ({
      id: t.behaviour_type,
      behaviorType: BEHAVIOR_FROM_API[t.behaviour_type],
      sensitivity: t.sensitivity,
      weight: t.weight,
      lastCalibrated: t.updated_at,
      calibratedBy: t.updated_by_name ?? 'System defaults',
    })),
  };
}

export async function updateThresholds(configs: ThresholdConfig[]): Promise<ApiResponse<ThresholdConfig[]>> {
  await request<ApiThreshold[]>('PUT', '/api/admin/thresholds', {
    body: configs.map(c => ({ behaviour_type: BEHAVIOR_TO_API[c.behaviorType], sensitivity: c.sensitivity, weight: c.weight })),
  });
  return { ...(await getThresholds()), message: 'Thresholds updated' };
}

// ── Audit Log API ──────────────────────────

interface ApiAuditEntry {
  id: string;
  timestamp: string;
  user_id: string | null;
  user_name: string;
  user_role: string | null;
  action: string;
  target: string;
  details: string;
  ip_address: string | null;
}

export async function getAuditLog(filters?: {
  action?: string;
  userId?: string;
  dateFrom?: string;
  dateTo?: string;
}): Promise<PaginatedResponse<AuditLogEntry>> {
  const entries = await request<ApiAuditEntry[]>('GET', '/api/admin/audit-log', {
    query: { action: filters?.action, user_id: filters?.userId, date_from: filters?.dateFrom, date_to: filters?.dateTo },
  });
  return paginated(entries.map(e => ({
    id: e.id,
    timestamp: e.timestamp,
    userId: e.user_id ?? '',
    userName: e.user_name,
    userRole: e.user_role ? ROLE_FROM_API[e.user_role] : null,
    action: e.action,
    target: e.target,
    details: e.details,
    ipAddress: e.ip_address ?? '',
  })));
}

// ── Notifications API ──────────────────────
// Always the signed-in user's own; the userId arguments are not sent.

interface ApiNotification {
  id: string;
  type: Notification['type'];
  title: string;
  message: string;
  reference_type: Notification['referenceType'] | null;
  reference_id: string | null;
  read: boolean;
  created_at: string;
}

export async function getNotifications(userId: string): Promise<PaginatedResponse<Notification>> {
  const notifications = await request<ApiNotification[]>('GET', '/api/notifications');
  return paginated(notifications.map(n => ({
    id: n.id,
    userId,
    title: n.title,
    message: n.message,
    type: n.type,
    referenceId: n.reference_id ?? undefined,
    referenceType: n.reference_type ?? undefined,
    read: n.read,
    createdAt: n.created_at,
  })));
}

export async function markNotificationRead(id: string): Promise<ApiResponse<null>> {
  await request<void>('POST', `/api/notifications/${id}/read`);
  return { data: null };
}

export async function markAllNotificationsRead(_userId: string): Promise<ApiResponse<null>> {
  await request<void>('POST', '/api/notifications/read-all');
  return { data: null };
}

// ── Exam Schedule API ──────────────────────

export async function getExamSchedule(): Promise<PaginatedResponse<ExamScheduleEntry>> {
  return paginated((await request<ApiScheduleEntry[]>('GET', '/api/exam-schedule')).map(toScheduleEntry));
}

function examToApi(data: Partial<ExamScheduleEntry>): Record<string, unknown> {
  const body: Record<string, unknown> = {};
  if (data.courseCode !== undefined) body.course_code = data.courseCode;
  if (data.courseName !== undefined) body.course_name = data.courseName;
  if (data.department !== undefined) body.department = data.department;
  if (data.date !== undefined) body.date = data.date;
  if (data.startTime !== undefined) body.start_time = data.startTime;
  if (data.endTime !== undefined) body.end_time = data.endTime;
  if (data.classroomId !== undefined) body.classroom_id = data.classroomId;
  return body;
}

export async function createExam(data: Omit<ExamScheduleEntry, 'id'>): Promise<ApiResponse<ExamScheduleEntry>> {
  const exam = toScheduleEntry(await request<ApiScheduleEntry>('POST', '/api/exam-schedule', { body: examToApi(data) }));
  return { data: exam, message: exam.hasConflict ? 'Exam created with conflicts' : 'Exam created successfully' };
}

export async function updateExam(id: string, data: Partial<ExamScheduleEntry>): Promise<ApiResponse<ExamScheduleEntry>> {
  return { data: toScheduleEntry(await request<ApiScheduleEntry>('PATCH', `/api/exam-schedule/${id}`, { body: examToApi(data) })), message: 'Exam updated' };
}

export async function deleteExam(id: string): Promise<ApiResponse<null>> {
  await request<void>('DELETE', `/api/exam-schedule/${id}`);
  return { data: null, message: 'Exam cancelled' };
}

// ── Invigilator Assignments API ────────────

export async function getAssignments(): Promise<PaginatedResponse<InvigilatorAssignment>> {
  return paginated((await request<ApiAssignment[]>('GET', '/api/invigilator-assignments')).map(toAssignment));
}

export async function assignInvigilator(examId: string, teacherId: string): Promise<ApiResponse<InvigilatorAssignment>> {
  const assignment = await request<ApiAssignment>('POST', `/api/exam-schedule/${examId}/invigilator`, { body: { teacher_id: teacherId } });
  return { data: toAssignment(assignment), message: 'Invigilator assigned' };
}

// ── Statistical Reports API ────────────────

interface ApiStatistics {
  incidents_by_department: { label: string; count: number }[];
  incidents_over_time: { label: string; count: number }[];
  behavior_distribution: { label: string; count: number }[];
  case_status_distribution: { label: string; count: number }[];
  total_cases: number;
  total_appeals: number;
  appeal_success_rate: number;
  average_resolution_days: number;
}

export async function getStatisticalReports(): Promise<ApiResponse<StatisticalReport>> {
  const s = await request<ApiStatistics>('GET', '/api/reports/statistics');
  return {
    data: {
      incidentsByDepartment: s.incidents_by_department.map(d => ({ department: d.label, count: d.count })),
      incidentsOverTime: s.incidents_over_time.map(d => ({ date: d.label, count: d.count })),
      behaviorDistribution: s.behavior_distribution.map(d => ({ behavior: BEHAVIOR_FROM_API[d.label], count: d.count })),
      caseStatusDistribution: s.case_status_distribution.map(d => ({ status: CASE_STATUS_FROM_API[d.label], count: d.count })),
      totalCases: s.total_cases,
      totalAppeals: s.total_appeals,
      appealSuccessRate: s.appeal_success_rate,
      averageResolutionDays: s.average_resolution_days,
    },
  };
}
