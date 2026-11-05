from __future__ import annotations

import logging
import random
import secrets
from datetime import date
from functools import lru_cache

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Path, Request

from magnitude_engine import daily_set, generate_problem

from .config import Settings
from .schemas import DailySetOut, GenerateIn, ProblemOut

log = logging.getLogger("problem-service")


async def require_internal_key(request: Request, x_internal_key: str | None = Header(default=None)) -> None:
    expected: str = request.app.state.settings.internal_api_key
    if not x_internal_key or not secrets.compare_digest(x_internal_key.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="invalid internal key")


@lru_cache(maxsize=64)
def _daily(key: str) -> tuple[ProblemOut, ...]:
    """The daily set is deterministic per date, so compute it once per process."""
    return tuple(ProblemOut.from_engine(p) for p in daily_set(key))


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    logging.basicConfig(level=settings.log_level)

    app = FastAPI(title="Magnitude problem service", version="0.1.0", docs_url=None, redoc_url=None)
    app.state.settings = settings

    @app.get("/healthz", include_in_schema=False)
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    internal = APIRouter(prefix="/internal", dependencies=[Depends(require_internal_key)])

    # Plain `def` endpoints: generation is CPU-bound, so FastAPI runs it in a worker thread
    # instead of blocking the event loop.
    @internal.post("/problems", response_model=ProblemOut)
    def generate(body: GenerateIn) -> ProblemOut:
        rng = random.Random().random  # seeded from OS entropy per request
        return ProblemOut.from_engine(generate_problem(body.skill, body.target_rating, rng))

    @internal.get("/daily/{day}", response_model=DailySetOut)
    def daily(day: str = Path(pattern=r"^\d{4}-\d{2}-\d{2}$")) -> DailySetOut:
        try:
            date.fromisoformat(day)
        except ValueError:
            raise HTTPException(status_code=422, detail="not a real calendar date") from None
        return DailySetOut(date=day, problems=list(_daily(day)))

    app.include_router(internal)
    return app
