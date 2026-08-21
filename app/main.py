from fastapi import FastAPI

from app.api.health import router as health_router
from app.api.ocr import router as ocr_router

app = FastAPI(title="backend-record")

app.include_router(health_router)
app.include_router(ocr_router)
