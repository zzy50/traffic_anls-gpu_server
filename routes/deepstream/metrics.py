import logging
from typing import List

from fastapi import APIRouter, HTTPException, Path as FastAPIPath

from models.deepstream import InstanceMetrics
from services.deepstream_manager import deepstream_manager
from services.websocket_manager import websocket_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/metrics", tags=["메트릭"])


@router.get("/", response_model=List[InstanceMetrics])
async def get_all_metrics():
    """모든 인스턴스의 메트릭 조회"""
    result = []
    
    for instance in deepstream_manager.get_all_instances():
        if instance.last_metrics:
            result.append(InstanceMetrics(
                instance_id=instance.instance_id,
                cpu_percent=instance.last_metrics.get("cpu_percent", 0.0),
                ram_mb=instance.last_metrics.get("ram_mb", 0.0),
                gpu_percent=instance.last_metrics.get("gpu_percent", 0.0),
                vram_mb=instance.last_metrics.get("vram_mb", 0.0),
                timestamp=instance.last_metrics_time.isoformat() if instance.last_metrics_time else ""
            ))
    
    return result


@router.get("/{instance_id}", response_model=InstanceMetrics)
async def get_instance_metrics(instance_id: str = FastAPIPath(..., description="인스턴스 ID")):
    """특정 인스턴스의 메트릭 조회"""
    instance = deepstream_manager.get_instance(instance_id)
    if not instance:
        raise HTTPException(status_code=404, detail=f"인스턴스를 찾을 수 없습니다: {instance_id}")
    
    if not instance.last_metrics:
        raise HTTPException(status_code=404, detail="메트릭 데이터가 없습니다")
    
    return InstanceMetrics(
        instance_id=instance.instance_id,
        cpu_percent=instance.last_metrics.get("cpu_percent", 0.0),
        ram_mb=instance.last_metrics.get("ram_mb", 0.0),
        gpu_percent=instance.last_metrics.get("gpu_percent", 0.0),
        vram_mb=instance.last_metrics.get("vram_mb", 0.0),
        timestamp=instance.last_metrics_time.isoformat() if instance.last_metrics_time else ""
    )


@router.post("/{instance_id}/refresh")
async def refresh_instance_metrics(instance_id: str = FastAPIPath(..., description="인스턴스 ID")):
    """특정 인스턴스의 메트릭 새로고침 요청"""
    instance = deepstream_manager.get_instance(instance_id)
    if not instance:
        raise HTTPException(status_code=404, detail=f"인스턴스를 찾을 수 없습니다: {instance_id}")
    
    # WebSocket을 통해 메트릭 조회 메시지 전송
    success = await websocket_manager.send_query_metrics(instance_id)
    
    if not success:
        raise HTTPException(status_code=500, detail="메트릭 조회 메시지 전송에 실패했습니다")
    
    return {
        "status": "requested",
        "instance_id": instance_id,
        "message": "메트릭 조회 요청이 전송되었습니다"
    } 