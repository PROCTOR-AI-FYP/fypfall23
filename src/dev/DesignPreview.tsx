/** Development-only visual QA. No import from the production entry point.
 * Requests are answered in this tab with sample data; writes are refused.
 * It does not authenticate to, seed, configure or mutate the real backend.
 */
import { createRoot } from 'react-dom/client';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { ThemeProvider } from '@/lib/theme-context';
import { AuthProvider } from '@/lib/auth-context';
import { AppShell } from '@/components/layout/AppShell';
import { LoginPage } from '@/pages/Login';
import { AdminDashboard } from '@/pages/admin/Dashboard';
import { UserManagement } from '@/pages/admin/UserManagement';
import { ClassroomManagement } from '@/pages/admin/ClassroomManagement';
import { ThresholdConfiguration } from '@/pages/admin/ThresholdConfiguration';
import { AuditLogViewer } from '@/pages/admin/AuditLogViewer';
import { SeatPolygonEditor } from '@/pages/admin/SeatPolygonEditor';
import { HodDashboard } from '@/pages/hod/Dashboard';
import { CaseManagement } from '@/pages/hod/CaseManagement';
import { CaseDetail } from '@/pages/hod/CaseDetail';
import { AppealReview } from '@/pages/hod/AppealReview';
import { SessionSetup } from '@/pages/teacher/SessionSetup';
import { TeacherSessionList } from '@/pages/teacher/SessionList';
import { LiveMonitor } from '@/pages/teacher/LiveMonitor';
import { AlertInbox } from '@/pages/teacher/AlertInbox';
import { SessionReport } from '@/pages/teacher/SessionReport';
import { MyCases } from '@/pages/student/MyCases';
import { StudentCaseDetail } from '@/pages/student/StudentCaseDetail';
import { AppealForm } from '@/pages/student/AppealForm';
import { ExamSchedule } from '@/pages/controller/ExamSchedule';
import { InvigilatorAssignment } from '@/pages/controller/InvigilatorAssignment';
import { SessionHistory } from '@/pages/controller/SessionHistory';
import { StatisticalReports } from '@/pages/controller/StatisticalReports';
import * as fixtures from '@/lib/mock-db';
import { Role, type User, type Case, type Appeal, type Penalty } from '@/lib/types';
import '@/index.css';
import '@/styles/portal.css';

if (!import.meta.env.DEV) throw new Error('The design preview is available only in development.');

const params = new URLSearchParams(window.location.search);
const roleMap: Record<string, Role> = { admin:Role.Admin, hod:Role.HOD, teacher:Role.Teacher, student:Role.Student, exam_controller:Role.ExamController };
const role = roleMap[params.get('role') ?? 'admin'] ?? Role.Admin;
const user = fixtures.MOCK_USERS.find(u => u.role === role)!;
const defaults: Record<Role,string> = { [Role.Admin]:'/admin/dashboard', [Role.HOD]:'/hod/dashboard', [Role.Teacher]:'/teacher/session-setup', [Role.Student]:'/student/cases', [Role.ExamController]:'/exam-controller/schedule' };
const slug = (value:string) => value.replace(/([a-z])([A-Z])/g,'$1_$2').replaceAll(' ','_').toLowerCase();
const signal = (value:string) => slug(value).toUpperCase();
const roleSlug = (value:Role) => Object.entries(roleMap).find(([,r]) => r === value)?.[0];
const wireUser = (u:User) => ({ id:u.id, full_name:u.name, email:u.email, role:roleSlug(u.role), department:u.department, registration_or_employee_no:u.registrationNo ?? 'EMP-001', status:u.status==='Active'?'active':'disabled', activated:u.activated,created_at:u.createdAt });
const penalty = (p:Penalty) => ({ id:p.id,case_id:p.caseId,penalty_type:slug(p.type),description:p.description,issued_by:p.issuedBy,issued_by_name:p.issuedByName,notice_reference:p.noticeReference,created_at:p.createdAt,revoked_at:p.revokedAt ?? null });
const appeal = (a:Appeal) => ({id:a.id,case_id:a.caseId,case_reference_no:fixtures.MOCK_CASES.find(c=>c.id===a.caseId)?.referenceNo,student_id:a.studentId,student_name:a.studentName,student_reg_no:a.studentRegNo,statement:a.statement,supporting_info:a.supportingInfo ?? null,status:slug(a.status),reviewed_by:a.reviewedBy ?? null,reviewer_name:a.reviewerName ?? null,review_note:a.reviewNote ?? null,submitted_at:a.submittedAt,resolved_at:a.resolvedAt ?? null});
const wireCase = (c:Case) => ({id:c.id,reference_no:c.referenceNo,session_id:c.sessionId,student_id:c.studentId,student_name:c.studentName,student_reg_no:c.studentRegNo,course_code:c.courseCode,course_name:c.courseName,classroom_name:c.classroomName,seat_number:c.seatNumber,behaviour_types:c.behaviourTypes.map(signal),per_signal:Object.fromEntries(c.behaviourTypes.map(b=>[signal(b),c.compositeScore])),composite_score:c.compositeScore,status:slug(c.status),detection_event_id:c.detectionEventId,teacher_note:c.teacherNote ?? null,teacher_id:c.teacherId,teacher_name:c.teacherName,penalty:c.penalty?penalty(c.penalty):null,appeal:c.appeal?appeal(c.appeal):null,timeline:c.timeline.map(t=>({id:t.id,action:t.action,actor_name:t.actorName,actor_role:t.actorRole?roleSlug(t.actorRole):null,details:t.details??null,timestamp:t.timestamp})),created_at:c.createdAt,updated_at:c.updatedAt});
const sessions = fixtures.MOCK_SESSIONS.map(s=>({id:s.id,course_code:s.courseCode,course_name:s.courseName,department:'Computer Science',classroom_id:s.classroomId,classroom_name:s.classroomName,scheduled_date:s.scheduledDate,start_time:s.startTime,end_time:s.endTime,status:slug(s.status),invigilator_id:s.invigilatorId,invigilator_name:s.invigilatorName,silent_mode:s.silentMode,total_seats:s.totalSeats,occupied_seats:s.occupiedSeats,alert_count:s.alertCount,case_count:s.caseCount,confirmed_case_count:s.caseCount,created_at:s.createdAt}));
const classrooms = fixtures.MOCK_CLASSROOMS.map(c=>({id:c.id,name:c.name,building:c.building,capacity:c.capacity,camera_id:c.cameraId,camera_status:slug(c.cameraStatus),seat_map:c.seatMap?.map(s=>({seat_number:s.seatNumber,vertices:s.vertices})) ?? [],created_at:c.createdAt}));
const cases = fixtures.MOCK_CASES.filter(c=>role!==Role.Student || c.studentId===user.id).map(wireCase);
const detections = fixtures.MOCK_DETECTIONS.map(d=>({id:d.id,session_id:d.sessionId,seat_number:d.seatNumber,student_id:d.studentId,student_name:d.studentName,behaviour_types:d.behaviourTypes.map(signal),per_signal:Object.fromEntries(Object.entries(d.perSignal).map(([k,v])=>[signal(k),v])),composite_score:d.compositeScore,detected_at:d.detectedAt,status:slug(d.status)}));
const nativeFetch = window.fetch.bind(window);
window.fetch = async (input,options) => {
  const url=new URL(typeof input==='string'?input:input instanceof URL?input.href:input.url,window.location.origin);
  if (!url.pathname.startsWith('/api/')) return nativeFetch(input,options);
  if (url.pathname==='/api/seatmap/preview' && options?.body instanceof FormData) {
    const file=options.body.get('file');
    const lines=file instanceof File?(await file.text()).trim().split(/\r?\n/).slice(1):[];
    return Response.json({rows:lines.map(line=>{const [seat,reg]=line.split(',');const student=fixtures.MOCK_USERS.find(u=>u.registrationNo===reg&&u.role===Role.Student);return {seat_number:Number(seat),student_reg_no:reg,status:student?.activated?'Resolved':student?'Unverified':'Unregistered ID'};})});
  }
  if ((options?.method ?? 'GET') !== 'GET') return Response.json({detail:'Design preview: sample data is read-only.'},{status:409});
  const path=url.pathname;
  let data:unknown=[];
  if (path==='/api/auth/me' && params.get('view')==='/login') return Response.json({detail:'Signed-out design preview.'},{status:401});
  if (path==='/api/auth/me') data=wireUser(user);
  else if (path==='/api/admin/users') data=fixtures.MOCK_USERS.map(wireUser);
  else if (path==='/api/classrooms') data=classrooms;
  else if (path.startsWith('/api/classrooms/')) data=classrooms.find(c=>c.id===path.split('/')[3]);
  else if (path.endsWith('/camera/seats')) data=[{seat_number:14,student_name:'Ayesha Raza',registration_no:'232475'}];
  else if (path.endsWith('/camera/status')) data={running:false,phase:'stopped',session_id:path.split('/')[3],seat_number:null,objects:[],fps:0,head_pose:null,error:null,head_error:null,alert_error:null};
  else if (path==='/api/sessions') data=sessions.filter(s=>!url.searchParams.get('status') || s.status===url.searchParams.get('status'));
  else if (path.startsWith('/api/sessions/')) data=sessions.find(s=>s.id===path.split('/')[3]);
  else if (path.endsWith('/media')) data={case_id:path.includes('/cases/')?path.split('/')[3]:null,detection_id:'design-preview',clip_status:'pending_upload',clip:null,record_image_url:null,snapshot_url:null,clip_deleted_at:null};
  else if (path==='/api/cases') data=cases;
  else if (path.startsWith('/api/cases/')) data=cases.find(c=>c.id===path.split('/')[3]);
  else if (path==='/api/appeals') data=fixtures.MOCK_APPEALS.map(appeal);
  else if (path.startsWith('/api/appeals/')) data=fixtures.MOCK_APPEALS.map(appeal).find(a=>a.id===path.split('/')[3]);
  else if (path==='/api/detections') data=detections;
  else if (path==='/api/admin/thresholds') data=fixtures.MOCK_THRESHOLDS.map(t=>({behaviour_type:signal(t.behaviorType),sensitivity:t.sensitivity,weight:t.weight,updated_at:t.lastCalibrated,updated_by_name:t.calibratedBy}));
  else if (path==='/api/admin/audit-log') data=fixtures.MOCK_AUDIT_LOG.map(a=>({id:a.id,timestamp:a.timestamp,user_id:a.userId,user_name:a.userName,user_role:a.userRole?roleSlug(a.userRole):null,action:a.action,target:a.target,details:a.details,ip_address:a.ipAddress}));
  else if (path==='/api/notifications') data=fixtures.getMockNotifications(user.id).map(n=>({id:n.id,title:n.title,message:n.message,type:n.type,reference_id:n.referenceId,reference_type:n.referenceType,read:n.read,created_at:n.createdAt}));
  else if (path==='/api/exam-schedule') data=fixtures.MOCK_EXAM_SCHEDULE.map(e=>({id:e.id,course_code:e.courseCode,course_name:e.courseName,department:e.department,date:e.date,start_time:e.startTime,end_time:e.endTime,classroom_id:e.classroomId,classroom_name:e.classroomName,invigilator_id:e.invigilatorId,invigilator_name:e.invigilatorName,status:slug(e.status),has_conflict:e.hasConflict,conflict_details:e.conflictDetails}));
  else if (path==='/api/invigilator-assignments') data=fixtures.MOCK_ASSIGNMENTS.map(a=>({id:a.id,exam_id:a.examId,teacher_id:a.teacherId,teacher_name:a.teacherName,department:a.department,course_code:a.courseCode,date:a.date,start_time:a.startTime,end_time:a.endTime,classroom_name:a.classroomName}));
  else if (path==='/api/reports/statistics') {const s=fixtures.MOCK_STATS;data={incidents_by_department:s.incidentsByDepartment.map(v=>({label:v.department,count:v.count})),incidents_over_time:s.incidentsOverTime.map(v=>({label:v.date,count:v.count})),behavior_distribution:s.behaviorDistribution.map(v=>({label:signal(v.behavior),count:v.count})),case_status_distribution:s.caseStatusDistribution.map(v=>({label:slug(v.status),count:v.count})),total_cases:s.totalCases,total_appeals:s.totalAppeals,appeal_success_rate:s.appealSuccessRate,average_resolution_days:s.averageResolutionDays};}
  return Response.json(data ?? {detail:'Sample record not found.'},{status:data===undefined?404:200});
};

createRoot(document.getElementById('root')!).render(<ThemeProvider><AuthProvider><MemoryRouter initialEntries={[params.get('view') ?? defaults[role]]}><Routes><Route path="/login" element={<LoginPage />} /><Route element={<AppShell />}>
  <Route path="/admin/dashboard" element={<AdminDashboard />} /><Route path="/admin/users" element={<UserManagement />} /><Route path="/admin/classrooms" element={<ClassroomManagement />} /><Route path="/admin/classrooms/:id/seats" element={<SeatPolygonEditor />} /><Route path="/admin/thresholds" element={<ThresholdConfiguration />} /><Route path="/admin/audit-log" element={<AuditLogViewer />} />
  <Route path="/hod/dashboard" element={<HodDashboard />} /><Route path="/hod/cases" element={<CaseManagement />} /><Route path="/hod/cases/:id" element={<CaseDetail />} /><Route path="/hod/appeals" element={<AppealReview />} />
  <Route path="/teacher/session-setup" element={<SessionSetup />} /><Route path="/teacher/live-monitor" element={<TeacherSessionList />} /><Route path="/teacher/live-monitor/:id" element={<LiveMonitor />} /><Route path="/teacher/alerts" element={<AlertInbox />} /><Route path="/teacher/session-report" element={<TeacherSessionList reports />} /><Route path="/teacher/session-report/:id" element={<SessionReport />} />
  <Route path="/student/cases" element={<MyCases />} /><Route path="/student/cases/:id" element={<StudentCaseDetail />} /><Route path="/student/cases/:id/appeal" element={<AppealForm />} />
  <Route path="/exam-controller/schedule" element={<ExamSchedule />} /><Route path="/exam-controller/assignments" element={<InvigilatorAssignment />} /><Route path="/exam-controller/history" element={<SessionHistory />} /><Route path="/exam-controller/reports" element={<StatisticalReports />} />
</Route></Routes><div style={{position:'fixed',bottom:10,right:15,zIndex:60,padding:'7px 12px',borderRadius:10,background:'#225ce7',color:'white',fontSize:10}}>Frontend design preview · sample data · read-only</div></MemoryRouter></AuthProvider></ThemeProvider>);
