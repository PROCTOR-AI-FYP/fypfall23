import type { SeatPolygon } from './types';

export interface SeatLayoutOptions { seats: number; columns: number; room: string; }
export const SETUP_TEMPLATES = [
  { id: 'roster', title: 'Student roster', filename: 'student-roster-template.csv', content: 'student_reg_no,full_name,university_email,department\r\n,,,\r\n', note: 'Administrator CSV Imports creates student accounts. Use six-digit registration numbers matching their university emails.' },
  { id: 'classrooms', title: 'Classroom inventory', filename: 'classroom-inventory-template.csv', content: 'room_name,building,capacity,camera_id,camera_status\r\n,,,,\r\n', note: 'Administrator CSV Imports creates rooms and their camera settings. Set status to Online, Offline or Maintenance.' },
  { id: 'schedule', title: 'Exam schedule', filename: 'exam-schedule-template.csv', content: 'course_code,course_name,department,date,start_time,end_time,room_name\r\n,,,,,,\r\n', note: 'Admin or Exam Controller CSV Imports creates exams. Match room names and use YYYY-MM-DD and 24-hour HH:MM.' },
  { id: 'invigilators', title: 'Invigilator assignments', filename: 'invigilator-assignment-template.csv', content: 'teacher_email,course_code,date,start_time,end_time,room_name\r\n,,,,,\r\n', note: 'Admin or Exam Controller CSV Imports links registered teachers to matching exams and sends assignment notifications.' },
] as const;

export function registrationNumbers(text: string): string[] {
  return text.split(/[\s,;]+/).map(v => v.trim()).filter(Boolean);
}

export function validateAssignments(ids: string[], seats: number): string | undefined {
  if (ids.length > seats) return `There are ${ids.length} students but only ${seats} ${seats===1?'seat':'seats'}.`;
  if (ids.some(v => !/^[a-zA-Z0-9][a-zA-Z0-9_-]*$/.test(v))) return 'Use registration numbers only: letters, digits, hyphens or underscores.';
  if (new Set(ids.map(v => v.toLowerCase())).size !== ids.length) return 'Each student registration number must appear only once.';
}

export function seatAssignmentCsv(seats: number, ids: string[] = []): string {
  return 'seat_number,student_reg_no\r\n' + Array.from({ length: ids.length || seats }, (_, i) => `${i + 1},${ids[i] ?? ''}`).join('\r\n') + '\r\n';
}

/** Draft rectangles in the existing editor's 720 x 480 coordinate space. */
export function seatGrid(seats: number, columns: number): SeatPolygon[] {
  if (!Number.isInteger(seats) || seats < 1 || seats > 200 || !Number.isInteger(columns) || columns < 1 || columns > 20) throw new Error('Choose 1–200 seats and 1–20 columns.');
  const rows = Math.ceil(seats / columns);
  const cellW = 660 / columns;
  const cellH = 360 / rows;
  return Array.from({ length: seats }, (_, i) => {
    const left = Math.round(30 + (i % columns) * cellW + cellW * .12);
    const top = Math.round(85 + Math.floor(i / columns) * cellH + cellH * .12);
    const right = Math.round(30 + (i % columns + 1) * cellW - cellW * .12);
    const bottom = Math.round(85 + (Math.floor(i / columns) + 1) * cellH - cellH * .12);
    return { seatNumber: i + 1, vertices: [{ x:left,y:top },{ x:right,y:top },{ x:right,y:bottom },{ x:left,y:bottom }] };
  });
}

const xml = (s:string) => s.replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;').replaceAll("'",'&apos;');

export function seatingPlanSvg(options: SeatLayoutOptions, ids: string[] = []): string {
  const { seats, columns, room } = options;
  const rows = Math.ceil(seats / columns);
  const labels = seatGrid(seats,columns).map((seat,i) => {
    const [a,,b] = seat.vertices;
    const h = b.y-a.y;
    const font = Math.min(14, h*.3, (b.x-a.x)*.22);
    return `<g><rect x="${a.x}" y="${a.y}" width="${b.x-a.x}" height="${h}" rx="${Math.min(7,h*.12)}" fill="${ids[i]?'#e8f0ff':'#f5f8fc'}" stroke="#9baed0"/><text x="${(a.x+b.x)/2}" y="${(a.y+b.y)/2-(ids[i]?font*.25:-font*.3)}" text-anchor="middle" font-size="${font}" fill="#16345e">${seat.seatNumber}</text>${ids[i]?`<text x="${(a.x+b.x)/2}" y="${(a.y+b.y)/2+font*.85}" text-anchor="middle" font-size="${font*.75}" fill="#305b91">${xml(ids[i])}</text>`:''}</g>`;
  }).join('');
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 720 480" role="img" aria-label="${xml(room)} seating plan"><rect width="720" height="480" rx="16" fill="white"/><g font-family="Arial,sans-serif"><text x="30" y="28" font-size="16" font-weight="bold" fill="#16345e">${xml(room || 'Classroom')} · ${seats} seats</text><text x="690" y="28" text-anchor="end" font-size="10" fill="#5b6e88">${rows} rows × ${columns} columns</text><rect x="240" y="44" width="240" height="24" rx="6" fill="#225de7"/><text x="360" y="60" text-anchor="middle" font-size="10" fill="white">FRONT / WHITEBOARD</text>${labels}<text x="30" y="466" font-size="9" fill="#5b6e88">ProctorAI · Planning layout · Adjust camera polygons to the actual room before saving.</text></g></svg>`;
}

export function polygonJson(seats:number,columns:number): string {
  return JSON.stringify(seatGrid(seats,columns).map(s => ({seat_number:s.seatNumber,vertices:s.vertices})),null,2);
}

export const SETUP_GUIDE = `# ProctorAI exam setup toolkit

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
`;

export function downloadSetupFile(filename:string,content:string|Blob,type='text/plain;charset=utf-8') {
  const url = URL.createObjectURL(content instanceof Blob?content:new Blob([content],{type}));
  const link = document.createElement('a');
  link.href=url; link.download=filename;
  document.body.append(link); link.click(); link.remove();
  setTimeout(()=>URL.revokeObjectURL(url),1000);
}
