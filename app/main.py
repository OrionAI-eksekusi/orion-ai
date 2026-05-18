from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app.routers import chat, auth
from app.routers import zenith
from contextlib import asynccontextmanager
import logging
import traceback

logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Init database saat startup
    from app.services.database_service import init_db
    from app.services.memory_service import init_memory_db
    from app.services.zenith_service import init_zenith_db
    try:
        init_db()
        init_memory_db()
        init_zenith_db()
        import asyncio
        from app.services.schema_service import init_apex_schema
        asyncio.create_task(init_apex_schema())
        print("[STARTUP] ✅ Database initialized!")
    except Exception as e:
        print(f"[STARTUP] ❌ DB init error: {e}")
    # Start ARQ worker sebagai asyncio task
    import asyncio
    from arq.worker import create_worker
    from app.workers.arq_worker import WorkerSettings

    async def run_worker():
        worker = create_worker(WorkerSettings)
        await worker.async_run()

    arq_task = asyncio.create_task(run_worker())
    print("[STARTUP] ✅ ARQ worker started!")
    yield
    arq_task.cancel()
    print("[SHUTDOWN] ARQ worker stopped.")

app = FastAPI(
    title="Orion AI",
    description="AI Execution System",
    version="2.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Global Error Handler ──────────────────────────────
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    error_detail = traceback.format_exc()
    logger.error(f"[UNHANDLED ERROR] {request.method} {request.url}\n{error_detail}")
    return JSONResponse(
        status_code=500,
        content={
            "status": "error",
            "message": "Internal server error",
            "path": str(request.url),
        }
    )

@app.exception_handler(404)
async def not_found_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=404,
        content={"status": "error", "message": f"Endpoint tidak ditemukan: {request.url.path}"}
    )

app.include_router(chat.router)
app.include_router(zenith.router)
app.include_router(auth.router)

@app.get("/")
def root():
    return {
        "status": "Orion AI is running 🚀",
        "version": "2.0.0",
        "modules": ["chat", "zenith"]
    }