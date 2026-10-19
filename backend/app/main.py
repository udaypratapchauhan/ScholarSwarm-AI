"""FastAPI entry point for ScholarSwarm AI backend.

Exposes application health diagnostics and initializes the persistence layer.
"""

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import AsyncGenerator

from fastapi import FastAPI, Response, status
from fastapi.middleware.cors import CORSMiddleware

from backend.app.database import check_db_health, init_db
from backend.app.schemas import HealthResponse


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Initialize database tables on application startup."""
    init_db()
    yield


app = FastAPI(
    title="ScholarSwarm AI Backend",
    description="Multi-Agent Scholarship Discovery and Verification Platform API",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS configuration for development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get(
    "/api/health",
    response_model=HealthResponse,
    summary="Application Health Check",
    description="Validates service health and SQLite database connectivity via SELECT 1.",
)
def get_health(response: Response) -> HealthResponse:
    """Execute connectivity check against SQLite persistence layer.

    Returns HTTP 200 with status=healthy when database responds.
    Returns HTTP 503 with status=unhealthy when database connectivity fails.
    """
    is_healthy, db_status = check_db_health()
    now = datetime.now(timezone.utc)

    if is_healthy:
        response.status_code = status.HTTP_200_OK
        return HealthResponse(
            status="healthy",
            database="connected",
            version="0.1.0",
            timestamp=now,
        )

    response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthResponse(
        status="unhealthy",
        database="disconnected",
        version="0.1.0",
        timestamp=now,
    )
