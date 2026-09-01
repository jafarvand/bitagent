from fastapi import FastAPI

from .api import router

app = FastAPI(
    title="bitAgent Options Paper Trading",
    version="0.1.0",
    description="Read-only Aevo market data plus governed paper options execution.",
)
app.include_router(router)


@app.get("/health")
def health():
    return {"status": "ok", "mode": "paper", "live_execution": False}
