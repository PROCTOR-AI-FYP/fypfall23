import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { ThemeProvider } from './lib/theme-context';
import { AuthProvider } from './lib/auth-context';
import { Role } from './lib/types';

// Layout & Auth
import { AppShell } from './components/layout/AppShell';
import { ProtectedRoute } from './components/auth/ProtectedRoute';
import { LoginPage } from './pages/Login';
import { LandingPage } from './pages/Landing';

// Admin
import { AdminDashboard } from './pages/admin/Dashboard';
import { UserManagement } from './pages/admin/UserManagement';
import { ClassroomManagement } from './pages/admin/ClassroomManagement';
import { SeatPolygonEditor } from './pages/admin/SeatPolygonEditor';
import { ThresholdConfiguration } from './pages/admin/ThresholdConfiguration';
import { AuditLogViewer } from './pages/admin/AuditLogViewer';

// HOD
import { HodDashboard } from './pages/hod/Dashboard';
import { CaseManagement } from './pages/hod/CaseManagement';
import { CaseDetail } from './pages/hod/CaseDetail';
import { AppealReview } from './pages/hod/AppealReview';

// Teacher
import { SessionSetup } from './pages/teacher/SessionSetup';
import { LiveMonitor } from './pages/teacher/LiveMonitor';
import { AlertInbox } from './pages/teacher/AlertInbox';
import { SessionReport } from './pages/teacher/SessionReport';

// Student
import { MyCases } from './pages/student/MyCases';
import { StudentCaseDetail } from './pages/student/StudentCaseDetail';
import { AppealForm } from './pages/student/AppealForm';

// Exam Controller
import { ExamSchedule } from './pages/controller/ExamSchedule';
import { InvigilatorAssignment } from './pages/controller/InvigilatorAssignment';
import { SessionHistory } from './pages/controller/SessionHistory';
import { StatisticalReports } from './pages/controller/StatisticalReports';

export default function App() {
  return (
    <ThemeProvider>
      <AuthProvider>
        <BrowserRouter>
          <Routes>
            <Route path="/" element={<LandingPage />} />
            <Route path="/login" element={<LoginPage />} />

            <Route element={<AppShell />}>
              {/* Admin Routes */}
              <Route path="/admin" element={<ProtectedRoute allowedRoles={[Role.Admin]}><Navigate to="/admin/dashboard" replace /></ProtectedRoute>} />
              <Route path="/admin/dashboard" element={<ProtectedRoute allowedRoles={[Role.Admin]}><AdminDashboard /></ProtectedRoute>} />
              <Route path="/admin/users" element={<ProtectedRoute allowedRoles={[Role.Admin]}><UserManagement /></ProtectedRoute>} />
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
              <Route path="/teacher/alerts" element={<ProtectedRoute allowedRoles={[Role.Teacher]}><AlertInbox /></ProtectedRoute>} />
              <Route path="/teacher/session-report/:id" element={<ProtectedRoute allowedRoles={[Role.Teacher]}><SessionReport /></ProtectedRoute>} />

              {/* Student Routes */}
              <Route path="/student" element={<ProtectedRoute allowedRoles={[Role.Student]}><Navigate to="/student/cases" replace /></ProtectedRoute>} />
              <Route path="/student/cases" element={<ProtectedRoute allowedRoles={[Role.Student]}><MyCases /></ProtectedRoute>} />
              <Route path="/student/cases/:id" element={<ProtectedRoute allowedRoles={[Role.Student]}><StudentCaseDetail /></ProtectedRoute>} />
              <Route path="/student/cases/:id/appeal" element={<ProtectedRoute allowedRoles={[Role.Student]}><AppealForm /></ProtectedRoute>} />

              {/* Exam Controller Routes */}
              <Route path="/exam-controller" element={<ProtectedRoute allowedRoles={[Role.ExamController]}><Navigate to="/exam-controller/schedule" replace /></ProtectedRoute>} />
              <Route path="/exam-controller/schedule" element={<ProtectedRoute allowedRoles={[Role.ExamController]}><ExamSchedule /></ProtectedRoute>} />
              <Route path="/exam-controller/assignments" element={<ProtectedRoute allowedRoles={[Role.ExamController]}><InvigilatorAssignment /></ProtectedRoute>} />
              <Route path="/exam-controller/history" element={<ProtectedRoute allowedRoles={[Role.ExamController]}><SessionHistory /></ProtectedRoute>} />
              <Route path="/exam-controller/reports" element={<ProtectedRoute allowedRoles={[Role.ExamController]}><StatisticalReports /></ProtectedRoute>} />
            </Route>

            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </BrowserRouter>
      </AuthProvider>
    </ThemeProvider>
  );
}
