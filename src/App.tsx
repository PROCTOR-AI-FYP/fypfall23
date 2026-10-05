import { lazy, Suspense } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { ThemeProvider } from './lib/theme-context';
import { AuthProvider } from './lib/auth-context';
import { Role } from './lib/types';
import { LiveProvider } from './lib/live-context';

// Layout & Auth
import { AppShell } from './components/layout/AppShell';
import { ProtectedRoute } from './components/auth/ProtectedRoute';
const LoginPage = lazy(() => import('./pages/Login').then(module => ({ default: module.LoginPage })));
const CsvImports = lazy(() => import('./pages/setup/CsvImports').then(module => ({ default: module.CsvImports })));
const LandingPage = lazy(() => import('./pages/Landing').then(module => ({ default: module.LandingPage })));
const CameraCheck = lazy(() => import('./pages/CameraCheck').then(module => ({ default: module.CameraCheck })));

// Admin
const AdminDashboard = lazy(() => import('./pages/admin/Dashboard').then(module => ({ default: module.AdminDashboard })));
const UserManagement = lazy(() => import('./pages/admin/UserManagement').then(module => ({ default: module.UserManagement })));
const ClassroomManagement = lazy(() => import('./pages/admin/ClassroomManagement').then(module => ({ default: module.ClassroomManagement })));
const SeatPolygonEditor = lazy(() => import('./pages/admin/SeatPolygonEditor').then(module => ({ default: module.SeatPolygonEditor })));
const ThresholdConfiguration = lazy(() => import('./pages/admin/ThresholdConfiguration').then(module => ({ default: module.ThresholdConfiguration })));
const AuditLogViewer = lazy(() => import('./pages/admin/AuditLogViewer').then(module => ({ default: module.AuditLogViewer })));

// HOD
const HodDashboard = lazy(() => import('./pages/hod/Dashboard').then(module => ({ default: module.HodDashboard })));
const CaseManagement = lazy(() => import('./pages/hod/CaseManagement').then(module => ({ default: module.CaseManagement })));
const CaseDetail = lazy(() => import('./pages/hod/CaseDetail').then(module => ({ default: module.CaseDetail })));
const AppealReview = lazy(() => import('./pages/hod/AppealReview').then(module => ({ default: module.AppealReview })));

// Teacher
const SessionSetup = lazy(() => import('./pages/teacher/SessionSetup').then(module => ({ default: module.SessionSetup })));
const LiveMonitor = lazy(() => import('./pages/teacher/LiveMonitor').then(module => ({ default: module.LiveMonitor })));
const AlertInbox = lazy(() => import('./pages/teacher/AlertInbox').then(module => ({ default: module.AlertInbox })));
const SessionReport = lazy(() => import('./pages/teacher/SessionReport').then(module => ({ default: module.SessionReport })));
const TeacherSessionList = lazy(() => import('./pages/teacher/SessionList').then(module => ({ default: module.TeacherSessionList })));

// Student
const MyCases = lazy(() => import('./pages/student/MyCases').then(module => ({ default: module.MyCases })));
const StudentCaseDetail = lazy(() => import('./pages/student/StudentCaseDetail').then(module => ({ default: module.StudentCaseDetail })));
const AppealForm = lazy(() => import('./pages/student/AppealForm').then(module => ({ default: module.AppealForm })));

// Exam Controller
const ExamSchedule = lazy(() => import('./pages/controller/ExamSchedule').then(module => ({ default: module.ExamSchedule })));
const InvigilatorAssignment = lazy(() => import('./pages/controller/InvigilatorAssignment').then(module => ({ default: module.InvigilatorAssignment })));
const SessionHistory = lazy(() => import('./pages/controller/SessionHistory').then(module => ({ default: module.SessionHistory })));
const StatisticalReports = lazy(() => import('./pages/controller/StatisticalReports').then(module => ({ default: module.StatisticalReports })));

export default function App() {
  return (
    <ThemeProvider>
      <AuthProvider>
        <LiveProvider>
        <BrowserRouter>
          <Suspense fallback={<div className="p-6">Loading page…</div>}>
          <Routes>
            <Route path="/" element={<LandingPage />} />
            <Route path="/login" element={<LoginPage />} />

            <Route element={<AppShell />}>
              <Route path="/camera-check" element={<ProtectedRoute allowedRoles={Object.values(Role)}><CameraCheck /></ProtectedRoute>} />
              {/* Admin Routes */}
              <Route path="/admin" element={<ProtectedRoute allowedRoles={[Role.Admin]}><Navigate to="/admin/dashboard" replace /></ProtectedRoute>} />
              <Route path="/admin/dashboard" element={<ProtectedRoute allowedRoles={[Role.Admin]}><AdminDashboard /></ProtectedRoute>} />
              <Route path="/admin/users" element={<ProtectedRoute allowedRoles={[Role.Admin]}><UserManagement /></ProtectedRoute>} />
              <Route path="/admin/imports" element={<ProtectedRoute allowedRoles={[Role.Admin]}><CsvImports /></ProtectedRoute>} />
              <Route path="/admin/classrooms" element={<ProtectedRoute allowedRoles={[Role.Admin]}><ClassroomManagement /></ProtectedRoute>} />
              <Route path="/admin/classrooms/:id/seats" element={<ProtectedRoute allowedRoles={[Role.Admin]}><SeatPolygonEditor /></ProtectedRoute>} />
              <Route path="/admin/thresholds" element={<ProtectedRoute allowedRoles={[Role.Admin]}><ThresholdConfiguration /></ProtectedRoute>} />
              <Route path="/admin/audit-log" element={<ProtectedRoute allowedRoles={[Role.Admin]}><AuditLogViewer /></ProtectedRoute>} />

              {/* HOD Routes */}
              <Route path="/hod" element={<ProtectedRoute allowedRoles={[Role.HOD]}><Navigate to="/hod/dashboard" replace /></ProtectedRoute>} />
              <Route path="/hod/dashboard" element={<ProtectedRoute allowedRoles={[Role.HOD]}><HodDashboard /></ProtectedRoute>} />
              <Route path="/hod/cases" element={<ProtectedRoute allowedRoles={[Role.HOD]}><CaseManagement /></ProtectedRoute>} />
              <Route path="/hod/cases/:id" element={<ProtectedRoute allowedRoles={[Role.HOD]}><CaseDetail /></ProtectedRoute>} />
              <Route path="/hod/appeals" element={<ProtectedRoute allowedRoles={[Role.HOD]}><AppealReview /></ProtectedRoute>} />

              {/* Teacher Routes */}
              <Route path="/teacher" element={<ProtectedRoute allowedRoles={[Role.Teacher]}><Navigate to="/teacher/session-setup" replace /></ProtectedRoute>} />
              <Route path="/teacher/session-setup" element={<ProtectedRoute allowedRoles={[Role.Teacher]}><SessionSetup /></ProtectedRoute>} />
              <Route path="/teacher/live-monitor/:id" element={<ProtectedRoute allowedRoles={[Role.Teacher]}><LiveMonitor /></ProtectedRoute>} />
              <Route path="/teacher/live-monitor" element={<ProtectedRoute allowedRoles={[Role.Teacher]}><TeacherSessionList /></ProtectedRoute>} />
              <Route path="/teacher/alerts" element={<ProtectedRoute allowedRoles={[Role.Teacher]}><AlertInbox /></ProtectedRoute>} />
              <Route path="/teacher/session-report/:id" element={<ProtectedRoute allowedRoles={[Role.Teacher]}><SessionReport /></ProtectedRoute>} />
              <Route path="/teacher/session-report" element={<ProtectedRoute allowedRoles={[Role.Teacher]}><TeacherSessionList reports /></ProtectedRoute>} />

              {/* Student Routes */}
              <Route path="/student" element={<ProtectedRoute allowedRoles={[Role.Student]}><Navigate to="/student/cases" replace /></ProtectedRoute>} />
              <Route path="/student/cases" element={<ProtectedRoute allowedRoles={[Role.Student]}><MyCases /></ProtectedRoute>} />
              <Route path="/student/cases/:id" element={<ProtectedRoute allowedRoles={[Role.Student]}><StudentCaseDetail /></ProtectedRoute>} />
              <Route path="/student/cases/:id/appeal" element={<ProtectedRoute allowedRoles={[Role.Student]}><AppealForm /></ProtectedRoute>} />

              {/* Exam Controller Routes */}
              <Route path="/exam-controller" element={<ProtectedRoute allowedRoles={[Role.ExamController]}><Navigate to="/exam-controller/schedule" replace /></ProtectedRoute>} />
              <Route path="/exam-controller/schedule" element={<ProtectedRoute allowedRoles={[Role.ExamController]}><ExamSchedule /></ProtectedRoute>} />
              <Route path="/exam-controller/imports" element={<ProtectedRoute allowedRoles={[Role.ExamController]}><CsvImports /></ProtectedRoute>} />
              <Route path="/exam-controller/assignments" element={<ProtectedRoute allowedRoles={[Role.ExamController]}><InvigilatorAssignment /></ProtectedRoute>} />
              <Route path="/exam-controller/history" element={<ProtectedRoute allowedRoles={[Role.ExamController]}><SessionHistory /></ProtectedRoute>} />
              <Route path="/exam-controller/reports" element={<ProtectedRoute allowedRoles={[Role.ExamController]}><StatisticalReports /></ProtectedRoute>} />
            </Route>

            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
          </Suspense>
        </BrowserRouter>
        </LiveProvider>
      </AuthProvider>
    </ThemeProvider>
  );
}
