"""Sales portal API (FastAPI). Run: uvicorn app.main:app --reload"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .db import CORS_ORIGINS, Base, engine
from .routers import attendance, auth, dashboard, expenses, integration, masters, org, sales


@asynccontextmanager
async def lifespan(_app):
    Base.metadata.create_all(engine)    # creates missing tables; database/schema.sql has the same structure
    yield


app = FastAPI(title="Sales portal API", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


@app.get("/api/health")
def health():
    return {"ok": True}


for r in (auth, org, masters, sales, expenses, attendance, dashboard, integration):
    app.include_router(r.router)
