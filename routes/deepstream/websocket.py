import logging

from fastapi import APIRouter, WebSocket
from services.websocket_manager import websocket_manager
from services.process_launcher import process_launcher

logger = logging.getLogger(__name__)

router = APIRouter(tags=["WebSocket"])


@router.get("/health")
async def health_check():
    """헬스 체크"""
    all_processes = process_launcher.get_all_processes()
    running_processes = [p for p in all_processes if p.status == "running"]
    
    from services.deepstream_manager import deepstream_manager
    
    return {
        "status": "ok",
        "connected_instances": websocket_manager.get_connected_instances(),
        "total_instances": len(deepstream_manager.get_all_instances()),
        "total_processes": len(all_processes),
        "running_processes": len(running_processes)
    }


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