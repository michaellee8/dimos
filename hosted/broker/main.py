# Copyright 2026 Dimensional Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import asyncio
from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Must run before any module-level loggers get created, else the root logger
# stays at WARNING and every INFO log below is silently dropped.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

from config import settings
from metrics import install as install_metrics
from models.database import init_db
from ratelimit import install as install_rate_limit
from routers import auth, keys, sessions
from routers.sessions import operator_reaper_loop
from services.auth import register_robot_key


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()

    if settings.environment == "dev":
        dev_key = "dev-robot-key-change-me"
        register_robot_key(dev_key, "dev-robot")
        print(f"[dev] robot key registered: {dev_key} → dev-robot")

    reaper = asyncio.create_task(operator_reaper_loop())
    try:
        yield
    finally:
        reaper.cancel()


app = FastAPI(
    title="dimos-teleop",
    description="Session microservice for hosted teleoperation",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.public_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Module-level handle so tests (and a future admin toggle) can flip .enforce
# at runtime.
rate_limiter = install_rate_limit(app, enforce=settings.rate_limit_enforce)

# Loopback-only in prod (Caddy doesn't proxy it).
install_metrics(app)

app.include_router(auth.router, prefix="/api/v1")
app.include_router(keys.router, prefix="/api/v1")
app.include_router(sessions.router, prefix="/api/v1")


@app.get("/health")
async def health():
    return {"status": "ok", "service": "dimos-teleop", "environment": settings.environment}
