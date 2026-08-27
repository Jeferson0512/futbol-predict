from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from futpredict.api.routes import router


def create_app() -> FastAPI:
    app = FastAPI(
        title="Futbol Predict API",
        version="0.1.0",
        description="API local para prediccion probabilistica 1X2.",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=False,
        allow_methods=["GET"],
        allow_headers=["*"],
    )
    app.include_router(router)
    return app


app = create_app()
