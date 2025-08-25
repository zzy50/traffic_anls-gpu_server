from typing import List, Optional, Dict, Any
from pydantic import BaseModel

from models.websocket_messages import AnalysisType, InitFile


# 요청 모델들
class AnalysisRequest(BaseModel):
    """분석 요청 모델"""
    camera_id: int
    camera_type: AnalysisType
    path: str
    name: str
    output_dir: str
    files: Optional[List[Dict]] = None
    init_file: Optional[InitFile] = None


class LaunchRequest(BaseModel):
    """DeepStream 앱 실행 요청 모델"""
    instance_id: Optional[str] = None
    streams_count: Optional[int] = None
    log_dir: str


# 응답 모델들
class StartAnalysisResponse(BaseModel):
    """분석 시작 응답 모델"""
    request_id: str
    instance_id: str
    stream_id: int
    camera_id: int
    status: str
    message: Optional[str] = None


class LaunchResponse(BaseModel):
    """DeepStream 앱 실행 응답 모델"""
    success: bool
    message: str
    process_id: Optional[str] = None
    instance_id: Optional[str] = None
    host_pid: Optional[int] = None
    log_dir: Optional[str] = None


class LogResponse(BaseModel):
    """로그 조회 응답 모델"""
    success: bool
    message: str
    log_content: Optional[str] = None
    lines_requested: int
    process_id: str


class ProcessListResponse(BaseModel):
    """프로세스 목록 응답 모델"""
    total_count: int
    running_count: int
    stopped_count: int
    error_count: int
    processes: List["ProcessStatusInfo"]


# 정보 모델들
class InstanceInfo(BaseModel):
    """인스턴스 정보 모델"""
    instance_id: str
    config_path: str
    streams_count: int
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


class ProcessStatusInfo(BaseModel):
    """프로세스 상태 정보 모델"""
    process_id: str
    instance_id: str
    config_path: str
    host_pid: Optional[int] = None
    container_pid: Optional[int] = None
    status: str
    launched_at: str
    log_dir: Optional[str] = None
    command: Optional[str] = None
    error_message: Optional[str] = None


# Forward reference 해결
ProcessListResponse.model_rebuild() 