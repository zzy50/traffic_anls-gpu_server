import logging
import psutil
from datetime import datetime, timezone

from fastapi import APIRouter, WebSocket
from fastapi.responses import JSONResponse
from services.websocket_manager import websocket_manager
from services.process_launcher import process_launcher

logger = logging.getLogger(__name__)

router = APIRouter(tags=["WebSocket"])


@router.get("/health")
async def health_check():
    """DeepStream 클라이언트가 재연결 전 호출하는 Health Check API"""
    all_processes = process_launcher.get_all_processes()
    running_processes = [p for p in all_processes if p.status == "running"]
    
    from services.deepstream_manager import deepstream_manager
    
    # 서버 종료 상태 확인
    is_shutting_down = websocket_manager.is_shutting_down()
    
    # WebSocket 연결 통계 정보
    ws_stats = websocket_manager.get_connection_stats()
    
    # 시스템 정보 수집
    try:
        cpu_percent = psutil.cpu_percent(interval=0.1)
        memory = psutil.virtual_memory()
        boot_time = psutil.boot_time()
        current_time = datetime.now(timezone.utc).timestamp()
        uptime_seconds = current_time - boot_time
    except Exception as e:
        logger.warning(f"시스템 정보 수집 실패: {e}")
        cpu_percent = 0
        memory = None
        uptime_seconds = 0
    
    health_data = {
        "status": "shutting_down" if is_shutting_down else "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "connected_instances": websocket_manager.get_connected_instances(),
        "total_instances": len(deepstream_manager.get_all_instances()),
        "total_processes": len(all_processes),
        "running_processes": len(running_processes),
        "websocket": {
            "total_connections": ws_stats["total_connections"],
            "authenticated_connections": ws_stats["authenticated_connections"],
            "unauthenticated_connections": ws_stats["unauthenticated_connections"],
            "is_shutting_down": is_shutting_down
        },
        "system": {
            "cpu_usage": round(cpu_percent, 2),
            "memory_usage": {
                "total": memory.total if memory else 0,
                "available": memory.available if memory else 0,
                "percent": round(memory.percent, 2) if memory else 0
            },
            "uptime_seconds": int(uptime_seconds)
        }
    }
    
    # 종료 중일 때는 503 상태 코드 반환
    status_code = 503 if is_shutting_down else 200
    
    return JSONResponse(content=health_data, status_code=status_code)


@router.get("/stats")
async def get_websocket_stats():
    """WebSocket 상세 통계 정보 조회 (모니터링용)"""
    return websocket_manager.get_detailed_stats()


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """DeepStream 인스턴스와의 WebSocket 연결"""
    connection_id = await websocket_manager.connect(websocket)
    logger.info(f"새로운 WebSocket 연결: {connection_id}")
    
    try:
        await websocket_manager.handle_connection(connection_id)
    except Exception as e:
        logger.error(f"WebSocket 연결 처리 오류: {e}")
    finally:
        websocket_manager.disconnect(connection_id) 