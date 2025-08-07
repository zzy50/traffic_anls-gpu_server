import logging
import os
from pathlib import Path
from uvicorn import Config, Server
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from logging.handlers import RotatingFileHandler

from routes.deepstream import router as deepstream_router

log_dir = Path("logs")
log_dir.mkdir(exist_ok=True)
log_file = log_dir / "gpu_server.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s.%(msecs)03d - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        RotatingFileHandler(log_file, maxBytes=5*1024*1024, backupCount=5, encoding="utf-8"),
        logging.StreamHandler()
    ]
)

uvicorn_access_logger = logging.getLogger("uvicorn.access")
uvicorn_access_logger.handlers = []
access_handler = RotatingFileHandler(log_file, maxBytes=5*1024*1024, backupCount=5, encoding="utf-8")
access_formatter = logging.Formatter(
    fmt="%(asctime)s.%(msecs)03d - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
access_handler.setFormatter(access_formatter)
uvicorn_access_logger.addHandler(access_handler)

uvicorn_error_logger = logging.getLogger("uvicorn.error")
uvicorn_error_logger.handlers = []
error_handler = RotatingFileHandler(log_file, maxBytes=5*1024*1024, backupCount=5, encoding="utf-8")
error_handler.setFormatter(access_formatter)
uvicorn_error_logger.addHandler(error_handler)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logging.info("Starting application...")
    yield
    # Shutdown
    logging.info("Stopping application...")

app = FastAPI(
    title="DeepStream 관리 API",
    description="DeepStream 인스턴스와 분석 작업을 관리할 수 있는 API 서비스",
    version="1.0.0",
    lifespan=lifespan
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# DeepStream 라우터 등록
app.include_router(deepstream_router)

@app.get("/", tags=["Root"])
async def root():
    return {
        "message": "Deepstream API Server가 정상적으로 실행 중입니다",
        "version": "1.0.0",
        "docs_url": "/docs"
    }

@app.get("/health", tags=["Health"])
async def health_check():
    return {"status": "healthy"}

if __name__ == "__main__":
    config = Config(
        app="main:app",
        host="0.0.0.0",
        port=18000,
        reload=False,
    )
    server = Server(config)
    server.run()

    # uvicorn main:app --host localhost --port 18000 --reload 2>&1 | tee -a log/fastapi.log &