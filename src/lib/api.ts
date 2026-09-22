// ═══════════════════════════════════════════
// ProctorAI Mock API Layer
// Every function matches the real FastAPI contract.
// Artificial latency (200-500ms) + 5% error rate.
// ═══════════════════════════════════════════

import type {
  User, Classroom, ExamSession, Case, Appeal, DetectionEvent,
  ThresholdConfig, AuditLogEntry, Notification, ExamScheduleEntry,
  InvigilatorAssignment, StatisticalReport, Penalty, CaseMedia,
  ApiResponse, PaginatedResponse,
} from './types';
import {
  Role, CaseStatus, BehaviorType, PenaltyType, AppealStatus, SessionStatus,
} from './types';
import {
  users as fixtureUsers,
  classrooms as fixtureClassrooms,
  examSessions as fixtureSessions,
  cases as fixtureCases,
  detectionEvents as fixtureDetections,
  thresholdConfigs as fixtureThresholds,
  auditLog as fixtureAuditLog,
  notifications as fixtureNotifications,
  examSchedule as fixtureExamSchedule,
  invigilatorAssignments as fixtureAssignments,
} from './fixtures';

// ── Auth / signup constants ────────────────

// All new self-service and admin-provisioned accounts use this single
// institutional domain. Legacy fixture users (@au.edu.pk / @student.au.edu.pk)
// remain untouched — they represent already-provisioned accounts.
export const ALLOWED_EMAIL_DOMAIN = 'students.au.edu.pk';

const STUDENT_LOCAL_PART_PATTERN = /^\d{6}$/;

interface PendingVerification {
  token: string;
  email: string;
  fullName: string;
  password: string;
  createdAt: number;
  expiresAt: number;
  consumed: boolean;
}

// ── Mutable in-memory stores ───────────────

let _users = [...fixtureUsers];
let _classrooms = [...fixtureClassrooms];
let _sessions = [...fixtureSessions];
let _cases = [...fixtureCases];
let _detections = [...fixtureDetections];
let _thresholds = [...fixtureThresholds];
let _auditLog = [...fixtureAuditLog];
let _notifications = [...fixtureNotifications];
let _examSchedule = [...fixtureExamSchedule];
let _assignments = [...fixtureAssignments];
let _pendingVerifications: PendingVerification[] = [];

// ── Helpers ────────────────────────────────

function delay(): Promise<void> {
  const ms = 200 + Math.random() * 300;
  return new Promise(resolve => setTimeout(resolve, ms));
}

function maybeError(): void {
  if (Math.random() < 0.05) {
    throw { message: 'Internal server error', code: 'INTERNAL_ERROR', status: 500 };
  }
}

function generateId(prefix: string): string {
  return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 6)}`;
}

// Validates the institutional email + local-part rule shared by signup and
// resendVerification. Throws the same 422-shaped errors either mock consumer
// would need to surface as input validation (these ARE meant to be visible —
// they are not part of the identity-leak axis).
function assertSelfServiceSignupEmail(email: string): string {
  const atIdx = email.indexOf('@');
  const localPart = atIdx === -1 ? email : email.slice(0, atIdx);
  const domain = atIdx === -1 ? '' : email.slice(atIdx + 1);

  if (domain !== ALLOWED_EMAIL_DOMAIN) {
    throw { message: 'Please sign up with your university email.', code: 'INVALID_DOMAIN', status: 422 };
  }
  if (!STUDENT_LOCAL_PART_PATTERN.test(localPart)) {
    throw {
      message: 'This account type is created by an administrator — contact your department.',
      code: 'STAFF_SIGNUP_BLOCKED',
      status: 422,
    };
  }
  return localPart;
}

function throwInvalidOrExpiredToken(): never {
  throw { message: 'This link is invalid or has expired.', code: 'INVALID_TOKEN', status: 400 };
}

// ── Auth API ───────────────────────────────

export async function login(email: string, _password: string): Promise<ApiResponse<User>> {
  await delay();
  const user = _users.find(u => u.email === email);
  if (!user) throw { message: 'Invalid credentials', code: 'AUTH_ERROR', status: 401 };
  if (user.emailVerified === false) {
    throw { message: 'Please verify your email before signing in.', code: 'EMAIL_NOT_VERIFIED', status: 403 };
  }
  return { data: user };
}

export async function getCurrentUser(userId: string): Promise<ApiResponse<User>> {
  await delay();
  const user = _users.find(u => u.id === userId);
  if (!user) throw { message: 'User not found', code: 'NOT_FOUND', status: 404 };
  return { data: user };
}

// ── Signup / Email Verification API ────────
// Mirrors the future backend contract: role is never client-supplied.
// A 6-digit local part under ALLOWED_EMAIL_DOMAIN => self-service Student
// signup. Anything else is staff, provisioned only by an Admin (no public
// signup path). Responses never reveal whether an email already has an
// account — every code path below resolves/throws identically regardless.

export async function signup(fullName: string, email: string, _password: string): Promise<ApiResponse<{ message: string }>> {
  await delay();
  assertSelfServiceSignupEmail(email);

  // Always create/refresh a pending verification record — this happens
  // identically whether or not the email already belongs to an account, so
  // it cannot be used to distinguish the two cases from the outside.
  const token = generateId('vtok');
  _pendingVerifications = _pendingVerifications.filter(p => p.email !== email);
  _pendingVerifications.push({
    token,
    email,
    fullName,
    password: _password,
    createdAt: Date.now(),
    expiresAt: Date.now() + 1000 * 60 * 30,
    consumed: false,
  });
  // Dev convenience only (Phase 1 has no real email delivery); logged
  // unconditionally so it can't leak account existence via timing/branching.
  console.info(`[mock] Verification link for ${email}: /verify-email?token=${token}`);

  return { data: { message: 'If this email is valid, a verification link has been sent.' } };
}

export async function verifyEmail(token: string): Promise<ApiResponse<{ message: string }>> {
  await delay();
  const idx = _pendingVerifications.findIndex(p => p.token === token);
  if (idx === -1) throwInvalidOrExpiredToken();

  const record = _pendingVerifications[idx];
  if (record.consumed || Date.now() > record.expiresAt) throwInvalidOrExpiredToken();

  _pendingVerifications[idx] = { ...record, consumed: true };

  const existingIdx = _users.findIndex(u => u.email === record.email);
  if (existingIdx !== -1) {
    _users[existingIdx] = { ..._users[existingIdx], emailVerified: true };
  } else {
    const newUser: User = {
      id: generateId('usr'),
      name: record.fullName,
      email: record.email,
      role: Role.Student,
      department: '',
      registrationNo: record.email.split('@')[0],
      status: 'Active',
      emailVerified: true,
      createdAt: new Date().toISOString(),
    };
    _users.push(newUser);
  }

  return { data: { message: 'Email verified — you can now sign in.' } };
}

export async function resendVerification(email: string): Promise<ApiResponse<{ message: string }>> {
  await delay();
  assertSelfServiceSignupEmail(email);

  const token = generateId('vtok');
  const existing = _pendingVerifications.find(p => p.email === email);
  _pendingVerifications = _pendingVerifications.filter(p => p.email !== email);
  _pendingVerifications.push({
    token,
    email,
    fullName: existing?.fullName || '',
    password: existing?.password || '',
    createdAt: Date.now(),
    expiresAt: Date.now() + 1000 * 60 * 30,
    consumed: false,
  });
  console.info(`[mock] Verification link for ${email}: /verify-email?token=${token}`);

  return { data: { message: 'If this email is valid, a verification link has been sent.' } };
}

// ── Users API ──────────────────────────────

export async function getUsers(filters?: { role?: Role; status?: string }): Promise<PaginatedResponse<User>> {
  await delay();
  maybeError();
  let result = [..._users];
  if (filters?.role) result = result.filter(u => u.role === filters.role);
  if (filters?.status) result = result.filter(u => u.status === filters.status);
  return { data: result, total: result.length, page: 1, pageSize: 50 };
}

export async function createUser(data: Omit<User, 'id' | 'createdAt'>): Promise<ApiResponse<User>> {
  await delay();
  maybeError();
  const user: User = {
    ...data,
    id: generateId('usr'),
    createdAt: new Date().toISOString(),
  };
  _users.push(user);
  return { data: user, message: 'User created successfully' };
}

export async function updateUser(id: string, data: Partial<User>): Promise<ApiResponse<User>> {
  await delay();
  maybeError();
  const idx = _users.findIndex(u => u.id === id);
  if (idx === -1) throw { message: 'User not found', code: 'NOT_FOUND', status: 404 };
  _users[idx] = { ..._users[idx], ...data };
  return { data: _users[idx], message: 'User updated successfully' };
}

export async function deleteUser(id: string): Promise<ApiResponse<null>> {
  await delay();
  maybeError();
  _users = _users.filter(u => u.id !== id);
  return { data: null, message: 'User deleted successfully' };
}

// ── Classrooms API ─────────────────────────

export async function getClassrooms(): Promise<PaginatedResponse<Classroom>> {
  await delay();
  maybeError();
  return { data: [..._classrooms], total: _classrooms.length, page: 1, pageSize: 50 };
}

export async function getClassroom(id: string): Promise<ApiResponse<Classroom>> {
  await delay();
  const cls = _classrooms.find(c => c.id === id);
  if (!cls) throw { message: 'Classroom not found', code: 'NOT_FOUND', status: 404 };
  return { data: cls };
}

export async function createClassroom(data: Omit<Classroom, 'id' | 'createdAt'>): Promise<ApiResponse<Classroom>> {
  await delay();
  maybeError();
  const classroom: Classroom = {
    ...data,
    id: generateId('cls'),
    createdAt: new Date().toISOString(),
  };
  _classrooms.push(classroom);
  return { data: classroom, message: 'Classroom created successfully' };
}

export async function updateClassroom(id: string, data: Partial<Classroom>): Promise<ApiResponse<Classroom>> {
  await delay();
  maybeError();
  const idx = _classrooms.findIndex(c => c.id === id);
  if (idx === -1) throw { message: 'Classroom not found', code: 'NOT_FOUND', status: 404 };
  _classrooms[idx] = { ..._classrooms[idx], ...data };
  return { data: _classrooms[idx], message: 'Classroom updated successfully' };
}

export async function deleteClassroom(id: string): Promise<ApiResponse<null>> {
  await delay();
  _classrooms = _classrooms.filter(c => c.id !== id);
  return { data: null, message: 'Classroom deleted successfully' };
}

// ── Sessions API ───────────────────────────

export async function getSessions(filters?: { status?: SessionStatus }): Promise<PaginatedResponse<ExamSession>> {
  await delay();
  maybeError();
  let result = [..._sessions];
  if (filters?.status) result = result.filter(s => s.status === filters.status);
  return { data: result, total: result.length, page: 1, pageSize: 50 };
}

export async function getSession(id: string): Promise<ApiResponse<ExamSession>> {
  await delay();
  const session = _sessions.find(s => s.id === id);
  if (!session) throw { message: 'Session not found', code: 'NOT_FOUND', status: 404 };
  return { data: session };
}

export async function createSession(data: Partial<ExamSession>): Promise<ApiResponse<ExamSession>> {
  await delay();
  maybeError();
  const session: ExamSession = {
    id: generateId('ses'),
    courseCode: data.courseCode || '',
    courseName: data.courseName || '',
    classroomId: data.classroomId || '',
    classroomName: data.classroomName || '',
    scheduledDate: data.scheduledDate || '',
    startTime: data.startTime || '',
    endTime: data.endTime || '',
    status: SessionStatus.InProgress,
    invigilatorId: data.invigilatorId || '',
    invigilatorName: data.invigilatorName || '',
    silentMode: data.silentMode || false,
    totalSeats: data.totalSeats || 0,
    occupiedSeats: data.occupiedSeats || 0,
    alertCount: 0,
    caseCount: 0,
    createdAt: new Date().toISOString(),
  };
  _sessions.push(session);
  return { data: session, message: 'Session started' };
}

export async function endSession(id: string): Promise<ApiResponse<ExamSession>> {
  await delay();
  const idx = _sessions.findIndex(s => s.id === id);
  if (idx === -1) throw { message: 'Session not found', code: 'NOT_FOUND', status: 404 };
  _sessions[idx] = { ..._sessions[idx], status: SessionStatus.Completed };
  return { data: _sessions[idx], message: 'Session ended' };
}

// ── Cases API ──────────────────────────────

export async function getCases(filters?: {
  status?: CaseStatus;
  behaviorType?: BehaviorType;
  studentId?: string;
  courseCode?: string;
}): Promise<PaginatedResponse<Case>> {
  await delay();
  maybeError();
  let result = [..._cases];
  if (filters?.status) result = result.filter(c => c.status === filters.status);
  if (filters?.behaviorType) result = result.filter(c => c.behaviourTypes.includes(filters.behaviorType!));
  if (filters?.studentId) result = result.filter(c => c.studentId === filters.studentId);
  if (filters?.courseCode) result = result.filter(c => c.courseCode === filters.courseCode);
  return { data: result, total: result.length, page: 1, pageSize: 50 };
}

export async function getCase(id: string): Promise<ApiResponse<Case>> {
  await delay();
  const c = _cases.find(c => c.id === id);
  if (!c) throw { message: 'Case not found', code: 'NOT_FOUND', status: 404 };
  return { data: c };
}

export async function confirmCase(id: string, note?: string): Promise<ApiResponse<Case>> {
  await delay();
  maybeError();
  const idx = _cases.findIndex(c => c.id === id);
  if (idx === -1) throw { message: 'Case not found', code: 'NOT_FOUND', status: 404 };
  _cases[idx] = {
    ..._cases[idx],
    status: CaseStatus.Confirmed,
    teacherNote: note || _cases[idx].teacherNote,
    updatedAt: new Date().toISOString(),
    timeline: [
      ..._cases[idx].timeline,
      {
        id: generateId('tl'),
        action: 'Case confirmed',
        actorName: 'Current User',
        actorRole: Role.Teacher,
        details: note || 'Case confirmed by invigilator',
        timestamp: new Date().toISOString(),
      },
    ],
  };
  return { data: _cases[idx], message: 'Case confirmed' };
}

export async function dismissCase(id: string, reason?: string): Promise<ApiResponse<Case>> {
  await delay();
  const idx = _cases.findIndex(c => c.id === id);
  if (idx === -1) throw { message: 'Case not found', code: 'NOT_FOUND', status: 404 };
  _cases[idx] = {
    ..._cases[idx],
    status: CaseStatus.Dismissed,
    updatedAt: new Date().toISOString(),
    timeline: [
      ..._cases[idx].timeline,
      {
        id: generateId('tl'),
        action: 'Case dismissed',
        actorName: 'Current User',
        actorRole: Role.HOD,
        details: reason || 'Case dismissed',
        timestamp: new Date().toISOString(),
      },
    ],
  };
  return { data: _cases[idx], message: 'Case dismissed' };
}

export async function escalateCase(id: string, reason?: string): Promise<ApiResponse<Case>> {
  await delay();
  const idx = _cases.findIndex(c => c.id === id);
  if (idx === -1) throw { message: 'Case not found', code: 'NOT_FOUND', status: 404 };
  _cases[idx] = {
    ..._cases[idx],
    status: CaseStatus.Escalated,
    updatedAt: new Date().toISOString(),
    timeline: [
      ..._cases[idx].timeline,
      {
        id: generateId('tl'),
        action: 'Case escalated',
        actorName: 'Current User',
        actorRole: Role.Teacher,
        details: reason || 'Escalated to HOD',
        timestamp: new Date().toISOString(),
      },
    ],
  };
  return { data: _cases[idx], message: 'Case escalated' };
}

export async function createCaseFromDetection(detectionId: string, teacherNote: string): Promise<ApiResponse<Case>> {
  await delay();
  maybeError();
  const detection = _detections.find(d => d.id === detectionId);
  if (!detection) throw { message: 'Detection not found', code: 'NOT_FOUND', status: 404 };

  const caseNum = _cases.length + 1;
  const newCase: Case = {
    id: generateId('case'),
    referenceNo: `AU-CS-INT-2026-${String(caseNum).padStart(3, '0')}`,
    sessionId: detection.sessionId,
    studentId: detection.studentId,
    studentName: detection.studentName,
    studentRegNo: _users.find(u => u.id === detection.studentId)?.registrationNo || '',
    courseCode: _sessions.find(s => s.id === detection.sessionId)?.courseCode || '',
    courseName: _sessions.find(s => s.id === detection.sessionId)?.courseName || '',
    classroomName: _sessions.find(s => s.id === detection.sessionId)?.classroomName || '',
    seatNumber: detection.seatNumber,
    behaviourTypes: detection.behaviourTypes,
    compositeScore: detection.compositeScore,
    status: CaseStatus.PendingReview,
    detectionEventId: detection.id,
    snapshotPath: detection.snapshotPath,
    teacherNote,
    teacherId: 'current-user',
    teacherName: 'Current Teacher',
    timeline: [
      {
        id: generateId('tl'),
        action: 'Case created from detection alert',
        actorName: 'Current Teacher',
        actorRole: Role.Teacher,
        details: teacherNote,
        timestamp: new Date().toISOString(),
      },
    ],
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  };
  _cases.push(newCase);

  // Update detection status
  const detIdx = _detections.findIndex(d => d.id === detectionId);
  if (detIdx !== -1) _detections[detIdx] = { ..._detections[detIdx], status: 'Confirmed' };

  return { data: newCase, message: 'Case created successfully' };
}

// ── Penalties API ──────────────────────────

export async function issuePenalty(caseId: string, data: {
  type: PenaltyType;
  description: string;
  issuedBy: string;
  issuedByName: string;
}): Promise<ApiResponse<Penalty>> {
  await delay();
  maybeError();
  const caseIdx = _cases.findIndex(c => c.id === caseId);
  if (caseIdx === -1) throw { message: 'Case not found', code: 'NOT_FOUND', status: 404 };

  const penalty: Penalty = {
    id: generateId('pen'),
    caseId,
    type: data.type,
    description: data.description,
    issuedBy: data.issuedBy,
    issuedByName: data.issuedByName,
    noticeReference: _cases[caseIdx].referenceNo,
    createdAt: new Date().toISOString(),
  };

  _cases[caseIdx] = {
    ..._cases[caseIdx],
    penalty,
    status: CaseStatus.Confirmed,
    updatedAt: new Date().toISOString(),
    timeline: [
      ..._cases[caseIdx].timeline,
      {
        id: generateId('tl'),
        action: `Penalty issued: ${data.type}`,
        actorName: data.issuedByName,
        actorRole: Role.HOD,
        details: data.description,
        timestamp: new Date().toISOString(),
      },
    ],
  };

  return { data: penalty, message: 'Penalty issued successfully' };
}

// ── Appeals API ────────────────────────────

export async function getAppeals(filters?: { status?: AppealStatus }): Promise<PaginatedResponse<Appeal>> {
  await delay();
  maybeError();
  const appeals = _cases
    .filter(c => c.appeal)
    .map(c => c.appeal!)
    .filter(a => !filters?.status || a.status === filters.status);
  return { data: appeals, total: appeals.length, page: 1, pageSize: 50 };
}

export async function getAppeal(id: string): Promise<ApiResponse<Appeal>> {
  await delay();
  const appeal = _cases.find(c => c.appeal?.id === id)?.appeal;
  if (!appeal) throw { message: 'Appeal not found', code: 'NOT_FOUND', status: 404 };
  return { data: appeal };
}

export async function submitAppeal(caseId: string, data: {
  statement: string;
  supportingInfo?: string;
  studentId: string;
  studentName: string;
  studentRegNo: string;
}): Promise<ApiResponse<Appeal>> {
  await delay();
  maybeError();
  const caseIdx = _cases.findIndex(c => c.id === caseId);
  if (caseIdx === -1) throw { message: 'Case not found', code: 'NOT_FOUND', status: 404 };

  const appeal: Appeal = {
    id: generateId('apl'),
    caseId,
    studentId: data.studentId,
    studentName: data.studentName,
    studentRegNo: data.studentRegNo,
    statement: data.statement,
    supportingInfo: data.supportingInfo,
    status: AppealStatus.Open,
    submittedAt: new Date().toISOString(),
  };

  _cases[caseIdx] = {
    ..._cases[caseIdx],
    appeal,
    updatedAt: new Date().toISOString(),
    timeline: [
      ..._cases[caseIdx].timeline,
      {
        id: generateId('tl'),
        action: 'Appeal submitted',
        actorName: data.studentName,
        actorRole: Role.Student,
        details: 'Student submitted an appeal',
        timestamp: new Date().toISOString(),
      },
    ],
  };

  return { data: appeal, message: 'Appeal submitted successfully' };
}

export async function resolveAppeal(appealId: string, data: {
  status: AppealStatus.Accepted | AppealStatus.Rejected;
  reviewNote: string;
  reviewerName: string;
  reviewerId: string;
}): Promise<ApiResponse<Appeal>> {
  await delay();
  maybeError();
  const caseIdx = _cases.findIndex(c => c.appeal?.id === appealId);
  if (caseIdx === -1) throw { message: 'Appeal not found', code: 'NOT_FOUND', status: 404 };

  const updatedAppeal: Appeal = {
    ..._cases[caseIdx].appeal!,
    status: data.status,
    reviewNote: data.reviewNote,
    reviewerName: data.reviewerName,
    reviewedBy: data.reviewerId,
    resolvedAt: new Date().toISOString(),
  };

  _cases[caseIdx] = {
    ..._cases[caseIdx],
    appeal: updatedAppeal,
    status: data.status === AppealStatus.Accepted ? CaseStatus.Dismissed : _cases[caseIdx].status,
    updatedAt: new Date().toISOString(),
    timeline: [
      ..._cases[caseIdx].timeline,
      {
        id: generateId('tl'),
        action: `Appeal ${data.status.toLowerCase()}`,
        actorName: data.reviewerName,
        actorRole: Role.HOD,
        details: data.reviewNote,
        timestamp: new Date().toISOString(),
      },
    ],
  };

  return { data: updatedAppeal, message: `Appeal ${data.status.toLowerCase()}` };
}

// ── Detection Events API ───────────────────

export async function getDetectionEvents(sessionId: string): Promise<PaginatedResponse<DetectionEvent>> {
  await delay();
  const result = _detections.filter(d => d.sessionId === sessionId);
  return { data: result, total: result.length, page: 1, pageSize: 100 };
}

export async function dismissDetection(id: string): Promise<ApiResponse<DetectionEvent>> {
  await delay();
  const idx = _detections.findIndex(d => d.id === id);
  if (idx === -1) throw { message: 'Detection not found', code: 'NOT_FOUND', status: 404 };
  _detections[idx] = { ..._detections[idx], status: 'Dismissed' };
  return { data: _detections[idx] };
}

// ── Evidence Media API ─────────────────────
// Mirrors GET /api/cases/{caseId}/media and GET /api/detections/{detectionId}/media.
// Real backend: 403 for roles that cannot review, 404 when a teacher is not
// the invigilator of the session. The mock does not model the caller's
// identity; frontend route guards cover role access in Phase 1.

const MOCK_CLIP_PATH = '/mock-media/sample-clip.mp4';
const MOCK_RECORD_IMAGE_PATH = '/mock-media/sample-record.jpg';
const MOCK_CLIP_DURATION_SECONDS = 10;
const MOCK_CLIP_SIZE_BYTES = 306665;
const MEDIA_URL_TTL_SECONDS = 300;

// The one detection whose clip is still being processed, so the
// 'pending_upload' state is reachable in the UI. Applies to both endpoints
// (the case built from this detection reports the same state).
const PENDING_UPLOAD_DETECTION_ID = 'det-003';

// Imitates a short-lived signed URL: every fetch returns a fresh URL, just as
// the real backend does. Static hosting ignores the query string.
function mockSignedUrl(path: string): string {
  const expires = Math.floor(Date.now() / 1000) + MEDIA_URL_TTL_SECONDS;
  const signature = Math.random().toString(36).slice(2, 12);
  return `${path}?expires=${expires}&signature=${signature}`;
}

function buildMockMedia(detectionId: string, linkedCase: Case | undefined): CaseMedia {
  const base = {
    caseId: linkedCase?.id ?? null,
    detectionId,
    snapshotUrl: null,
  };

  if (detectionId === PENDING_UPLOAD_DETECTION_ID) {
    return { ...base, clipStatus: 'pending_upload', clip: null, recordImageUrl: null, clipDeletedAt: null };
  }

  const reviewFinalised =
    !!linkedCase &&
    (linkedCase.status === CaseStatus.Dismissed ||
      (linkedCase.status === CaseStatus.Confirmed && !!linkedCase.penalty));

  if (reviewFinalised) {
    return {
      ...base,
      clipStatus: 'deleted_after_review',
      clip: null,
      recordImageUrl: mockSignedUrl(MOCK_RECORD_IMAGE_PATH),
      clipDeletedAt: linkedCase.updatedAt,
    };
  }

  return {
    ...base,
    clipStatus: 'available',
    clip: {
      url: mockSignedUrl(MOCK_CLIP_PATH),
      expiresInSeconds: MEDIA_URL_TTL_SECONDS,
      durationSeconds: MOCK_CLIP_DURATION_SECONDS,
      sizeBytes: MOCK_CLIP_SIZE_BYTES,
      contentType: 'video/mp4',
    },
    recordImageUrl: mockSignedUrl(MOCK_RECORD_IMAGE_PATH),
    clipDeletedAt: null,
  };
}

export async function getCaseMedia(caseId: string): Promise<ApiResponse<CaseMedia>> {
  await delay();
  maybeError();
  const c = _cases.find(c => c.id === caseId);
  if (!c) throw { message: 'Case not found', code: 'NOT_FOUND', status: 404 };
  return { data: buildMockMedia(c.detectionEventId, c) };
}

export async function getDetectionMedia(detectionId: string): Promise<ApiResponse<CaseMedia>> {
  await delay();
  maybeError();
  const detection = _detections.find(d => d.id === detectionId);
  if (!detection) throw { message: 'Detection not found', code: 'NOT_FOUND', status: 404 };
  const linkedCase = _cases.find(c => c.detectionEventId === detectionId);
  return { data: buildMockMedia(detectionId, linkedCase) };
}

// ── Thresholds API ─────────────────────────

export async function getThresholds(): Promise<ApiResponse<ThresholdConfig[]>> {
  await delay();
  maybeError();
  return { data: [..._thresholds] };
}

export async function updateThresholds(configs: ThresholdConfig[]): Promise<ApiResponse<ThresholdConfig[]>> {
  await delay();
  maybeError();
  _thresholds = configs.map(c => ({ ...c, lastCalibrated: new Date().toISOString() }));
  return { data: _thresholds, message: 'Thresholds updated' };
}

// ── Audit Log API ──────────────────────────

export async function getAuditLog(filters?: {
  action?: string;
  userId?: string;
  dateFrom?: string;
  dateTo?: string;
}): Promise<PaginatedResponse<AuditLogEntry>> {
  await delay();
  maybeError();
  let result = [..._auditLog];
  if (filters?.action) result = result.filter(a => a.action.includes(filters.action!));
  if (filters?.userId) result = result.filter(a => a.userId === filters.userId);
  if (filters?.dateFrom) result = result.filter(a => a.timestamp >= filters.dateFrom!);
  if (filters?.dateTo) result = result.filter(a => a.timestamp <= filters.dateTo!);
  result.sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime());
  return { data: result, total: result.length, page: 1, pageSize: 50 };
}

// ── Notifications API ──────────────────────

export async function getNotifications(userId: string): Promise<PaginatedResponse<Notification>> {
  await delay();
  const result = _notifications.filter(n => n.userId === userId);
  result.sort((a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime());
  return { data: result, total: result.length, page: 1, pageSize: 50 };
}

export async function markNotificationRead(id: string): Promise<ApiResponse<null>> {
  await delay();
  const idx = _notifications.findIndex(n => n.id === id);
  if (idx !== -1) _notifications[idx] = { ..._notifications[idx], read: true };
  return { data: null };
}

export async function markAllNotificationsRead(userId: string): Promise<ApiResponse<null>> {
  await delay();
  _notifications = _notifications.map(n =>
    n.userId === userId ? { ...n, read: true } : n
  );
  return { data: null };
}

// ── Exam Schedule API ──────────────────────

export async function getExamSchedule(): Promise<PaginatedResponse<ExamScheduleEntry>> {
  await delay();
  maybeError();
  return { data: [..._examSchedule], total: _examSchedule.length, page: 1, pageSize: 50 };
}

export async function createExam(data: Omit<ExamScheduleEntry, 'id'>): Promise<ApiResponse<ExamScheduleEntry>> {
  await delay();
  maybeError();

  // Check for conflicts
  const conflict = _examSchedule.find(e =>
    e.date === data.date &&
    e.classroomId === data.classroomId &&
    e.id !== data.courseCode && // don't conflict with self
    ((data.startTime >= e.startTime && data.startTime < e.endTime) ||
     (data.endTime > e.startTime && data.endTime <= e.endTime))
  );

  const exam: ExamScheduleEntry = {
    ...data,
    id: generateId('exam'),
    hasConflict: !!conflict,
    conflictDetails: conflict ? `Conflicts with ${conflict.courseCode} in ${conflict.classroomName}` : undefined,
  };
  _examSchedule.push(exam);
  return { data: exam, message: conflict ? 'Exam created with conflicts' : 'Exam created successfully' };
}

export async function updateExam(id: string, data: Partial<ExamScheduleEntry>): Promise<ApiResponse<ExamScheduleEntry>> {
  await delay();
  const idx = _examSchedule.findIndex(e => e.id === id);
  if (idx === -1) throw { message: 'Exam not found', code: 'NOT_FOUND', status: 404 };
  _examSchedule[idx] = { ..._examSchedule[idx], ...data };
  return { data: _examSchedule[idx], message: 'Exam updated' };
}

export async function deleteExam(id: string): Promise<ApiResponse<null>> {
  await delay();
  _examSchedule = _examSchedule.filter(e => e.id !== id);
  return { data: null, message: 'Exam cancelled' };
}

// ── Invigilator Assignments API ────────────

export async function getAssignments(): Promise<PaginatedResponse<InvigilatorAssignment>> {
  await delay();
  maybeError();
  return { data: [..._assignments], total: _assignments.length, page: 1, pageSize: 50 };
}

export async function assignInvigilator(examId: string, teacherId: string): Promise<ApiResponse<InvigilatorAssignment>> {
  await delay();
  maybeError();
  const teacher = _users.find(u => u.id === teacherId);
  const exam = _examSchedule.find(e => e.id === examId);
  if (!teacher || !exam) throw { message: 'Not found', code: 'NOT_FOUND', status: 404 };

  const assignment: InvigilatorAssignment = {
    id: generateId('asn'),
    examId,
    teacherId,
    teacherName: teacher.name,
    department: teacher.department,
    courseCode: exam.courseCode,
    date: exam.date,
    startTime: exam.startTime,
    endTime: exam.endTime,
    classroomName: exam.classroomName,
    status: 'Assigned',
  };
  _assignments.push(assignment);

  // Update exam schedule
  const examIdx = _examSchedule.findIndex(e => e.id === examId);
  if (examIdx !== -1) {
    _examSchedule[examIdx] = {
      ..._examSchedule[examIdx],
      invigilatorId: teacherId,
      invigilatorName: teacher.name,
      hasConflict: false,
      conflictDetails: undefined,
    };
  }

  return { data: assignment, message: 'Invigilator assigned' };
}

// ── Statistical Reports API ────────────────

export async function getStatisticalReports(): Promise<ApiResponse<StatisticalReport>> {
  await delay();
  maybeError();

  const report: StatisticalReport = {
    incidentsByDepartment: [
      { department: 'Computer Science', count: 18 },
      { department: 'Software Engineering', count: 9 },
      { department: 'Electrical Engineering', count: 5 },
      { department: 'Mechanical Engineering', count: 3 },
    ],
    incidentsOverTime: [
      { date: '2026-09-01', count: 2 },
      { date: '2026-09-05', count: 4 },
      { date: '2026-09-08', count: 1 },
      { date: '2026-09-10', count: 6 },
      { date: '2026-09-12', count: 3 },
      { date: '2026-09-15', count: 8 },
      { date: '2026-09-18', count: 5 },
      { date: '2026-09-20', count: 7 },
      { date: '2026-09-22', count: 4 },
    ],
    behaviorDistribution: [
      { behavior: BehaviorType.GazeDeviation, count: 12 },
      { behavior: BehaviorType.HeadPoseViolation, count: 8 },
      { behavior: BehaviorType.LipMovement, count: 6 },
      { behavior: BehaviorType.PhoneDetected, count: 9 },
      { behavior: BehaviorType.UnauthorisedObject, count: 5 },
    ],
    caseStatusDistribution: [
      { status: CaseStatus.PendingReview, count: 4 },
      { status: CaseStatus.Confirmed, count: 3 },
      { status: CaseStatus.Dismissed, count: 2 },
      { status: CaseStatus.Escalated, count: 1 },
    ],
    totalCases: _cases.length,
    totalAppeals: _cases.filter(c => c.appeal).length,
    appealSuccessRate: 0.33,
    averageResolutionDays: 2.4,
  };

  return { data: report };
}
