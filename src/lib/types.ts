// ═══════════════════════════════════════════
// ProctorAI — Core Type Definitions
// Every type here mirrors the real API contract.
// ═══════════════════════════════════════════

// ── Enums ──────────────────────────────────

export enum Role {
  Admin = 'Admin',
  HOD = 'HOD',
  Teacher = 'Teacher',
  ExamController = 'Exam Controller',
  Student = 'Student',
}

export enum CaseStatus {
  PendingReview = 'Pending Review',
  Confirmed = 'Confirmed',
  Dismissed = 'Dismissed',
  Escalated = 'Escalated',
}

export enum BehaviorType {
  GazeDeviation = 'Gaze Deviation',
  HeadPoseViolation = 'Head Pose Violation',
  LipMovement = 'Lip Movement',
  PhoneDetected = 'Phone Detected',
  UnauthorisedObject = 'Unauthorised Object',
}

export enum PenaltyType {
  FormalWarning = 'Formal Warning',
  MarkDeduction = 'Mark Deduction',
  ExamVoidance = 'Exam Voidance',
  DisciplinaryReferral = 'Disciplinary Referral',
  Suspension = 'Suspension',
  Other = 'Other',
}

export enum AppealStatus {
  Open = 'Open',
  Accepted = 'Accepted',
  Rejected = 'Rejected',
}

export enum SessionStatus {
  Scheduled = 'Scheduled',
  InProgress = 'In Progress',
  Completed = 'Completed',
  Cancelled = 'Cancelled',
}

// ── Core Entities ──────────────────────────

export interface User {
  id: string;
  name: string;
  email: string;
  role: Role;
  department: string;
  registrationNo?: string; // Students only
  status: 'Active' | 'Inactive';
  avatarUrl?: string;
  emailVerified?: boolean; // defaults to true for pre-provisioned/legacy accounts
  createdAt: string;
}

export interface Classroom {
  id: string;
  name: string;
  building: string;
  capacity: number;
  cameraId?: string;
  cameraStatus: 'Online' | 'Offline' | 'Maintenance';
  seatMap?: SeatPolygon[];
  createdAt: string;
}

export interface SeatPolygon {
  seatNumber: number;
  vertices: { x: number; y: number }[];
}

export interface ExamSession {
  id: string;
  courseCode: string;
  courseName: string;
  classroomId: string;
  classroomName: string;
  scheduledDate: string;
  startTime: string;
  endTime: string;
  status: SessionStatus;
  invigilatorId: string;
  invigilatorName: string;
  silentMode: boolean;
  totalSeats: number;
  occupiedSeats: number;
  alertCount: number;
  caseCount: number;
  createdAt: string;
}

export interface DetectionEvent {
  id: string;
  sessionId: string;
  seatNumber: number;
  studentId: string;
  studentName: string;
  behaviourTypes: BehaviorType[];
  perSignal: Partial<Record<BehaviorType, number>>;
  compositeScore: number;
  snapshotPath: string;
  detectedAt: string;
  status: 'New' | 'Reviewed' | 'Confirmed' | 'Dismissed';
}

export interface Case {
  id: string;
  referenceNo: string; // e.g., AU-CS-INT-2026-014
  sessionId: string;
  studentId: string;
  studentName: string;
  studentRegNo: string;
  courseCode: string;
  courseName: string;
  classroomName: string;
  seatNumber: number;
  behaviourTypes: BehaviorType[];
  compositeScore: number;
  status: CaseStatus;
  detectionEventId: string;
  snapshotPath: string;
  teacherNote?: string;
  teacherId: string;
  teacherName: string;
  hodId?: string;
  penalty?: Penalty;
  appeal?: Appeal;
  timeline: TimelineEntry[];
  createdAt: string;
  updatedAt: string;
}

export interface TimelineEntry {
  id: string;
  action: string;
  actorName: string;
  actorRole: Role;
  details?: string;
  timestamp: string;
}

export interface Penalty {
  id: string;
  caseId: string;
  type: PenaltyType;
  description: string;
  issuedBy: string;
  issuedByName: string;
  noticeReference: string;
  documentUrl?: string;
  createdAt: string;
}

export interface Appeal {
  id: string;
  caseId: string;
  studentId: string;
  studentName: string;
  studentRegNo: string;
  statement: string;
  supportingInfo?: string;
  status: AppealStatus;
  reviewedBy?: string;
  reviewerName?: string;
  reviewNote?: string;
  submittedAt: string;
  resolvedAt?: string;
}

// ── Evidence Media ─────────────────────────
// Mirrors GET /api/cases/{caseId}/media and GET /api/detections/{detectionId}/media.
// The backend returns snake_case; api.ts maps it to these camelCase shapes.
// Media URLs are short-lived signed URLs (about 5 minutes) and must be
// re-fetched when they expire.

export type ClipStatus = 'pending_upload' | 'available' | 'deleted_after_review';

export interface CaseMediaClip {
  url: string;
  expiresInSeconds: number;
  durationSeconds: number;
  sizeBytes: number;
  contentType: 'video/mp4';
}

export interface CaseMedia {
  caseId: string | null;
  detectionId: string;
  clipStatus: ClipStatus;
  clip: CaseMediaClip | null;      // non-null only when clipStatus === 'available'
  recordImageUrl: string | null;   // contact-sheet JPEG, present once the clip has been processed; kept permanently
  snapshotUrl: string | null;      // the single trigger-frame JPEG
  clipDeletedAt: string | null;    // ISO timestamp, set when clipStatus === 'deleted_after_review'
}

export interface ThresholdConfig {
  id: string;
  behaviorType: BehaviorType;
  sensitivity: number; // 0-100
  weight: number; // 0-1, contributes to composite score
  lastCalibrated: string;
  calibratedBy: string;
}

export interface AuditLogEntry {
  id: string;
  timestamp: string;
  userId: string;
  userName: string;
  userRole: Role;
  action: string;
  target: string;
  details: string;
  ipAddress: string;
}

export interface Notification {
  id: string;
  userId: string;
  title: string;
  message: string;
  type: 'alert' | 'case_update' | 'penalty' | 'appeal' | 'system';
  referenceId?: string;
  referenceType?: 'case' | 'appeal' | 'session';
  read: boolean;
  createdAt: string;
}

export interface ExamScheduleEntry {
  id: string;
  courseCode: string;
  courseName: string;
  department: string;
  date: string;
  startTime: string;
  endTime: string;
  classroomId: string;
  classroomName: string;
  invigilatorId?: string;
  invigilatorName?: string;
  status: SessionStatus;
  hasConflict?: boolean;
  conflictDetails?: string;
}

export interface InvigilatorAssignment {
  id: string;
  examId: string;
  teacherId: string;
  teacherName: string;
  department: string;
  courseCode: string;
  date: string;
  startTime: string;
  endTime: string;
  classroomName: string;
  status: 'Assigned' | 'Available' | 'Unavailable';
}

export interface StatisticalReport {
  incidentsByDepartment: { department: string; count: number }[];
  incidentsOverTime: { date: string; count: number }[];
  behaviorDistribution: { behavior: BehaviorType; count: number }[];
  caseStatusDistribution: { status: CaseStatus; count: number }[];
  totalCases: number;
  totalAppeals: number;
  appealSuccessRate: number;
  averageResolutionDays: number;
}

// ── API Response Types ─────────────────────

export interface ApiResponse<T> {
  data: T;
  message?: string;
}

export interface PaginatedResponse<T> {
  data: T[];
  total: number;
  page: number;
  pageSize: number;
}

export interface ApiError {
  message: string;
  code: string;
  status: number;
}

// ── Auth Types ─────────────────────────────

export interface LoginCredentials {
  email: string;
  password: string;
}

export interface AuthState {
  user: User | null;
  isAuthenticated: boolean;
  isLoading: boolean;
}
