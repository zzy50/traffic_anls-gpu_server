import logging
from typing import List

from fastapi import APIRouter, HTTPException, Path as FastAPIPath

from models.deepstream import InstanceInfo
from services.deepstream_manager import deepstream_manager
from services.websocket_manager import websocket_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/instances", tags=["인스턴스 관리"])


@router.get("/", response_model=List[InstanceInfo])
async def get_instances():
    """모든 DeepStream 인스턴스 조회"""
    instances = deepstream_manager.get_all_instances()
    result = []
    
    for instance in instances:
        result.append(InstanceInfo(
            instance_id=instance.instance_id,
            config_path=instance.config_path,
            streams_count=instance.streams_count,
            status=instance.status.value,
            ws_status=instance.ws_status.value if hasattr(instance.ws_status, 'value') else instance.ws_status,
            launched_at=instance.launched_at.isoformat() if instance.launched_at else None,
            log_path=instance.log_path
        ))
    
    return result


@router.get("/{instance_id}", response_model=InstanceInfo)
async def get_instance(instance_id: str = FastAPIPath(..., description="인스턴스 ID")):
    """특정 DeepStream 인스턴스 조회"""
    instance = deepstream_manager.get_instance(instance_id)
    if not instance:
        raise HTTPException(status_code=404, detail=f"인스턴스를 찾을 수 없습니다: {instance_id}")
    
    return InstanceInfo(
        instance_id=instance.instance_id,
        config_path=instance.config_path,
        streams_count=instance.streams_count,
        status=instance.status.value,
        ws_status=instance.ws_status.value if hasattr(instance.ws_status, 'value') else instance.ws_status,
        launched_at=instance.launched_at.isoformat() if instance.launched_at else None,
        log_path=instance.log_path
    )


@router.post("/{instance_id}/terminate")
async def terminate_instance(instance_id: str = FastAPIPath(..., description="인스턴스 ID")):
    """DeepStream 인스턴스 종료"""
    instance = deepstream_manager.get_instance(instance_id)
    if not instance:
        raise HTTPException(status_code=404, detail=f"인스턴스를 찾을 수 없습니다: {instance_id}")
    
    # WebSocket을 통해 종료 메시지 전송
    success = await websocket_manager.send_terminate_app(instance_id)
    
    if not success:
        raise HTTPException(status_code=500, detail="종료 메시지 전송에 실패했습니다")
    
    return {
        "status": "terminating",
        "instance_id": instance_id,
        "message": "종료 명령이 전송되었습니다"
    } 