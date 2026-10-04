import datetime
import enum
import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, ForeignKey, Enum as SqlaEnum
from sqlalchemy.orm import declarative_base, sessionmaker, Session, relationship
from pydantic import BaseModel, ConfigDict
import socketio
if __package__:
    from .object_monitor import ObjectMonitor
else:
    from object_monitor import ObjectMonitor

# --------------------------------------------------------------------------
# Known Gap: No Authentication/Authorization for this milestone.
# Endpoints are fully public and rely on client-side constraints.
# --------------------------------------------------------------------------

DATABASE_URL = os.environ.get('PROCTORAI_DEMO_DATABASE_URL', 'sqlite:///./proctoring.db')
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class CaseStatus(str, enum.Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    DISMISSED = "dismissed"

class SessionModel(Base):
    __tablename__ = "sessions"
    id = Column(Integer, primary_key=True, index=True)
    started_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc))

class DetectionModel(Base):
    __tablename__ = "detections"
    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("sessions.id"), nullable=True)
    type = Column(String, index=True)
    confidence = Column(Float)
    created_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc))

    case = relationship("CaseModel", back_populates="detection", uselist=False)

class CaseModel(Base):
    __tablename__ = "cases"
    id = Column(Integer, primary_key=True, index=True)
    detection_id = Column(Integer, ForeignKey("detections.id"))
    status = Column(SqlaEnum(CaseStatus), default=CaseStatus.PENDING)
    created_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc))

    detection = relationship("DetectionModel", back_populates="case")

Base.metadata.create_all(bind=engine)

class DetectionEventCreate(BaseModel):
    session_id: int | None = None
    type: str
    confidence: float
    timestamp: float | None = None

class CaseResponse(BaseModel):
    id: int
    detection_id: int
    type: str | None = None
    confidence: float | None = None
    status: CaseStatus
    created_at: datetime.datetime

    model_config = ConfigDict(from_attributes=True)

async def camera_alert_sink(payload):
    with SessionLocal() as db:
        result = await create_detection_event(DetectionEventCreate(**payload), db)
    return {**result, 'type': payload['type'], 'timestamp': payload['timestamp']}


monitor = ObjectMonitor(camera_alert_sink)


@asynccontextmanager
async def lifespan(_app):
    yield
    await asyncio.to_thread(monitor.stop, 30)


fastapi_app = FastAPI(lifespan=lifespan)

fastapi_app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins="*")
app = socketio.ASGIApp(sio, other_asgi_app=fastapi_app)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

ALERT_THRESHOLD = 0.75

@fastapi_app.post("/detection-event")
async def create_detection_event(event: DetectionEventCreate, db: Session = Depends(get_db)):
    db_detection = DetectionModel(
        session_id=event.session_id,
        type=event.type,
        confidence=event.confidence
    )
    db.add(db_detection)
    db.commit()
    db.refresh(db_detection)

    if event.confidence >= ALERT_THRESHOLD:
        db_case = CaseModel(
            detection_id=db_detection.id,
            status=CaseStatus.PENDING
        )
        db.add(db_case)
        db.commit()
        db.refresh(db_case)

        case_data = {
            "id": db_case.id,
            "detection_id": db_case.detection_id,
            "type": db_detection.type,
            "confidence": db_detection.confidence,
            "status": db_case.status.value,
            "created_at": db_case.created_at.isoformat()
        }
        await sio.emit("case_created", case_data)

    return {"message": "Detection recorded", "detection_id": db_detection.id}

@fastapi_app.get("/cases", response_model=list[CaseResponse])
def get_cases(db: Session = Depends(get_db)):
    cases = db.query(CaseModel).all()
    return [
        {
            "id": c.id,
            "detection_id": c.detection_id,
            "type": c.detection.type if c.detection else None,
            "confidence": c.detection.confidence if c.detection else None,
            "status": c.status,
            "created_at": c.created_at,
        }
        for c in cases
    ]

@fastapi_app.post("/cases/{case_id}/confirm")
async def confirm_case(case_id: int, db: Session = Depends(get_db)):
    db_case = db.query(CaseModel).filter(CaseModel.id == case_id).first()
    if not db_case:
        raise HTTPException(status_code=404, detail="Case not found")

    db_case.status = CaseStatus.CONFIRMED
    db.commit()
    db.refresh(db_case)

    case_data = {
        "id": db_case.id,
        "detection_id": db_case.detection_id,
        "status": db_case.status.value,
        "created_at": db_case.created_at.isoformat()
    }
    await sio.emit("case_updated", case_data)

    return {"message": "Case confirmed", "case_id": db_case.id}

@fastapi_app.post("/cases/{case_id}/dismiss")
async def dismiss_case(case_id: int, db: Session = Depends(get_db)):
    db_case = db.query(CaseModel).filter(CaseModel.id == case_id).first()
    if not db_case:
        raise HTTPException(status_code=404, detail="Case not found")

    db_case.status = CaseStatus.DISMISSED
    db.commit()
    db.refresh(db_case)

    case_data = {
        "id": db_case.id,
        "detection_id": db_case.detection_id,
        "status": db_case.status.value,
        "created_at": db_case.created_at.isoformat()
    }
    await sio.emit("case_updated", case_data)

    return {"message": "Case dismissed", "case_id": db_case.id}


@fastapi_app.get('/object-monitor/status')
def object_monitor_status():
    return monitor.status()


@fastapi_app.post('/object-monitor/start', status_code=202)
async def start_object_monitor(db: Session = Depends(get_db)):
    state = monitor.status()
    if state['running']:
        return state
    if state['phase'] == 'stopping':
        raise HTTPException(409, 'The camera is still stopping. Try again shortly.')
    session = SessionModel()
    db.add(session)
    db.commit()
    db.refresh(session)
    try:
        return monitor.start(session.id, asyncio.get_running_loop())
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc


@fastapi_app.post('/object-monitor/stop')
async def stop_object_monitor():
    return await asyncio.to_thread(monitor.stop)


@fastapi_app.get('/object-monitor/feed')
async def object_monitor_feed(run_id: int):
    state = monitor.status()
    if run_id != state['run_id'] or not state['running']:
        raise HTTPException(409, 'Start monitoring before opening this camera feed.')

    async def frames():
        previous = -1
        while True:
            state = monitor.status()
            if not state['running'] or state['run_id'] != run_id:
                break
            sequence, jpeg = monitor.latest_frame()
            if jpeg is not None and sequence != previous:
                previous = sequence
                yield (b'--frame\r\nContent-Type: image/jpeg\r\nContent-Length: '
                       + str(len(jpeg)).encode() + b'\r\n\r\n' + jpeg + b'\r\n')
            await asyncio.sleep(1/30)
    return StreamingResponse(frames(), media_type='multipart/x-mixed-replace; boundary=frame',
                             headers={'Cache-Control': 'no-store', 'X-Accel-Buffering': 'no'})
