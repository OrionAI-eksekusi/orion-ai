from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers import chat, auth
from app.routers import zenith
from contextlib import asynccontextmanager

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
    # Start ARQ worker sebagai background process
    import subprocess, sys, os
    arq_env = os.environ.copy()
    arq_process = subprocess.Popen(
        [sys.executable, "-m", "arq", "app.workers.arq_worker.WorkerSettings"],
        cwd=os.getcwd(),
        env=arq_env
    )
    print("[STARTUP] ✅ ARQ worker started!")
    yield
    arq_process.terminate()
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