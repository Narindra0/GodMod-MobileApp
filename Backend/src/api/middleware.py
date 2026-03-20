from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from src.core import config


def apply_cors(app: FastAPI) -> None:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.get_cors_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
