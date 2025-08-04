import asyncio
import json
import logging
import uuid
from datetime import datetime
from typing import List, Optional, Dict, Any
from pathlib import Path

from fastapi import APIRouter, HTTPException, WebSocket, Query, Path as FastAPIPath
from pydantic import BaseModel

from services.deepstream_manager import deepstream_manager, InstanceStatus
from services.websocket_manager import websocket_manager
from services.process_launcher import process_launcher, ProcessInfo
from models.websocket_messages import AnalysisType

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/deepstream", tags=["DeepStream 제어"])


# Pydantic 모델들
class AnalysisRequest(BaseModel):
    """분석 요청 모델"""
    camera_id: int
    type: AnalysisType
    path: str
    name: str
    output_dir: str
    files: Optional[List[Dict]] = None


class StartAnalysisResponse(BaseModel):
    """분석 시작 응답 모델"""
    request_id: str
    instance_id: str
    stream_id: int
    camera_id: int
    status: str
    message: Optional[str] = None


class InstanceInfo(BaseModel):
    """인스턴스 정보 모델"""
    instance_id: str
    config_path: str
    streams_count: int
    gpu_allocated: List[int]
    status: str
    ws_status: str
    launched_at: Optional[str] = None
    log_path: Optional[str] = None


class InstanceMetrics(BaseModel):
    """인스턴스 메트릭 모델"""
    instance_id: str
    cpu_percent: float
    ram_mb: float
    gpu_percent: float
    vram_mb: float
    timestamp: str


class LaunchRequest(BaseModel):
    """DeepStream 앱 실행 요청 모델"""
    config_path: str
    streams_count: Optional[int] = None
    gpu_allocated: Optional[List[int]] = None
    instance_id: Optional[str] = None
    docker_container: Optional[str] = None
    additional_args: Optional[List[str]] = None


class LaunchResponse(BaseModel):
    """DeepStream 앱 실행 응답 모델"""
    success: bool
    message: str
    process_id: Optional[str] = None
    instance_id: Optional[str] = None
    host_pid: Optional[int] = None
    log_path: Optional[str] = None


class ProcessStatusInfo(BaseModel):
    """프로세스 상태 정보 모델"""
    process_id: str
    instance_id: str
    config_path: str
    docker_container: str
    host_pid: Optional[int] = None
    container_pid: Optional[int] = None
    status: str
    launched_at: str
    log_path: Optional[str] = None
    command: Optional[str] = None
    error_message: Optional[str] = None


class ProcessListResponse(BaseModel):
    """프로세스 목록 응답 모델"""
    total_count: int
    running_count: int
    stopped_count: int
    error_count: int
    processes: List[ProcessStatusInfo]


class LogResponse(BaseModel):
    """로그 조회 응답 모델"""
    success: bool
    message: str
    log_content: Optional[str] = None
    lines_requested: int
    process_id: str


# 헬스 체크 엔드포인트
@router.get("/health")
async def health_check():
    """헬스 체크"""
    all_processes = process_launcher.get_all_processes()
    running_processes = [p for p in all_processes if p.status == "running"]
    
    return {
        "status": "ok",
        "connected_instances": websocket_manager.get_connected_instances(),
        "total_instances": len(deepstream_manager.get_all_instances()),
        "total_processes": len(all_processes),
        "running_processes": len(running_processes)
    }


# 프로세스 관리 엔드포인트들
@router.post("/launch", response_model=LaunchResponse)
async def launch_deepstream_app(request: LaunchRequest):
    """DeepStream 앱 실행"""
    success, message, process_info = await process_launcher.launch_deepstream_app(
        config_path=request.config_path,
        streams_count=request.streams_count,
        gpu_allocated=request.gpu_allocated,
        instance_id=request.instance_id,
        docker_container=request.docker_container,
        additional_args=request.additional_args
    )
    
    if success and process_info:
        return LaunchResponse(
            success=True,
            message=message,
            process_id=process_info.process_id,
            instance_id=process_info.instance_id,
            host_pid=process_info.host_pid,
            log_path=process_info.log_path
        )
    else:
        # HTTP 500 대신 성공=False로 응답
        return LaunchResponse(
            success=False,
            message=message
        )


@router.get("/processes", response_model=ProcessListResponse)
async def get_all_processes():
    """모든 DeepStream 프로세스 목록 조회"""
    all_processes = process_launcher.get_all_processes()
    
    # 상태별 개수 집계
    running_count = len([p for p in all_processes if p.status == "running"])
    stopped_count = len([p for p in all_processes if p.status == "stopped"])
    error_count = len([p for p in all_processes if p.status == "error"])
    
    # ProcessStatusInfo 모델로 변환
    process_list = []
    for process in all_processes:
        process_list.append(ProcessStatusInfo(
            process_id=process.process_id,
            instance_id=process.instance_id,
            config_path=process.config_path,
            docker_container=process.docker_container,
            host_pid=process.host_pid,
            container_pid=process.container_pid,
            status=process.status,
            launched_at=process.launched_at.isoformat(),
            log_path=process.log_path,
            command=process.command,
            error_message=process.error_message
        ))
    
    return ProcessListResponse(
        total_count=len(all_processes),
        running_count=running_count,
        stopped_count=stopped_count,
        error_count=error_count,
        processes=process_list
    )


@router.get("/processes/{process_id}", response_model=ProcessStatusInfo)
async def get_process_status(process_id: str = FastAPIPath(..., description="프로세스 ID")):
    """특정 프로세스 상태 조회"""
    process = process_launcher.get_process_info(process_id)
    if not process:
        raise HTTPException(status_code=404, detail=f"프로세스를 찾을 수 없습니다: {process_id}")
    
    # 실시간 상태 확인
    await process_launcher.check_process_status(process_id)
    
    return ProcessStatusInfo(
        process_id=process.process_id,
        instance_id=process.instance_id,
        config_path=process.config_path,
        docker_container=process.docker_container,
        host_pid=process.host_pid,
        container_pid=process.container_pid,
        status=process.status,
        launched_at=process.launched_at.isoformat(),
        log_path=process.log_path,
        command=process.command,
        error_message=process.error_message
    )


@router.post("/processes/{process_id}/terminate")
async def terminate_process(process_id: str = FastAPIPath(..., description="프로세스 ID")):
    """DeepStream 프로세스 종료"""
    success, message = await process_launcher.terminate_process(process_id)
    
    if not success:
        raise HTTPException(status_code=500, detail=message)
    
    return {
        "success": True,
        "message": message,
        "process_id": process_id
    }


@router.get("/processes/{process_id}/logs", response_model=LogResponse)
async def get_process_logs(
    process_id: str = FastAPIPath(..., description="프로세스 ID"),
    lines: int = Query(100, description="조회할 로그 라인 수", ge=1, le=1000)
):
    """프로세스 로그 조회"""
    success, message, log_content = process_launcher.get_process_logs(process_id, lines)
    
    return LogResponse(
        success=success,
        message=message,
        log_content=log_content,
        lines_requested=lines,
        process_id=process_id
    )


@router.get("/processes/by-instance/{instance_id}", response_model=ProcessStatusInfo)
async def get_process_by_instance_id(instance_id: str = FastAPIPath(..., description="인스턴스 ID")):
    """인스턴스 ID로 프로세스 조회"""
    process = process_launcher.get_process_by_instance_id(instance_id)
    if not process:
        raise HTTPException(status_code=404, detail=f"인스턴스를 찾을 수 없습니다: {instance_id}")
    
    # 실시간 상태 확인
    await process_launcher.check_process_status(process.process_id)
    
    return ProcessStatusInfo(
        process_id=process.process_id,
        instance_id=process.instance_id,
        config_path=process.config_path,
        docker_container=process.docker_container,
        host_pid=process.host_pid,
        container_pid=process.container_pid,
        status=process.status,
        launched_at=process.launched_at.isoformat(),
        log_path=process.log_path,
        command=process.command,
        error_message=process.error_message
    )


@router.post("/processes/cleanup")
async def cleanup_stopped_processes():
    """중지된 프로세스들 정리"""
    await process_launcher.cleanup_stopped_processes()
    
    return {
        "success": True,
        "message": "중지된 프로세스들이 정리되었습니다",
        "timestamp": datetime.now().isoformat()
    }


# 인스턴스 관리 엔드포인트들
@router.get("/instances", response_model=List[InstanceInfo])
async def get_instances():
    """모든 DeepStream 인스턴스 조회"""
    instances = deepstream_manager.get_all_instances()
    result = []
    
    for instance in instances:
        result.append(InstanceInfo(
            instance_id=instance.instance_id,
            config_path=instance.config_path,
            streams_count=instance.streams_count,
            gpu_allocated=instance.gpu_allocated,
            status=instance.status.value,
            ws_status=instance.ws_status.value if hasattr(instance.ws_status, 'value') else instance.ws_status,
            launched_at=instance.launched_at.isoformat() if instance.launched_at else None,
            log_path=instance.log_path
        ))
    
    return result


@router.get("/instances/{instance_id}", response_model=InstanceInfo)
async def get_instance(instance_id: str = FastAPIPath(..., description="인스턴스 ID")):
    """특정 DeepStream 인스턴스 조회"""
    instance = deepstream_manager.get_instance(instance_id)
    if not instance:
        raise HTTPException(status_code=404, detail=f"인스턴스를 찾을 수 없습니다: {instance_id}")
    
    return InstanceInfo(
        instance_id=instance.instance_id,
        config_path=instance.config_path,
        streams_count=instance.streams_count,
        gpu_allocated=instance.gpu_allocated,
        status=instance.status.value,
        ws_status=instance.ws_status.value if hasattr(instance.ws_status, 'value') else instance.ws_status,
        launched_at=instance.launched_at.isoformat() if instance.launched_at else None,
        log_path=instance.log_path
    )


# 분석 제어 엔드포인트들
@router.post("/analysis/start", response_model=StartAnalysisResponse)
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


@router.post("/analysis/{instance_id}/interrupt")
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


@router.post("/instances/{instance_id}/terminate")
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


# 상태 조회 엔드포인트들
@router.get("/analysis/status")
async def get_all_analysis_status():
    """모든 인스턴스의 분석 상태 조회"""
    result = {}
    
    for instance in deepstream_manager.get_all_instances():
        status = deepstream_manager.get_analysis_status(instance.instance_id)
        if status:
            result[instance.instance_id] = status
    
    return result


@router.get("/analysis/status/{instance_id}")
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


# 메트릭 엔드포인트들
@router.get("/metrics", response_model=List[InstanceMetrics])
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


@router.get("/metrics/{instance_id}", response_model=InstanceMetrics)
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


@router.post("/metrics/{instance_id}/refresh")
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


# 테스트 엔드포인트들 (샘플 데이터 기반)
@router.get("/test/sample-data")
async def get_sample_data():
    """샘플 데이터 조회 (테스트용)"""
    return deepstream_manager.sample_data


@router.post("/test/mock-analysis")
async def mock_analysis_request():
    """모의 분석 요청 (테스트용)"""
    sample_request = deepstream_manager.sample_data.get("analysis_requests", [])
    if not sample_request:
        raise HTTPException(status_code=404, detail="샘플 분석 요청 데이터가 없습니다")
    
    request_data = sample_request[0]  # 첫 번째 샘플 사용
    
    analysis_request = AnalysisRequest(
        camera_id=request_data["camera_id"],
        type=AnalysisType(request_data["type"]),
        path=request_data["path"],
        name=request_data["name"],
        output_dir=request_data["output_dir"],
        files=request_data.get("files", [])
    )
    
    return await start_analysis(analysis_request)


@router.post("/test/simulate-handshake/{instance_id}")
async def simulate_handshake(instance_id: str = FastAPIPath(..., description="인스턴스 ID")):
    """핸드셰이크 시뮬레이션 (테스트용)"""
    # 샘플 데이터에서 해당 인스턴스 정보 조회
    sample_instances = deepstream_manager.sample_data.get("deepstream_instances", [])
    instance_data = None
    
    for sample in sample_instances:
        if sample["instance_id"] == instance_id:
            instance_data = sample
            break
    
    if not instance_data:
        raise HTTPException(status_code=404, detail=f"샘플 인스턴스 데이터를 찾을 수 없습니다: {instance_id}")
    
    # 인스턴스 상태 업데이트 (연결된 것처럼 시뮬레이션)
    deepstream_manager.update_instance_status(
        instance_id,
        status=InstanceStatus.IDLE,
        ws_status="connected"
    )
    
    return {
        "status": "simulated",
        "instance_id": instance_id,
        "message": "핸드셰이크가 시뮬레이션되었습니다"
    }


@router.post("/test/simulate-metrics/{instance_id}")
async def simulate_metrics_update(instance_id: str = FastAPIPath(..., description="인스턴스 ID")):
    """메트릭 업데이트 시뮬레이션 (테스트용)"""
    instance = deepstream_manager.get_instance(instance_id)
    if not instance:
        raise HTTPException(status_code=404, detail=f"인스턴스를 찾을 수 없습니다: {instance_id}")
    
    # 샘플 메트릭 데이터 찾기
    sample_metrics = deepstream_manager.sample_data.get("metrics_samples", [])
    metrics_data = None
    
    for sample in sample_metrics:
        if sample["instance_id"] == instance_id:
            metrics_data = sample
            break
    
    if not metrics_data:
        # 기본 메트릭 생성
        metrics_data = {
            "cpu_percent": 25.0,
            "ram_mb": 512.0,
            "gpu_percent": 45.0,
            "vram_mb": 1024.0
        }
    
    # 메트릭 업데이트
    deepstream_manager.update_metrics(instance_id, metrics_data)
    
    return {
        "status": "updated",
        "instance_id": instance_id,
        "metrics": metrics_data,
        "message": "메트릭이 시뮬레이션으로 업데이트되었습니다"
    }


@router.post("/test/simulate-file-processing/{instance_id}")
async def simulate_file_processing(
    instance_id: str = FastAPIPath(..., description="인스턴스 ID"),
    camera_id: int = Query(..., description="카메라 ID"),
    file_id: int = Query(..., description="파일 ID"),
    action: str = Query(..., description="액션: start, complete, error")
):
    """파일 처리 상태 시뮬레이션 (테스트용)"""
    instance = deepstream_manager.get_instance(instance_id)
    if not instance:
        raise HTTPException(status_code=404, detail=f"인스턴스를 찾을 수 없습니다: {instance_id}")
    
    if action == "start":
        success = deepstream_manager.start_file_processing(instance_id, camera_id, file_id)
        message = f"파일 처리 시작 시뮬레이션: file_{file_id}"
    elif action == "complete":
        success = deepstream_manager.complete_file_processing(instance_id, camera_id, file_id)
        message = f"파일 처리 완료 시뮬레이션: file_{file_id}"
    else:
        raise HTTPException(status_code=400, detail="지원되지 않는 액션입니다. start, complete 중 선택하세요")
    
    if not success:
        raise HTTPException(status_code=404, detail="파일 또는 카메라를 찾을 수 없습니다")
    
    return {
        "status": action,
        "instance_id": instance_id,
        "camera_id": camera_id,
        "file_id": file_id,
        "message": message
    }


@router.post("/test/reset-instance/{instance_id}")
async def reset_instance_for_test(instance_id: str = FastAPIPath(..., description="인스턴스 ID")):
    """테스트용 인스턴스 상태 리셋"""
    instance = deepstream_manager.get_instance(instance_id)
    if not instance:
        raise HTTPException(status_code=404, detail=f"인스턴스를 찾을 수 없습니다: {instance_id}")
    
    # 모든 스트림을 idle 상태로 리셋
    for stream in instance.streams.values():
        stream.status = "idle"
        stream.current_camera_id = None
        stream.camera_queue.clear()
    
    # 모든 카메라 정보 삭제
    instance.cameras.clear()
    
    # 인스턴스 상태 리셋
    instance.status = InstanceStatus.IDLE
    
    return {
        "status": "reset",
        "instance_id": instance_id,
        "message": "인스턴스 상태가 초기화되었습니다"
    }


@router.post("/test/simulate-app-ready/{instance_id}")
async def simulate_app_ready_message(instance_id: str = FastAPIPath(..., description="인스턴스 ID")):
    """app_ready 메시지 시뮬레이션 (테스트용)"""
    from services.websocket_manager import websocket_manager
    
    # 샘플 데이터에서 테스트 시나리오 가져오기
    handshake_data = deepstream_manager.sample_data.get("test_scenarios", {}).get("handshake_success", {})
    
    if not handshake_data:
        raise HTTPException(status_code=404, detail="테스트 시나리오 데이터가 없습니다")
    
    # 모의 app_ready 메시지 생성
    app_ready_message = {
        "action": "app_ready",
        "request_id": str(uuid.uuid4()),
        "instance_id": instance_id,
        "config_path": handshake_data.get("config_path", "/test/config.txt"),
        "process_id": handshake_data.get("process_id", 12345),
        "streams_count": handshake_data.get("streams_count", 3),
        "status": "ok",
        "version": "DeepStream-Yolo v7.1",
        "gpu_allocated": [0, 1],
        "start_time": datetime.now().isoformat()
    }
    
    # 모의 WebSocket 연결 생성
    class MockWebSocketConnection:
        def __init__(self):
            self.instance_id = None
            self.is_authenticated = False
    
    mock_connection = MockWebSocketConnection()
    
    try:
        # app_ready 메시지 처리 시뮬레이션
        await websocket_manager._handle_app_ready(mock_connection, app_ready_message)
        
        return {
            "status": "success",
            "message": f"app_ready 메시지 시뮬레이션 완료: {instance_id}",
            "simulated_message": app_ready_message,
            "received_process_id": app_ready_message["process_id"]
        }
    
    except Exception as e:
        return {
            "status": "error",
            "message": f"app_ready 메시지 시뮬레이션 실패: {str(e)}",
            "simulated_message": app_ready_message
        }


@router.get("/test/scenarios")
async def get_test_scenarios():
    """테스트 시나리오 목록 조회 (테스트용)"""
    scenarios = deepstream_manager.sample_data.get("test_scenarios", {})
    error_scenarios = deepstream_manager.sample_data.get("error_scenarios", {})
    
    return {
        "success_scenarios": scenarios,
        "error_scenarios": error_scenarios,
        "available_endpoints": [
            "POST /deepstream/launch - DeepStream 앱 실행",
            "GET /deepstream/processes - 모든 프로세스 목록 조회",
            "GET /deepstream/processes/{process_id} - 특정 프로세스 상태",
            "POST /deepstream/processes/{process_id}/terminate - 프로세스 종료",
            "GET /deepstream/processes/{process_id}/logs - 프로세스 로그 조회",
            "POST /deepstream/test/mock-launch - 모의 프로세스 실행 (테스트용)",
            "POST /deepstream/test/mock-analysis - 샘플 데이터로 분석 요청",
            "POST /deepstream/test/simulate-handshake/{instance_id} - 핸드셰이크 시뮬레이션",
            "POST /deepstream/test/simulate-app-ready/{instance_id} - app_ready 메시지 시뮬레이션 (PID 포함)",
            "POST /deepstream/test/simulate-metrics/{instance_id} - 메트릭 업데이트 시뮬레이션",
            "POST /deepstream/test/simulate-file-processing/{instance_id} - 파일 처리 상태 시뮬레이션",
            "POST /deepstream/test/reset-instance/{instance_id} - 인스턴스 상태 리셋",
            "GET /deepstream/test/sample-data - 전체 샘플 데이터 조회",
            "GET /deepstream/test/scenarios - 이 테스트 시나리오 목록"
        ]
    }


@router.post("/test/mock-launch", response_model=LaunchResponse)
async def mock_launch_deepstream_app():
    """모의 DeepStream 앱 실행 (테스트용)"""
    # 샘플 데이터에서 설정 정보 가져오기
    sample_instances = deepstream_manager.sample_data.get("deepstream_instances", [])
    if not sample_instances:
        raise HTTPException(status_code=404, detail="샘플 인스턴스 데이터가 없습니다")
    
    # 첫 번째 샘플 인스턴스 설정 사용
    sample = sample_instances[0]
    
    launch_request = LaunchRequest(
        config_path=sample["config_path"],
        streams_count=sample["streams_count"],
        gpu_allocated=sample["gpu_allocated"],
        docker_container="test_container"  # 테스트용 컨테이너
    )
    
    # 실제로는 Docker 명령을 실행하지 않고 모의 실행
    try:
        success, message, process_info = await process_launcher.launch_deepstream_app(
            config_path=launch_request.config_path,
            streams_count=launch_request.streams_count,
            gpu_allocated=launch_request.gpu_allocated,
            instance_id=launch_request.instance_id,
            docker_container=launch_request.docker_container,
            additional_args=launch_request.additional_args
        )
        
        if success and process_info:
            return LaunchResponse(
                success=True,
                message=f"모의 실행 성공: {message}",
                process_id=process_info.process_id,
                instance_id=process_info.instance_id,
                host_pid=process_info.host_pid,
                log_path=process_info.log_path
            )
        else:
            return LaunchResponse(
                success=False,
                message=f"모의 실행 실패: {message}"
            )
    
    except Exception as e:
        # Docker가 없는 환경에서는 에러가 발생할 수 있으므로 모의 응답
        mock_process_id = str(uuid.uuid4())
        mock_instance_id = process_launcher.generate_instance_id()
        
        return LaunchResponse(
            success=True,
            message=f"모의 실행 (Docker 없음): {str(e)}",
            process_id=mock_process_id,
            instance_id=mock_instance_id,
            host_pid=99999,
            log_path=f"/mock/logs/{mock_instance_id}.log"
        )


# WebSocket 엔드포인트
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