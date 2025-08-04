import logging
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Path as FastAPIPath

from models.deepstream import AnalysisRequest, StartAnalysisResponse
from services.deepstream_manager import deepstream_manager
from services.websocket_manager import websocket_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/analysis", tags=["분석 제어"])


@router.post("/start", response_model=StartAnalysisResponse)
async def start_analysis(request: AnalysisRequest):
    """영상 분석 시작"""
    # 사용 가능한 인스턴스와 스트림 찾기
    available_instance = None
    available_stream = None
    
    for instance in deepstream_manager.get_all_instances():
        if instance.ws_status == "connected":
            stream_id = deepstream_manager.get_available_stream(instance.instance_id)
            if stream_id is not None:
                available_instance = instance
                available_stream = stream_id
                break
    
    if not available_instance or available_stream is None:
        raise HTTPException(
            status_code=503, 
            detail="사용 가능한 스트림 슬롯이 없습니다"
        )
    
    # 분석 시작 시도
    success = deepstream_manager.start_analysis(
        available_instance.instance_id,
        available_stream,
        request.camera_id,
        request.type,
        request.path,
        request.name,
        request.output_dir
    )
    
    if not success:
        raise HTTPException(
            status_code=500,
            detail="분석 시작에 실패했습니다"
        )
    
    # 파일이 제공된 경우 파일 정보 추가
    if request.files:
        deepstream_manager.add_files_to_camera(
            available_instance.instance_id,
            request.camera_id,
            request.files
        )
    
    # WebSocket을 통해 DeepStream에 분석 시작 메시지 전송
    ws_success = await websocket_manager.send_start_analysis(
        available_instance.instance_id,
        available_stream,
        request.camera_id,
        request.type.value,
        request.path,
        request.name,
        request.output_dir
    )
    
    if ws_success and request.files:
        # 파일 목록도 전송
        await websocket_manager.send_push_file(
            available_instance.instance_id,
            available_stream,
            request.camera_id,
            request.files
        )
    
    request_id = str(uuid.uuid4())
    
    return StartAnalysisResponse(
        request_id=request_id,
        instance_id=available_instance.instance_id,
        stream_id=available_stream,
        camera_id=request.camera_id,
        status="started" if ws_success else "failed",
        message=f"Stream {available_stream}에서 분석 시작됨" if ws_success else "WebSocket 메시지 전송 실패"
    )


@router.post("/{instance_id}/interrupt")
async def interrupt_analysis(
    instance_id: str = FastAPIPath(..., description="인스턴스 ID"),
    stream_id: int = Query(..., description="스트림 ID"),
    camera_id: int = Query(..., description="카메라 ID"),
    reason: str = Query("user_cancelled", description="중단 사유")
):
    """분석 중단"""
    instance = deepstream_manager.get_instance(instance_id)
    if not instance:
        raise HTTPException(status_code=404, detail=f"인스턴스를 찾을 수 없습니다: {instance_id}")
    
    # WebSocket을 통해 중단 메시지 전송
    success = await websocket_manager.send_interrupt_analysis(
        instance_id, stream_id, camera_id, reason
    )
    
    if not success:
        raise HTTPException(status_code=500, detail="중단 메시지 전송에 실패했습니다")
    
    return {
        "status": "interrupted",
        "instance_id": instance_id,
        "stream_id": stream_id,
        "camera_id": camera_id,
        "reason": reason
    }


@router.get("/status")
async def get_all_analysis_status():
    """모든 인스턴스의 분석 상태 조회"""
    result = {}
    
    for instance in deepstream_manager.get_all_instances():
        status = deepstream_manager.get_analysis_status(instance.instance_id)
        if status:
            result[instance.instance_id] = status
    
    return result


@router.get("/status/{instance_id}")
async def get_instance_analysis_status(
    instance_id: str = FastAPIPath(..., description="인스턴스 ID"),
    stream_id: Optional[int] = Query(None, description="특정 스트림 ID"),
    camera_id: Optional[int] = Query(None, description="특정 카메라 ID")
):
    """특정 인스턴스의 분석 상태 조회"""
    instance = deepstream_manager.get_instance(instance_id)
    if not instance:
        raise HTTPException(status_code=404, detail=f"인스턴스를 찾을 수 없습니다: {instance_id}")
    
    status = deepstream_manager.get_analysis_status(instance_id, stream_id, camera_id)
    if not status:
        raise HTTPException(status_code=404, detail="분석 상태를 찾을 수 없습니다")
    
    return {
        "instance_id": instance_id,
        "timestamp": datetime.now().isoformat(),
        **status
    } 