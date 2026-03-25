import time
import logging
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi import Request

logger = logging.getLogger("API")

class SimplifiedLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # On ignore les routes trop répétitives (metrics, settings, etc.) dans les logs standards
        # mais on peut les garder en mode VERBOSE si besoin.
        ignored_paths = ["/metrics/overview", "/settings/ai", "/settings/prisma-ml", "/matches/next"]
        
        start_time = time.time()
        response = await call_next(request)
        process_time = (time.time() - start_time) * 1000
        
        path = request.url.path
        if path not in ignored_paths or response.status_code != 200:
            logger.info(f"{request.method} {path} -> {response.status_code} ({process_time:.1f}ms)")
            
        return response
