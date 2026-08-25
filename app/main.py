from fastapi import FastAPI

from app.api.health import router as health_router
from app.api.ocr import router as ocr_router
from app.api.scraps import router as scraps_router

app = FastAPI(title="backend-record")

app.include_router(health_router)
app.include_router(ocr_router)
app.include_router(scraps_router)
