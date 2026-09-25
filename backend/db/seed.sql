-- Fixture data for manual testing and the test suite.
-- Apply after schema.sql: psql "$DATABASE_ADMIN_URL" -f db/seed.sql
--
-- Accounts have no credentials: each activates on its owner's first Google
-- sign-in (supabase_user_id is NULL until then). Every address is on the
-- configured ALLOWED_EMAIL_DOMAIN.

-- Students.
INSERT INTO users (full_name, email, role, department, registration_or_employee_no, status)
VALUES
    ('Ayesha Raza', '232475@students.au.edu.pk', 'student', 'Computer Science', '232475', 'active'),
    ('Bilal Ahmed', '232490@students.au.edu.pk', 'student', 'Computer Science', '232490', 'active')
ON CONFLICT (email) DO NOTHING;

-- One of each staff role, staff-shaped local parts.
INSERT INTO users (full_name, email, role, department, registration_or_employee_no, status)
VALUES
    ('Dr. M. Bilal', 'm.bilal@au.edu.pk', 'teacher', 'Computer Science', 'EMP-1001', 'active'),
    ('Dr. Sara Khan', 'hod.cs@au.edu.pk', 'hod', 'Computer Science', 'EMP-1002', 'active'),
    ('Admin Registrar', 'admin.registrar@au.edu.pk', 'admin', 'IT Services', 'EMP-1003', 'active'),
    ('Usman Tariq', 'controller.exams@au.edu.pk', 'exam_controller', 'Examination Branch', 'EMP-1004', 'active')
ON CONFLICT (email) DO NOTHING;

-- Exam halls.
INSERT INTO classrooms (id, name, building, capacity, camera_id, camera_status)
VALUES
    ('00000000-0000-0000-0000-0000000c0001', 'Hall-A', 'Main Academic Block', 60, 'cam-hall-a', 'online'),
    ('00000000-0000-0000-0000-0000000c0002', 'LH-4', 'Block A', 48, 'cam-lh-4', 'online'),
    ('00000000-0000-0000-0000-0000000c0003', 'LH-7', 'Block B', 40, 'cam-lh-7', 'maintenance')
ON CONFLICT (id) DO NOTHING;

-- A completed session + one case per seeded student, for the cross-visibility test.
INSERT INTO exam_sessions (id, course_code, course_name, department, room, classroom_id, status, invigilator_id,
                           scheduled_date, start_time, end_time)
SELECT '00000000-0000-0000-0000-000000000001', 'CS-4402', 'Compiler Construction', 'Computer Science', 'Hall-A',
       '00000000-0000-0000-0000-0000000c0001', 'completed', id, DATE '2026-09-10', TIME '09:00', TIME '12:00'
FROM users WHERE email = 'm.bilal@au.edu.pk'
ON CONFLICT (id) DO NOTHING;

INSERT INTO seat_assignments (session_id, seat_number, student_reg_no, student_id)
SELECT '00000000-0000-0000-0000-000000000001', 14, '232475', id FROM users WHERE registration_or_employee_no = '232475'
ON CONFLICT (session_id, seat_number) DO NOTHING;

INSERT INTO seat_assignments (session_id, seat_number, student_reg_no, student_id)
SELECT '00000000-0000-0000-0000-000000000001', 15, '232490', id FROM users WHERE registration_or_employee_no = '232490'
ON CONFLICT (session_id, seat_number) DO NOTHING;

INSERT INTO cases (session_id, seat_number, student_id, reference_no, status)
SELECT '00000000-0000-0000-0000-000000000001', 14, id, 'AU-CS-INT-2026-014', 'pending_review'
FROM users WHERE registration_or_employee_no = '232475'
ON CONFLICT (reference_no) DO NOTHING;

INSERT INTO cases (session_id, seat_number, student_id, reference_no, status)
SELECT '00000000-0000-0000-0000-000000000001', 15, id, 'AU-CS-INT-2026-015', 'pending_review'
FROM users WHERE registration_or_employee_no = '232490'
ON CONFLICT (reference_no) DO NOTHING;
