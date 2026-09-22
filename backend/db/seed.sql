-- Fixture data for manual testing / the RLS cross-visibility test.
-- Apply after schema.sql: psql "$DATABASE_ADMIN_URL" -f db/seed.sql
--
-- Password for every seeded account is: "ChangeMe123!"
-- bcrypt hash below was generated with backend/app/security.py::hash_password
-- at bcrypt_rounds=12. Regenerate if you change BCRYPT_ROUNDS.

-- Students (email_verified = true so they can log in immediately).
INSERT INTO users (full_name, email, password_hash, role, registration_or_employee_no, status, email_verified)
VALUES
    ('Ayesha Raza', '232475@students.au.edu.pk', '$2b$12$kAuV3.oC7DbJ0Z.sdOqUEOtEj4a3jewlf1tuzQAqKX/g/s77gxhTu', 'student', '232475', 'active', true),
    ('Bilal Ahmed', '232490@students.au.edu.pk', '$2b$12$kAuV3.oC7DbJ0Z.sdOqUEOtEj4a3jewlf1tuzQAqKX/g/s77gxhTu', 'student', '232490', 'active', true)
ON CONFLICT (email) DO NOTHING;

-- One of each staff role, staff-shaped local parts, same institutional domain.
INSERT INTO users (full_name, email, password_hash, role, registration_or_employee_no, status, email_verified)
VALUES
    ('Dr. M. Bilal', 'm.bilal@students.au.edu.pk', '$2b$12$kAuV3.oC7DbJ0Z.sdOqUEOtEj4a3jewlf1tuzQAqKX/g/s77gxhTu', 'teacher', 'EMP-1001', 'active', true),
    ('Dr. Sara Khan', 'hod.cs@students.au.edu.pk', '$2b$12$kAuV3.oC7DbJ0Z.sdOqUEOtEj4a3jewlf1tuzQAqKX/g/s77gxhTu', 'hod', 'EMP-1002', 'active', true),
    ('Admin Registrar', 'admin.registrar@students.au.edu.pk', '$2b$12$kAuV3.oC7DbJ0Z.sdOqUEOtEj4a3jewlf1tuzQAqKX/g/s77gxhTu', 'admin', 'EMP-1003', 'active', true),
    ('Usman Tariq', 'controller.exams@students.au.edu.pk', '$2b$12$kAuV3.oC7DbJ0Z.sdOqUEOtEj4a3jewlf1tuzQAqKX/g/s77gxhTu', 'exam_controller', 'EMP-1004', 'active', true)
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
