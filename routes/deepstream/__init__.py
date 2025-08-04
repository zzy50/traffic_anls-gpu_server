from fastapi import APIRouter

from .processes import router as processes_router
from .instances import router as instances_router  
from .analysis import router as analysis_router
from .metrics import router as metrics_router
from .websocket import router as websocket_router

# 메인 DeepStream 라우터
router = APIRouter(prefix="/deepstream", tags=["DeepStream 제어"])

# 하위 라우터들 포함
router.include_router(processes_router)
router.include_router(instances_router)
router.include_router(analysis_router) 
router.include_router(metrics_router)
router.include_router(websocket_router) 