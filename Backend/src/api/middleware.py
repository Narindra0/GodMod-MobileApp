from fastapi.middleware.cors import CORSMiddleware
from src.core import config
from .logging_middleware import SimplifiedLoggingMiddleware

def apply_cors(app: FastAPI) -> None:
    # Log Middleware en premier pour capturer tout
    app.add_middleware(SimplifiedLoggingMiddleware)
    
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.get_cors_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
