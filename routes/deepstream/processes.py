import logging
from datetime import datetime
from typing import List

from fastapi import APIRouter, HTTPException, Query, Path as FastAPIPath

from models.deepstream import (
    LaunchRequest, LaunchResponse, ProcessListResponse, 
    ProcessStatusInfo, LogResponse
)
from services.process_launcher import process_launcher

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/processes", tags=["프로세스 관리"])


@router.post("/launch", response_model=LaunchResponse)
async def launch_deepstream_app(request: LaunchRequest):
    """DeepStream 앱 실행"""
    success, message, process_info = await process_launcher.launch_deepstream_app(
        instance_id=request.instance_id,
        streams_count=request.streams_count,
        log_dir=request.log_dir,
    )
    
    if success and process_info:
        return LaunchResponse(
            success=True,
            message=message,
            process_id=process_info.process_id,
            instance_id=process_info.instance_id,
            host_pid=process_info.host_pid,
            log_dir=process_info.log_dir
        )
    else:
        # HTTP 500 대신 성공=False로 응답
        return LaunchResponse(
            success=False,
            message=message
        )


@router.get("/", response_model=ProcessListResponse)
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
            config_path=process.log_dir,
            host_pid=process.host_pid,
            container_pid=process.container_pid,
            status=process.status,
            launched_at=process.launched_at.isoformat(),
            log_dir=process.log_dir,
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


@router.get("/{process_id}", response_model=ProcessStatusInfo)
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
        config_path=process.log_dir,
        docker_container=process.docker_container,
        host_pid=process.host_pid,
        container_pid=process.container_pid,
        status=process.status,
        launched_at=process.launched_at.isoformat(),
        log_dir=process.log_path,
        command=process.command,
        error_message=process.error_message
    )


@router.post("/{process_id}/terminate")
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


@router.get("/{process_id}/logs", response_model=LogResponse)
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


@router.get("/by-instance/{instance_id}", response_model=ProcessStatusInfo)
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
        config_path=process.log_dir,
        docker_container=process.docker_container,
        host_pid=process.host_pid,
        container_pid=process.container_pid,
        status=process.status,
        launched_at=process.launched_at.isoformat(),
        log_dir=process.log_path,
        command=process.command,
        error_message=process.error_message
    )


@router.post("/cleanup")
async def cleanup_stopped_processes():
    """중지된 프로세스들 정리"""
    await process_launcher.cleanup_stopped_processes()
    
    return {
        "success": True,
        "message": "중지된 프로세스들이 정리되었습니다",
        "timestamp": datetime.now().isoformat()
    } 