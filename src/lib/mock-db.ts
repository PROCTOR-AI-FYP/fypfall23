// ═══════════════════════════════════════════
// ProctorAI — In-memory mock database (Phase 1)
// Mirrors the seed.sql fixture data. Used by api.ts when the backend is
// unreachable so every page renders with realistic data.
// ═══════════════════════════════════════════

import {
  Role, CaseStatus, BehaviorType, PenaltyType, AppealStatus, SessionStatus,
} from './types';
import type {
  User, Classroom, ExamSession, Case, Appeal, DetectionEvent,
  ThresholdConfig, AuditLogEntry, Notification, ExamScheduleEntry,
  InvigilatorAssignment, StatisticalReport, Penalty, TimelineEntry, SeatPolygon,
} from './types';

// ── Helpers ────────────────────────────────

export function uid(prefix = '') {
  return `${prefix}${Math.random().toString(36).slice(2, 10)}`;
}

function iso(daysAgo = 0, hoursAgo = 0) {
  const d = new Date();
  d.setDate(d.getDate() - daysAgo);
  d.setHours(d.getHours() - hoursAgo);
  return d.toISOString();
}

// ── Users ──────────────────────────────────

export const MOCK_USERS: User[] = [
  {
    id: 'usr-student-1',
    name: 'Ayesha Raza',
    email: '232475@students.au.edu.pk',
    role: Role.Student,
    department: 'Computer Science',
    registrationNo: '232475',
    status: 'Active',
    emailVerified: true,
    activated: true,
    createdAt: iso(90),
  },
  {
    id: 'usr-student-2',
    name: 'Bilal Ahmed',
    email: '232490@students.au.edu.pk',
    role: Role.Student,
    department: 'Computer Science',
    registrationNo: '232490',
    status: 'Active',
    emailVerified: true,
    activated: true,
    createdAt: iso(90),
  },
  {
    id: 'usr-teacher-1',
    name: 'Dr. M. Bilal',
    email: 'm.bilal@au.edu.pk',
    role: Role.Teacher,
    department: 'Computer Science',
    status: 'Active',
    emailVerified: true,
    activated: true,
    createdAt: iso(365),
  },
  {
    id: 'usr-hod-1',
    name: 'Dr. Sara Khan',
    email: 'hod.cs@au.edu.pk',
    role: Role.HOD,
    department: 'Computer Science',
    status: 'Active',
    emailVerified: true,
    activated: true,
    createdAt: iso(365),
  },
  {
    id: 'usr-admin-1',
    name: 'Admin Registrar',
    email: 'admin.registrar@au.edu.pk',
    role: Role.Admin,
    department: 'IT Services',
    status: 'Active',
    emailVerified: true,
    activated: true,
    createdAt: iso(365),
  },
  {
    id: 'usr-controller-1',
    name: 'Usman Tariq',
    email: 'controller.exams@au.edu.pk',
    role: Role.ExamController,
    department: 'Examination Branch',
    status: 'Active',
    emailVerified: true,
    activated: true,
    createdAt: iso(365),
  },
  {
    id: 'usr-student-3',
    name: 'Zara Malik',
    email: '232501@students.au.edu.pk',
    role: Role.Student,
    department: 'Computer Science',
    registrationNo: '232501',
    status: 'Active',
    emailVerified: true,
    activated: false,
    createdAt: iso(30),
  },
];

export function findUserByEmail(email: string): User | undefined {
  return MOCK_USERS.find(u => u.email.toLowerCase() === email.toLowerCase());
}

export function findUserById(id: string): User | undefined {
  return MOCK_USERS.find(u => u.id === id);
}

// ── Classrooms ─────────────────────────────

const SEAT_MAP_A: SeatPolygon[] = Array.from({ length: 60 }, (_, i) => ({
  seatNumber: i + 1,
  vertices: [
    { x: (i % 6) * 100 + 10, y: Math.floor(i / 6) * 80 + 10 },
    { x: (i % 6) * 100 + 90, y: Math.floor(i / 6) * 80 + 10 },
    { x: (i % 6) * 100 + 90, y: Math.floor(i / 6) * 80 + 70 },
    { x: (i % 6) * 100 + 10, y: Math.floor(i / 6) * 80 + 70 },
  ],
}));

export const MOCK_CLASSROOMS: Classroom[] = [
  {
    id: 'cls-hall-a',
    name: 'Hall-A',
    building: 'Main Academic Block',
    capacity: 60,
    cameraId: 'cam-hall-a',
    cameraStatus: 'Online',
    seatMap: SEAT_MAP_A,
    createdAt: iso(400),
  },
  {
    id: 'cls-lh-4',
    name: 'LH-4',
    building: 'Block A',
    capacity: 48,
    cameraId: 'cam-lh-4',
    cameraStatus: 'Online',
    createdAt: iso(400),
  },
  {
    id: 'cls-lh-7',
    name: 'LH-7',
    building: 'Block B',
    capacity: 40,
    cameraId: 'cam-lh-7',
    cameraStatus: 'Maintenance',
    createdAt: iso(400),
  },
];

// ── Penalties ──────────────────────────────

export const MOCK_PENALTIES: Penalty[] = [
  {
    id: 'pen-001',
    caseId: 'case-001',
    type: PenaltyType.FormalWarning,
    description: 'Formal warning issued for confirmed phone use during examination. First offence on record.',
    issuedBy: 'usr-hod-1',
    issuedByName: 'Dr. Sara Khan',
    noticeReference: 'AU-CS-INT-2026-014',
    createdAt: iso(10),
  },
];

// ── Appeals ────────────────────────────────

export const MOCK_APPEALS: Appeal[] = [
  {
    id: 'appeal-001',
    caseId: 'case-001',
    studentId: 'usr-student-1',
    studentName: 'Ayesha Raza',
    studentRegNo: '232475',
    statement: 'I did not have a phone during the examination. The detected object was my calculator, which is permitted. I request the evidence be reviewed.',
    supportingInfo: 'My calculator is a Casio FX-991ES which resembles a smartphone in shape.',
    status: AppealStatus.Open,
    submittedAt: iso(7),
  },
];

// ── Timeline entries ────────────────────────

const TL_CASE_001: TimelineEntry[] = [
  { id: 'tl-001-1', action: 'Case Created', actorName: 'System', actorRole: null, details: 'Detection event flagged during CS-4402 exam.', timestamp: iso(15, 3) },
  { id: 'tl-001-2', action: 'Case Confirmed', actorName: 'Dr. M. Bilal', actorRole: Role.Teacher, details: 'Phone clearly visible in snapshot. Seat 14.', timestamp: iso(15) },
  { id: 'tl-001-3', action: 'Penalty Issued', actorName: 'Dr. Sara Khan', actorRole: Role.HOD, details: 'Formal Warning — First offence. Notice AU-CS-INT-2026-014 dispatched.', timestamp: iso(10) },
  { id: 'tl-001-4', action: 'Appeal Filed', actorName: 'Ayesha Raza', actorRole: Role.Student, details: 'Student disputes detection; claims object is a calculator.', timestamp: iso(7) },
];

const TL_CASE_002: TimelineEntry[] = [
  { id: 'tl-002-1', action: 'Case Created', actorName: 'System', actorRole: null, details: 'Detection event flagged during CS-4402 exam.', timestamp: iso(15, 2) },
  { id: 'tl-002-2', action: 'Case Escalated', actorName: 'Dr. M. Bilal', actorRole: Role.Teacher, details: 'Gaze deviation repeated 4 times. Escalating to HOD.', timestamp: iso(14) },
];

const TL_CASE_003: TimelineEntry[] = [
  { id: 'tl-003-1', action: 'Case Created', actorName: 'System', actorRole: null, timestamp: iso(5, 1) },
  { id: 'tl-003-2', action: 'Case Dismissed', actorName: 'Dr. M. Bilal', actorRole: Role.Teacher, details: 'Student was adjusting glasses — false positive.', timestamp: iso(5) },
];

// ── Cases ──────────────────────────────────

export const MOCK_CASES: Case[] = [
  {
    id: 'case-001',
    referenceNo: 'AU-CS-INT-2026-014',
    sessionId: 'sess-001',
    studentId: 'usr-student-1',
    studentName: 'Ayesha Raza',
    studentRegNo: '232475',
    courseCode: 'CS-4402',
    courseName: 'Compiler Construction',
    classroomName: 'Hall-A',
    seatNumber: 14,
    behaviourTypes: [BehaviorType.PhoneDetected],
    compositeScore: 0.91,
    status: CaseStatus.Confirmed,
    detectionEventId: 'det-001',
    snapshotPath: 'snapshots/sess-001/det-001.jpg',
    teacherNote: 'Phone clearly visible in snapshot. Seat 14, row 2.',
    teacherId: 'usr-teacher-1',
    teacherName: 'Dr. M. Bilal',
    hodId: 'usr-hod-1',
    penalty: MOCK_PENALTIES[0],
    appeal: MOCK_APPEALS[0],
    timeline: TL_CASE_001,
    createdAt: iso(15),
    updatedAt: iso(7),
  },
  {
    id: 'case-002',
    referenceNo: 'AU-CS-INT-2026-015',
    sessionId: 'sess-001',
    studentId: 'usr-student-2',
    studentName: 'Bilal Ahmed',
    studentRegNo: '232490',
    courseCode: 'CS-4402',
    courseName: 'Compiler Construction',
    classroomName: 'Hall-A',
    seatNumber: 15,
    behaviourTypes: [BehaviorType.GazeDeviation, BehaviorType.HeadPoseViolation],
    compositeScore: 0.76,
    status: CaseStatus.Escalated,
    detectionEventId: 'det-002',
    snapshotPath: 'snapshots/sess-001/det-002.jpg',
    teacherNote: 'Gaze deviation repeated 4 times in 10 minutes.',
    teacherId: 'usr-teacher-1',
    teacherName: 'Dr. M. Bilal',
    timeline: TL_CASE_002,
    createdAt: iso(15),
    updatedAt: iso(14),
  },
  {
    id: 'case-003',
    referenceNo: 'AU-CS-INT-2026-016',
    sessionId: 'sess-002',
    studentId: 'usr-student-3',
    studentName: 'Zara Malik',
    studentRegNo: '232501',
    courseCode: 'CS-3301',
    courseName: 'Operating Systems',
    classroomName: 'LH-4',
    seatNumber: 7,
    behaviourTypes: [BehaviorType.GazeDeviation],
    compositeScore: 0.52,
    status: CaseStatus.Dismissed,
    detectionEventId: 'det-003',
    snapshotPath: 'snapshots/sess-002/det-003.jpg',
    teacherNote: 'Student adjusting glasses — false positive.',
    teacherId: 'usr-teacher-1',
    teacherName: 'Dr. M. Bilal',
    timeline: TL_CASE_003,
    createdAt: iso(5),
    updatedAt: iso(5),
  },
  {
    id: 'case-004',
    referenceNo: 'AU-CS-INT-2026-017',
    sessionId: 'sess-003',
    studentId: 'usr-student-1',
    studentName: 'Ayesha Raza',
    studentRegNo: '232475',
    courseCode: 'CS-3301',
    courseName: 'Operating Systems',
    classroomName: 'LH-4',
    seatNumber: 3,
    behaviourTypes: [BehaviorType.LipMovement],
    compositeScore: 0.68,
    status: CaseStatus.PendingReview,
    detectionEventId: 'det-004',
    snapshotPath: 'snapshots/sess-003/det-004.jpg',
    teacherId: 'usr-teacher-1',
    teacherName: 'Dr. M. Bilal',
    timeline: [{ id: 'tl-004-1', action: 'Case Created', actorName: 'System', actorRole: null, details: 'Lip movement detected during silent exam.', timestamp: iso(2) }],
    createdAt: iso(2),
    updatedAt: iso(2),
  },
];

// ── Detection Events ────────────────────────

export const MOCK_DETECTIONS: DetectionEvent[] = [
  { id: 'det-001', sessionId: 'sess-001', seatNumber: 14, studentId: 'usr-student-1', studentName: 'Ayesha Raza', behaviourTypes: [BehaviorType.PhoneDetected], perSignal: { [BehaviorType.PhoneDetected]: 0.91 }, compositeScore: 0.91, snapshotPath: 'snapshots/sess-001/det-001.jpg', detectedAt: iso(15, 3), status: 'Confirmed' },
  { id: 'det-002', sessionId: 'sess-001', seatNumber: 15, studentId: 'usr-student-2', studentName: 'Bilal Ahmed', behaviourTypes: [BehaviorType.GazeDeviation, BehaviorType.HeadPoseViolation], perSignal: { [BehaviorType.GazeDeviation]: 0.72, [BehaviorType.HeadPoseViolation]: 0.68 }, compositeScore: 0.76, snapshotPath: 'snapshots/sess-001/det-002.jpg', detectedAt: iso(15, 2), status: 'Confirmed' },
  { id: 'det-003', sessionId: 'sess-002', seatNumber: 7, studentId: 'usr-student-3', studentName: 'Zara Malik', behaviourTypes: [BehaviorType.GazeDeviation], perSignal: { [BehaviorType.GazeDeviation]: 0.52 }, compositeScore: 0.52, snapshotPath: 'snapshots/sess-002/det-003.jpg', detectedAt: iso(5, 1), status: 'Dismissed' },
  { id: 'det-004', sessionId: 'sess-003', seatNumber: 3, studentId: 'usr-student-1', studentName: 'Ayesha Raza', behaviourTypes: [BehaviorType.LipMovement], perSignal: { [BehaviorType.LipMovement]: 0.68 }, compositeScore: 0.68, snapshotPath: 'snapshots/sess-003/det-004.jpg', detectedAt: iso(2), status: 'New' },
  { id: 'det-005', sessionId: 'sess-003', seatNumber: 12, studentId: 'usr-student-2', studentName: 'Bilal Ahmed', behaviourTypes: [BehaviorType.UnauthorisedObject], perSignal: { [BehaviorType.UnauthorisedObject]: 0.85 }, compositeScore: 0.85, snapshotPath: 'snapshots/sess-003/det-005.jpg', detectedAt: iso(0, 1), status: 'New' },
];

// ── Exam Sessions ───────────────────────────

export const MOCK_SESSIONS: ExamSession[] = [
  { id: 'sess-001', courseCode: 'CS-4402', courseName: 'Compiler Construction', classroomId: 'cls-hall-a', classroomName: 'Hall-A', scheduledDate: iso(15).slice(0, 10), startTime: '09:00', endTime: '12:00', status: SessionStatus.Completed, invigilatorId: 'usr-teacher-1', invigilatorName: 'Dr. M. Bilal', silentMode: true, totalSeats: 60, occupiedSeats: 52, alertCount: 4, caseCount: 2, createdAt: iso(16) },
  { id: 'sess-002', courseCode: 'CS-3301', courseName: 'Operating Systems', classroomId: 'cls-lh-4', classroomName: 'LH-4', scheduledDate: iso(5).slice(0, 10), startTime: '14:00', endTime: '17:00', status: SessionStatus.Completed, invigilatorId: 'usr-teacher-1', invigilatorName: 'Dr. M. Bilal', silentMode: false, totalSeats: 48, occupiedSeats: 41, alertCount: 1, caseCount: 0, createdAt: iso(6) },
  { id: 'sess-003', courseCode: 'CS-3301', courseName: 'Operating Systems', classroomId: 'cls-lh-4', classroomName: 'LH-4', scheduledDate: new Date().toISOString().slice(0, 10), startTime: '09:00', endTime: '12:00', status: SessionStatus.InProgress, invigilatorId: 'usr-teacher-1', invigilatorName: 'Dr. M. Bilal', silentMode: true, totalSeats: 48, occupiedSeats: 38, alertCount: 2, caseCount: 1, createdAt: iso(0, 3) },
  { id: 'sess-004', courseCode: 'SE-4101', courseName: 'Software Engineering', classroomId: 'cls-lh-7', classroomName: 'LH-7', scheduledDate: iso(-2).slice(0, 10), startTime: '10:00', endTime: '13:00', status: SessionStatus.Scheduled, invigilatorId: 'usr-teacher-1', invigilatorName: 'Dr. M. Bilal', silentMode: false, totalSeats: 40, occupiedSeats: 0, alertCount: 0, caseCount: 0, createdAt: iso(7) },
];

// ── Thresholds ─────────────────────────────

export const MOCK_THRESHOLDS: ThresholdConfig[] = [
  { id: BehaviorType.GazeDeviation, behaviorType: BehaviorType.GazeDeviation, sensitivity: 70, weight: 0.20, lastCalibrated: iso(30), calibratedBy: 'Admin Registrar' },
  { id: BehaviorType.HeadPoseViolation, behaviorType: BehaviorType.HeadPoseViolation, sensitivity: 75, weight: 0.25, lastCalibrated: iso(30), calibratedBy: 'Admin Registrar' },
  { id: BehaviorType.LipMovement, behaviorType: BehaviorType.LipMovement, sensitivity: 65, weight: 0.20, lastCalibrated: iso(30), calibratedBy: 'Admin Registrar' },
  { id: BehaviorType.PhoneDetected, behaviorType: BehaviorType.PhoneDetected, sensitivity: 85, weight: 0.20, lastCalibrated: iso(30), calibratedBy: 'Admin Registrar' },
  { id: BehaviorType.UnauthorisedObject, behaviorType: BehaviorType.UnauthorisedObject, sensitivity: 80, weight: 0.15, lastCalibrated: iso(30), calibratedBy: 'Admin Registrar' },
];

// ── Audit Log ──────────────────────────────

export const MOCK_AUDIT_LOG: AuditLogEntry[] = [
  { id: uid('al'), timestamp: iso(0, 1), userId: 'usr-admin-1', userName: 'Admin Registrar', userRole: Role.Admin, action: 'USER_CREATED', target: 'usr-student-3', details: 'Created student account for Zara Malik (232501)', ipAddress: '192.168.1.10' },
  { id: uid('al'), timestamp: iso(2), userId: 'usr-teacher-1', userName: 'Dr. M. Bilal', userRole: Role.Teacher, action: 'CASE_CREATED', target: 'case-004', details: 'Case AU-CS-INT-2026-017 created from detection event det-004', ipAddress: '192.168.1.22' },
  { id: uid('al'), timestamp: iso(5), userId: 'usr-teacher-1', userName: 'Dr. M. Bilal', userRole: Role.Teacher, action: 'CASE_DISMISSED', target: 'case-003', details: 'Case AU-CS-INT-2026-016 dismissed — false positive', ipAddress: '192.168.1.22' },
  { id: uid('al'), timestamp: iso(7), userId: 'usr-student-1', userName: 'Ayesha Raza', userRole: Role.Student, action: 'APPEAL_SUBMITTED', target: 'appeal-001', details: 'Appeal filed for case AU-CS-INT-2026-014', ipAddress: '192.168.5.34' },
  { id: uid('al'), timestamp: iso(10), userId: 'usr-hod-1', userName: 'Dr. Sara Khan', userRole: Role.HOD, action: 'PENALTY_ISSUED', target: 'pen-001', details: 'Formal Warning issued for case AU-CS-INT-2026-014', ipAddress: '192.168.1.15' },
  { id: uid('al'), timestamp: iso(14), userId: 'usr-teacher-1', userName: 'Dr. M. Bilal', userRole: Role.Teacher, action: 'CASE_ESCALATED', target: 'case-002', details: 'Case AU-CS-INT-2026-015 escalated to HOD', ipAddress: '192.168.1.22' },
  { id: uid('al'), timestamp: iso(15), userId: 'usr-teacher-1', userName: 'Dr. M. Bilal', userRole: Role.Teacher, action: 'SESSION_STARTED', target: 'sess-001', details: 'Exam session CS-4402 started in Hall-A', ipAddress: '192.168.1.22' },
  { id: uid('al'), timestamp: iso(30), userId: 'usr-admin-1', userName: 'Admin Registrar', userRole: Role.Admin, action: 'THRESHOLD_UPDATED', target: 'thresholds', details: 'Detection thresholds calibrated for all 5 behaviour types', ipAddress: '192.168.1.10' },
];

// ── Notifications ──────────────────────────

export function getMockNotifications(userId: string): Notification[] {
  const all: Notification[] = [
    { id: 'notif-001', userId: 'usr-student-1', title: 'Appeal Received', message: 'Your appeal for case AU-CS-INT-2026-014 has been submitted and is under review.', type: 'appeal', referenceId: 'appeal-001', referenceType: 'appeal', read: false, createdAt: iso(7) },
    { id: 'notif-002', userId: 'usr-student-1', title: 'Penalty Notice Issued', message: 'A formal warning has been issued for case AU-CS-INT-2026-014. Check your case details.', type: 'penalty', referenceId: 'case-001', referenceType: 'case', read: true, createdAt: iso(10) },
    { id: 'notif-003', userId: 'usr-hod-1', title: 'Case Escalated for Review', message: 'Case AU-CS-INT-2026-015 (Bilal Ahmed) has been escalated to your department.', type: 'case_update', referenceId: 'case-002', referenceType: 'case', read: false, createdAt: iso(14) },
    { id: 'notif-004', userId: 'usr-hod-1', title: 'New Appeal Submitted', message: 'Ayesha Raza filed an appeal for case AU-CS-INT-2026-014.', type: 'appeal', referenceId: 'appeal-001', referenceType: 'appeal', read: false, createdAt: iso(7) },
    { id: 'notif-005', userId: 'usr-teacher-1', title: 'New Detection Alert', message: 'Unauthorised object detected at Seat 12 in current session CS-3301.', type: 'alert', referenceId: 'sess-003', referenceType: 'session', read: false, createdAt: iso(0, 1) },
    { id: 'notif-006', userId: 'usr-admin-1', title: 'System Health', message: 'Camera cam-lh-7 in LH-7 entered maintenance mode.', type: 'system', read: true, createdAt: iso(3) },
    { id: 'notif-007', userId: 'usr-controller-1', title: 'Exam Scheduled', message: 'SE-4101 Software Engineering scheduled for upcoming session.', type: 'system', read: true, createdAt: iso(7) },
  ];
  return all.filter(n => n.userId === userId);
}

// ── Exam Schedule ──────────────────────────

export const MOCK_EXAM_SCHEDULE: ExamScheduleEntry[] = [
  { id: 'exam-001', courseCode: 'CS-4402', courseName: 'Compiler Construction', department: 'Computer Science', date: iso(15).slice(0, 10), startTime: '09:00', endTime: '12:00', classroomId: 'cls-hall-a', classroomName: 'Hall-A', invigilatorId: 'usr-teacher-1', invigilatorName: 'Dr. M. Bilal', status: SessionStatus.Completed },
  { id: 'exam-002', courseCode: 'CS-3301', courseName: 'Operating Systems', department: 'Computer Science', date: new Date().toISOString().slice(0, 10), startTime: '09:00', endTime: '12:00', classroomId: 'cls-lh-4', classroomName: 'LH-4', invigilatorId: 'usr-teacher-1', invigilatorName: 'Dr. M. Bilal', status: SessionStatus.InProgress },
  { id: 'exam-003', courseCode: 'SE-4101', courseName: 'Software Engineering', department: 'Computer Science', date: iso(-2).slice(0, 10), startTime: '10:00', endTime: '13:00', classroomId: 'cls-lh-7', classroomName: 'LH-7', status: SessionStatus.Scheduled, hasConflict: false },
  { id: 'exam-004', courseCode: 'EE-2201', courseName: 'Circuit Analysis', department: 'Electrical Engineering', date: iso(-3).slice(0, 10), startTime: '14:00', endTime: '17:00', classroomId: 'cls-hall-a', classroomName: 'Hall-A', status: SessionStatus.Scheduled, hasConflict: true, conflictDetails: 'Hall-A already reserved for CS-3301 on this date.' },
];

// ── Invigilator Assignments ────────────────

export const MOCK_ASSIGNMENTS: InvigilatorAssignment[] = [
  { id: 'asgn-001', examId: 'exam-001', teacherId: 'usr-teacher-1', teacherName: 'Dr. M. Bilal', department: 'Computer Science', courseCode: 'CS-4402', date: iso(15).slice(0, 10), startTime: '09:00', endTime: '12:00', classroomName: 'Hall-A', status: 'Assigned' },
  { id: 'asgn-002', examId: 'exam-002', teacherId: 'usr-teacher-1', teacherName: 'Dr. M. Bilal', department: 'Computer Science', courseCode: 'CS-3301', date: new Date().toISOString().slice(0, 10), startTime: '09:00', endTime: '12:00', classroomName: 'LH-4', status: 'Assigned' },
];

// ── Statistical Reports ────────────────────

export const MOCK_STATS: StatisticalReport = {
  incidentsByDepartment: [
    { department: 'Computer Science', count: 12 },
    { department: 'Electrical Engineering', count: 5 },
    { department: 'Mechanical Engineering', count: 3 },
    { department: 'Business Administration', count: 7 },
  ],
  incidentsOverTime: [
    { date: 'Jul 2026', count: 3 },
    { date: 'Aug 2026', count: 6 },
    { date: 'Sep 2026', count: 14 },
  ],
  behaviorDistribution: [
    { behavior: BehaviorType.GazeDeviation, count: 8 },
    { behavior: BehaviorType.HeadPoseViolation, count: 5 },
    { behavior: BehaviorType.LipMovement, count: 3 },
    { behavior: BehaviorType.PhoneDetected, count: 6 },
    { behavior: BehaviorType.UnauthorisedObject, count: 2 },
  ],
  caseStatusDistribution: [
    { status: CaseStatus.Confirmed, count: 8 },
    { status: CaseStatus.Dismissed, count: 5 },
    { status: CaseStatus.Escalated, count: 3 },
    { status: CaseStatus.PendingReview, count: 7 },
  ],
  totalCases: 23,
  totalAppeals: 4,
  appealSuccessRate: 0.5,
  averageResolutionDays: 4.2,
};

// ── In-memory mutable stores ────────────────

export const db = {
  users: [...MOCK_USERS] as User[],
  classrooms: [...MOCK_CLASSROOMS] as Classroom[],
  sessions: [...MOCK_SESSIONS] as ExamSession[],
  cases: [...MOCK_CASES] as Case[],
  detections: [...MOCK_DETECTIONS] as DetectionEvent[],
  penalties: [...MOCK_PENALTIES] as Penalty[],
  appeals: [...MOCK_APPEALS] as Appeal[],
  thresholds: [...MOCK_THRESHOLDS] as ThresholdConfig[],
  auditLog: [...MOCK_AUDIT_LOG] as AuditLogEntry[],
  examSchedule: [...MOCK_EXAM_SCHEDULE] as ExamScheduleEntry[],
  assignments: [...MOCK_ASSIGNMENTS] as InvigilatorAssignment[],
  notifRead: new Set<string>(),
};

// ── mockCall Router ────────────────────────

export async function mockCall(funcName: string, args: any[]): Promise<any> {
  // Simulate network latency
  await new Promise(r => setTimeout(r, 100 + Math.random() * 200));

  const paginated = (data: any[]) => ({ data, total: data.length, page: 1, pageSize: data.length });
  const response = (data: any, message?: string) => ({ data, message });

  switch (funcName) {
    case 'getUsers': return paginated(db.users);
    case 'createUser': return response(db.users[0], 'User created (mock)');
    case 'updateUser': return response(db.users[0], 'User updated (mock)');
    case 'deleteUser': return response(null, 'User deleted (mock)');
    case 'getClassrooms': return paginated(db.classrooms);
    case 'getClassroom': return response(db.classrooms.find(c => c.id === args[0]) || db.classrooms[0]);
    case 'createClassroom': return response(db.classrooms[0], 'Classroom created (mock)');
    case 'updateClassroom': return response(db.classrooms[0], 'Classroom updated (mock)');
    case 'deleteClassroom': return response(null, 'Classroom deleted (mock)');
    case 'getSessions': return paginated(db.sessions);
    case 'getSession': return response(db.sessions.find(s => s.id === args[0]) || db.sessions[0]);
    case 'createSession': return response(db.sessions[0], 'Session started (mock)');
    case 'endSession': return response(db.sessions[0], 'Session ended (mock)');
    case 'previewSeatMap': return response([]);
    case 'getCases': 
      const caseFilters = args[0] || {};
      let cases = db.cases;
      if (caseFilters.studentId) cases = cases.filter(c => c.studentId === caseFilters.studentId);
      if (caseFilters.status) cases = cases.filter(c => c.status === caseFilters.status);
      return paginated(cases);
    case 'getCase': return response(db.cases.find(c => c.id === args[0]) || db.cases[0]);
    case 'confirmCase': return response(db.cases[0], 'Case confirmed (mock)');
    case 'dismissCase': return response(db.cases[0], 'Case dismissed (mock)');
    case 'escalateCase': return response(db.cases[0], 'Case escalated (mock)');
    case 'createCaseFromDetection': return response(db.cases[0], 'Case created (mock)');
    case 'issuePenalty': return response(db.penalties[0], 'Penalty issued (mock)');
    case 'getAppeals': return paginated(db.appeals);
    case 'getAppeal': return response(db.appeals.find(a => a.id === args[0]) || db.appeals[0]);
    case 'submitAppeal': return response(db.appeals[0], 'Appeal submitted (mock)');
    case 'resolveAppeal': return response(db.appeals[0], 'Appeal resolved (mock)');
    case 'getDetectionEvents': return paginated(db.detections);
    case 'dismissDetection': return response(db.detections[0]);
    case 'getCaseMedia': 
      return response({ caseId: args[0], detectionId: 'det-001', clipStatus: 'available', clip: { url: '', expiresInSeconds: 300, durationSeconds: 10, sizeBytes: 1000, contentType: 'video/mp4' }, recordImageUrl: '', snapshotUrl: '', clipDeletedAt: null });
    case 'getDetectionMedia': 
      return response({ caseId: null, detectionId: args[0], clipStatus: 'available', clip: { url: '', expiresInSeconds: 300, durationSeconds: 10, sizeBytes: 1000, contentType: 'video/mp4' }, recordImageUrl: '', snapshotUrl: '', clipDeletedAt: null });
    case 'getThresholds': return response(db.thresholds);
    case 'updateThresholds': return response(db.thresholds, 'Thresholds updated (mock)');
    case 'getAuditLog': return paginated(db.auditLog);
    case 'getNotifications': return paginated(getMockNotifications(args[0]));
    case 'markNotificationRead': return response(null);
    case 'markAllNotificationsRead': return response(null);
    case 'getExamSchedule': return paginated(db.examSchedule);
    case 'createExam': return response(db.examSchedule[0], 'Exam created (mock)');
    case 'updateExam': return response(db.examSchedule[0], 'Exam updated (mock)');
    case 'deleteExam': return response(null, 'Exam deleted (mock)');
    case 'getAssignments': return paginated(db.assignments);
    case 'assignInvigilator': return response(db.assignments[0], 'Invigilator assigned (mock)');
    case 'getStatisticalReports': return response(MOCK_STATS);
    default:
      console.warn(`[MockDB] Unhandled mock call: ${funcName}`);
      return response(null);
  }
}
