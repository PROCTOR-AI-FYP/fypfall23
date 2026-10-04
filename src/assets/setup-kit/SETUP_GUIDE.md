# ProctorAI exam setup toolkit

1. Administrator: fill student roster and classroom inventory CSVs. Use CSV Imports to create students and rooms. Register staff through User Management. Student registration numbers must match the six-digit university email local part; students must sign in before seat assignments resolve.
2. Administrator: open a room's seat polygon editor. Generate a grid or draw polygons, align them to the actual camera view, then save the map.
3. Admin or Exam Controller: fill the exam schedule and invigilator CSVs, choose both on CSV Imports, preview, fix any rejected rows, then import. Room names must match classrooms. Teachers must already have active teacher accounts. Admins may upload all four sheets together; new rooms and exams resolve within the same batch. Imports skip exact existing matches and reject conflicting details, missing links and overlapping bookings. All records and audit entries save together or the whole batch rolls back.
4. Teacher: generate a seat-assignment CSV using real registration numbers. Upload it on Session Setup and wait for every row to resolve. Blank templates must be filled first.
5. Teacher: select the scheduled classroom, start the session, assign the monitored camera seat and check live head pose / phone / book signals.
6. Teacher: review evidence before creating a case. HOD: review cases and appeals. Students: see only their own cases and appeals.

FILES
- seat-assignments.csv: supported upload format (seat_number,student_reg_no). Seat numbering begins at 1. Leading zeros in registration numbers are preserved.
- seating-plan.svg: printable planning diagram; open in a browser and print, or save as PDF through the print dialog.
- seat-polygons.json: draft polygons in the existing 720×480 editor space. The website does not offer JSON upload; use the admin grid tool to create the draft, adjust and save.
- Student roster and classroom CSVs: Admin import only. Exam schedule and invigilator CSVs: Admin or Exam Controller. See CSV Imports in the appropriate portal navigation. Upload filled UTF-8 CSVs with the exact template headers, at most 256 KB / 1000 rows each. Blank templates must be filled first.

Downloading files creates no records. Importing a reviewed valid batch creates accounts, classrooms, exams and assignments. Imports do not activate accounts, create staff roles, overwrite existing records or calibrate cameras. No fictitious registration numbers are generated. A room grid is a planning aid, not calibrated camera geometry. The current local camera monitors one explicitly assigned student per view.
