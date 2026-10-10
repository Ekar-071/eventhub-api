from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models, schemas
from .db import Base, engine, get_db
from .security import create_token, decode_token, hash_password, verify_password


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(engine)
    yield


app = FastAPI(title="EventHub API", version="1.0.0", lifespan=lifespan)
# Ouvert pour le développement : à restreindre en production.
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

bearer = HTTPBearer(auto_error=False)


def current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> models.User:
    user_id = decode_token(creds.credentials) if creds else None
    user = db.get(models.User, user_id) if user_id else None
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentification requise")
    return user


def to_out(event: models.Event) -> schemas.EventOut:
    return schemas.EventOut(
        id=event.id,
        owner_id=event.owner_id,
        title=event.title,
        description=event.description,
        location=event.location,
        starts_at=event.starts_at,
        capacity=event.capacity,
        registrations_count=len(event.registrations),
    )


def get_event_or_404(db: Session, event_id: int) -> models.Event:
    event = db.get(models.Event, event_id)
    if event is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Événement introuvable")
    return event


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/auth/register", response_model=schemas.UserOut, status_code=201)
def register(data: schemas.UserCreate, db: Session = Depends(get_db)):
    if db.scalar(select(models.User).where(models.User.email == data.email)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Email déjà utilisé")
    user = models.User(email=data.email, password_hash=hash_password(data.password))
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@app.post("/auth/login", response_model=schemas.Token)
def login(data: schemas.UserCreate, db: Session = Depends(get_db)):
    user = db.scalar(select(models.User).where(models.User.email == data.email))
    if user is None or not verify_password(data.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Identifiants invalides")
    return schemas.Token(access_token=create_token(user.id))


@app.get("/events", response_model=list[schemas.EventOut])
def list_events(
    q: str | None = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    stmt = select(models.Event).order_by(models.Event.starts_at)
    if q:
        stmt = stmt.where(models.Event.title.ilike(f"%{q}%"))
    return [to_out(e) for e in db.scalars(stmt.offset(skip).limit(limit))]


@app.post("/events", response_model=schemas.EventOut, status_code=201)
def create_event(
    data: schemas.EventIn,
    user: models.User = Depends(current_user),
    db: Session = Depends(get_db),
):
    event = models.Event(**data.model_dump(), owner_id=user.id)
    db.add(event)
    db.commit()
    db.refresh(event)
    return to_out(event)


@app.get("/events/{event_id}", response_model=schemas.EventOut)
def read_event(event_id: int, db: Session = Depends(get_db)):
    return to_out(get_event_or_404(db, event_id))


@app.put("/events/{event_id}", response_model=schemas.EventOut)
def update_event(
    event_id: int,
    data: schemas.EventIn,
    user: models.User = Depends(current_user),
    db: Session = Depends(get_db),
):
    event = get_event_or_404(db, event_id)
    if event.owner_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Réservé à l'organisateur")
    for key, value in data.model_dump().items():
        setattr(event, key, value)
    db.commit()
    db.refresh(event)
    return to_out(event)


@app.delete("/events/{event_id}", status_code=204)
def delete_event(
    event_id: int,
    user: models.User = Depends(current_user),
    db: Session = Depends(get_db),
):
    event = get_event_or_404(db, event_id)
    if event.owner_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Réservé à l'organisateur")
    db.delete(event)
    db.commit()


@app.post("/events/{event_id}/register", status_code=201)
def register_to_event(
    event_id: int,
    user: models.User = Depends(current_user),
    db: Session = Depends(get_db),
):
    event = get_event_or_404(db, event_id)
    if any(r.user_id == user.id for r in event.registrations):
        raise HTTPException(status.HTTP_409_CONFLICT, "Déjà inscrit")
    if len(event.registrations) >= event.capacity:
        raise HTTPException(status.HTTP_409_CONFLICT, "Événement complet")
    db.add(models.Registration(event_id=event.id, user_id=user.id))
    db.commit()
    return {"detail": "Inscription confirmée"}
