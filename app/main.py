"""FastAPI entry point for the local ErgoStudy study dashboard."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import StudyDatabase
from app.posture import PostureAnalysisManager
from app.routers import metrics, posture, sessions, statistics, subjects
from app.study import StudySessionManager


@asynccontextmanager
async def lifespan(application: FastAPI):
    database = StudyDatabase()
    application.state.database = database
    application.state.study = StudySessionManager(database)
    application.state.posture = PostureAnalysisManager()
    yield
    application.state.posture.close()
    manager = application.state.study
    if manager.status()["active"]:
        manager.stop()


app = FastAPI(title="ErgoStudy API", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type"],
)
app.include_router(subjects.router)
app.include_router(sessions.router)
app.include_router(metrics.router)
app.include_router(posture.router)
app.include_router(statistics.router)


@app.get("/api/health", tags=["health"])
def health() -> dict[str, str]:
    return {"status": "ok"}
