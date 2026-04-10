import threading

import uvicorn
from fastapi import FastAPI
from src.core import config
from src.core.init_data import initialize_all

from .middleware import apply_cors
from .routes import register_routes


def create_app() -> FastAPI:
    app = FastAPI(title="GODMOD API", version="1.0.0", docs_url="/docs")
    # Hugging Face peut exécuter une stack FastAPI/Starlette légèrement différente.
    # On enregistre donc le hook startup avec un fallback compatible.
    if hasattr(app, "add_event_handler"):
        app.add_event_handler("startup", initialize_all)
    elif hasattr(app, "on_event"):
        app.on_event("startup")(initialize_all)
    else:
        initialize_all()
    apply_cors(app)
    register_routes(app)
    return app


def start_api_server(host: str = None, port: int = None):
    app = create_app()
    resolved_host = host or config.API_HOST
    resolved_port = port or config.API_PORT
    server_thread = threading.Thread(
        target=uvicorn.run,
        args=(app,),
        kwargs={
            "host": resolved_host, 
            "port": resolved_port, 
            "log_level": "info",
            "access_log": False # On désactive le log bruyant par défaut
        },
        daemon=True,
        name="api-server",
    )
    server_thread.start()
    return server_thread
