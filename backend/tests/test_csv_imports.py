"""Real database tests for atomic CSV setup imports and role boundaries."""
from datetime import timedelta
import asyncio
import csv
import io

import pytest

from app.services.clock import institution_today
from app.services.csv_imports import HEADERS, parse_csv
from tests.helpers import ADMIN_EMAIL, CONTROLLER_EMAIL, HOD_EMAIL, STUDENT_A_EMAIL, TEACHER_EMAIL, auth, login


def csv_file(kind, rows):
    out = io.StringIO(newline='')
    writer = csv.writer(out)
    writer.writerow(HEADERS[kind])
    writer.writerows(rows)
    return (kind+'.csv',out.getvalue().encode(),'text/csv')


def batch():
    day=(institution_today()+timedelta(days=2)).isoformat()
    return {
        'student_roster':csv_file('student_roster',[['001234','Imported Student','001234@students.au.edu.pk','Computer Science']]),
        'classroom_inventory':csv_file('classroom_inventory',[['Import Lab','Block CSV','30','cam-import','Offline']]),
        'exam_schedule':csv_file('exam_schedule',[['CS-CSV','CSV Exam','Computer Science',day,'09:00','11:00','Import Lab']]),
        'invigilator_assignments':csv_file('invigilator_assignments',[[TEACHER_EMAIL,'CS-CSV',day,'09:00','11:00','Import Lab']]),
    }


async def preview(client,headers,files):
    response=await client.post('/api/imports/preview',headers=headers,files=files)
    assert response.status_code==200,response.text
    return response.json()


async def commit(client,headers,files,plan):
    return await client.post('/api/imports/commit',headers=headers,files=files,data={'preview_hash':plan['preview_hash']})


async def test_csv_import_complete_batch_resolves_links_audits_notifies_and_reimports(client,admin_conn):
    headers=auth(await login(client,ADMIN_EMAIL)); files=batch()
    plan=await preview(client,headers,files)
    assert plan['counts']=={'create':4,'skip':0,'error':0}
    assert await admin_conn.fetchval("SELECT count(*) FROM classrooms WHERE name='Import Lab'")==0
    applied=await commit(client,headers,files,plan)
    assert applied.status_code==200,applied.text
    assert applied.json()['created']=={kind:1 for kind in HEADERS}
    user=await admin_conn.fetchrow("SELECT role,status,supabase_user_id,registration_or_employee_no FROM users WHERE email='001234@students.au.edu.pk'")
    assert user['role']=='student' and user['status']=='active' and user['supabase_user_id'] is None
    assert user['registration_or_employee_no']=='001234'
    exam=await admin_conn.fetchrow("SELECT s.*,c.name,u.email FROM exam_sessions s JOIN classrooms c ON c.id=s.classroom_id JOIN users u ON u.id=s.invigilator_id WHERE course_code='CS-CSV'")
    assert exam['name']=='Import Lab' and exam['email']==TEACHER_EMAIL and exam['status']=='scheduled'
    assert await admin_conn.fetchval("SELECT count(*) FROM notifications WHERE reference_id=$1",exam['id'])==1
    assert await admin_conn.fetchval("SELECT count(*) FROM audit_log WHERE action IN ('admin_create_user','classroom_created','exam_scheduled','invigilator_assigned')")==4
    again=await preview(client,headers,files)
    assert again['counts']=={'create':0,'skip':4,'error':0}
    replay=await commit(client,headers,files,again)
    assert replay.status_code==200 and replay.json()['skipped']==4
    assert await admin_conn.fetchval("SELECT count(*) FROM exam_sessions WHERE course_code='CS-CSV'")==1
    assert await admin_conn.fetchval("SELECT count(*) FROM notifications WHERE reference_id=$1",exam['id'])==1


async def test_csv_import_enforces_roles_and_csrf(client):
    files=batch()
    for email in (HOD_EMAIL,TEACHER_EMAIL,STUDENT_A_EMAIL):
        headers=auth(await login(client,email))
        assert (await client.post('/api/imports/preview',headers=headers,files=files)).status_code==403
        assert (await client.post('/api/imports/commit',headers=headers,files=files,data={'preview_hash':'0'*64})).status_code==403
    controller=auth(await login(client,CONTROLLER_EMAIL))
    for kind in ('student_roster','classroom_inventory'):
        assert (await client.post('/api/imports/preview',headers=controller,files={kind:files[kind]})).status_code==403
    admin=auth(await login(client,ADMIN_EMAIL))
    no_csrf={'Cookie':admin['Cookie'],'X-ProctorAI-CSRF':''}
    assert (await client.post('/api/imports/preview',headers=no_csrf,files=files)).status_code==403


async def test_csv_import_controller_can_schedule_and_assign_existing_room(client,admin_conn):
    files=batch(); day=(institution_today()+timedelta(days=2)).isoformat()
    files['exam_schedule']=csv_file('exam_schedule',[['CS-CSV','CSV Exam','Computer Science',day,'09:00','11:00','Hall-A']])
    files['invigilator_assignments']=csv_file('invigilator_assignments',[[TEACHER_EMAIL,'CS-CSV',day,'09:00','11:00','Hall-A']])
    files={k:files[k] for k in ('exam_schedule','invigilator_assignments')}
    headers=auth(await login(client,CONTROLLER_EMAIL))
    plan=await preview(client,headers,files)
    assert plan['counts']['create']==2
    result=await commit(client,headers,files,plan)
    assert result.status_code==200,result.text
    assert await admin_conn.fetchval("SELECT invigilator_id IS NOT NULL FROM exam_sessions WHERE course_code='CS-CSV'")


async def test_csv_import_duplicate_mismatch_and_blank_template_block_entire_batch(client,admin_conn):
    files=batch(); headers=auth(await login(client,ADMIN_EMAIL))
    files['student_roster']=csv_file('student_roster',[
        ['001234','Imported Student','001234@students.au.edu.pk','Computer Science'],
        ['001234','Imported Student','001234@students.au.edu.pk','Computer Science'],
        ['009999','Mismatch','008888@students.au.edu.pk','Computer Science'],
    ])
    plan=await preview(client,headers,files)
    assert plan['counts']['error']==2
    assert (await commit(client,headers,files,plan)).status_code==409
    assert await admin_conn.fetchval("SELECT count(*) FROM classrooms WHERE name='Import Lab'")==0
    assert await admin_conn.fetchval("SELECT count(*) FROM users WHERE email='001234@students.au.edu.pk'")==0
    blank=await preview(client,headers,{'student_roster':csv_file('student_roster',[['','','','']])})
    assert blank['counts']['error']==1 and not blank['can_import']


async def test_csv_import_refuses_teacher_and_room_overlaps(client):
    files=batch(); headers=auth(await login(client,ADMIN_EMAIL))
    day=(institution_today()+timedelta(days=2)).isoformat()
    files['classroom_inventory']=csv_file('classroom_inventory',[['Import Lab','Block CSV',30,'cam-import','Offline'],['Other Import Lab','Block CSV',30,'','Offline']])
    files['exam_schedule']=csv_file('exam_schedule',[
        ['CS-CSV','CSV Exam','Computer Science',day,'09:00','11:00','Import Lab'],
        ['CS-OTHER','Other Exam','Computer Science',day,'10:00','12:00','Other Import Lab'],
        ['CS-CLASH','Room Clash','Computer Science',day,'10:00','12:00','Import Lab'],
    ])
    files['invigilator_assignments']=csv_file('invigilator_assignments',[
        [TEACHER_EMAIL,'CS-CSV',day,'09:00','11:00','Import Lab'],
        [TEACHER_EMAIL,'CS-OTHER',day,'10:00','12:00','Other Import Lab'],
    ])
    plan=await preview(client,headers,files)
    assert plan['counts']['error']==2
    assert any('Room is already booked' in r['note'] for r in plan['rows'])
    assert any('already invigilating' in r['note'] for r in plan['rows'])


async def test_csv_import_stale_preview_and_changed_files_write_nothing(client,admin_conn):
    files=batch(); headers=auth(await login(client,ADMIN_EMAIL))
    plan=await preview(client,headers,files)
    await admin_conn.execute("INSERT INTO classrooms(name,building,capacity,camera_status) VALUES('Import Lab','Other',10,'offline')")
    assert (await commit(client,headers,files,plan)).status_code==409
    assert await admin_conn.fetchval("SELECT count(*) FROM users WHERE email='001234@students.au.edu.pk'")==0
    roster={'student_roster':files['student_roster']}
    plan=await preview(client,headers,roster)
    changed={'student_roster':csv_file('student_roster',[['001234','Changed Name','001234@students.au.edu.pk','Computer Science']])}
    assert (await commit(client,headers,changed,plan)).status_code==409


async def test_csv_import_late_failure_rolls_back_all_entities_and_audits(client,admin_conn,monkeypatch):
    from app.services import csv_imports
    from fastapi import HTTPException
    async def fail(*args,**kwargs):
        raise HTTPException(409,'Simulated assignment failure')
    monkeypatch.setattr(csv_imports,'assign_invigilator',fail)
    files=batch(); headers=auth(await login(client,ADMIN_EMAIL)); plan=await preview(client,headers,files)
    assert (await commit(client,headers,files,plan)).status_code==409
    assert await admin_conn.fetchval("SELECT count(*) FROM users WHERE email='001234@students.au.edu.pk'")==0
    assert await admin_conn.fetchval("SELECT count(*) FROM classrooms WHERE name='Import Lab'")==0
    assert await admin_conn.fetchval("SELECT count(*) FROM exam_sessions WHERE course_code='CS-CSV'")==0
    assert await admin_conn.fetchval("SELECT count(*) FROM audit_log WHERE action IN ('admin_create_user','classroom_created','exam_scheduled')")==0


def test_csv_import_parser_handles_bom_quotes_and_rejects_bad_headers():
    raw='\ufeffstudent_reg_no,full_name,university_email,department\r\n001234,"Student, Example",001234@students.au.edu.pk,CS\r\n'.encode()
    assert parse_csv('student_roster',raw)[0][1]['full_name']=='Student, Example'
    for raw in (b'foo\nbar\n',b'student_reg_no,student_reg_no\n1,2\n',b'\xff',b'x'*262145):
        with pytest.raises(ValueError): parse_csv('student_roster',raw)


async def test_csv_import_concurrent_commits_do_not_duplicate_records(client,admin_conn):
    files=batch(); headers=auth(await login(client,ADMIN_EMAIL)); plan=await preview(client,headers,files)
    results=await asyncio.gather(commit(client,headers,files,plan),commit(client,headers,files,plan))
    assert sorted(r.status_code for r in results)==[200,409]
    assert await admin_conn.fetchval("SELECT count(*) FROM users WHERE email='001234@students.au.edu.pk'")==1
    assert await admin_conn.fetchval("SELECT count(*) FROM classrooms WHERE name='Import Lab'")==1
    assert await admin_conn.fetchval("SELECT count(*) FROM exam_sessions WHERE course_code='CS-CSV'")==1
