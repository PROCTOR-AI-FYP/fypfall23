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
    ('Dr. M. Bilal', 'm.bilal@students.au.edu.pk', 'teacher', 'Computer Science', 'EMP-1001', 'active'),
    ('Dr. Sara Khan', 'hod.cs@students.au.edu.pk', 'hod', 'Computer Science', 'EMP-1002', 'active'),
    ('Admin Registrar', 'admin.registrar@students.au.edu.pk', 'admin', 'IT Services', 'EMP-1003', 'active'),
    ('Usman Tariq', 'controller.exams@students.au.edu.pk', 'exam_controller', 'Examination Branch', 'EMP-1004', 'active')
ON CONFLICT (email) DO NOTHING;

-- A session + one case per seeded student, for the cross-visibility test.
INSERT INTO exam_sessions (id, course_code, room, status, invigilator_id)
SELECT '00000000-0000-0000-0000-000000000001', 'CS-4402', 'Hall-A', 'completed', id
FROM users WHERE email = 'm.bilal@students.au.edu.pk'
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
