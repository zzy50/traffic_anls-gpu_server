from typing import List, Optional, Union, Literal
from pydantic import BaseModel, Field
from datetime import datetime
from enum import Enum


class MessageType(str, Enum):
    """WebSocket 메시지 타입"""
    # FastAPI -> DeepStream 메시지 타입들
    APP_READY = "app_ready"
    START_ANALYSIS = "start_analysis"
    PUSH_FILE = "push_file"
    INTERRUPT_ANALYSIS = "interrupt_analysis"
    TERMINATE_APP = "terminate_app"
    QUERY_METRICS = "query_metrics"
    QUERY_ANALYSIS_STATUS = "query_analysis_status"
    
    # DeepStream -> FastAPI 메시지 타입들
    EXECUTE_ACK = "execute_ack"
    ANALYSIS_STARTED = "analysis_started"
    PUSH_ACK = "push_ack"
    PROCESSING_STARTED = "processing_started"
    FILE_DONE = "file_done"
    ANALYSIS_COMPLETE = "analysis_complete"
    ANALYSIS_INTERRUPTED = "analysis_interrupted"
    APP_TERMINATED = "app_terminated"
    METRICS_RESPONSE = "metrics_response"
    ANALYSIS_STATUS = "analysis_status"


class AnalysisType(str, Enum):
    """분석 타입"""
    VIDEOSTREAM = "videostream"
    FILESET = "fileset"
    FILE = "file"


class StatusType(str, Enum):
    """상태 타입"""
    OK = "ok"
    ERROR = "error"
    RUNNING = "running"
    IDLE = "idle"
    QUEUED = "queued"
    DONE = "done"


# DeepStream -> FastAPI 메시지들
class AppReadyMessage(BaseModel):
    """앱 준비 완료 메시지 (DeepStream -> FastAPI)"""
    type: Literal[MessageType.APP_READY] = MessageType.APP_READY
    request_id: str
    instance_id: str
    config_path: str
    process_id: int  # DeepStream-app에서 전송하는 프로세스 ID
    streams_count: int
    status: StatusType
    version: str = "DeepStream-Yolo v7.1"
    start_time: str = Field(default_factory=lambda: datetime.now().isoformat())


class AnalysisStartedMessage(BaseModel):
    """분석 시작 응답 메시지 (DeepStream -> FastAPI)"""
    type: Literal[MessageType.ANALYSIS_STARTED] = MessageType.ANALYSIS_STARTED
    request_id: str
    stream_id: int
    camera_id: int
    status: StatusType
    message: Optional[str] = None
    error_reason: Optional[str] = None


class ProcessingStartedMessage(BaseModel):
    """파일 처리 시작 메시지 (DeepStream -> FastAPI)"""
    type: Literal[MessageType.PROCESSING_STARTED] = MessageType.PROCESSING_STARTED
    request_id: str
    stream_id: int
    camera_id: int
    file_id: int
    current_file: str


class FileDoneMessage(BaseModel):
    """파일 처리 완료 메시지 (DeepStream -> FastAPI)"""
    type: Literal[MessageType.FILE_DONE] = MessageType.FILE_DONE
    request_id: str
    stream_id: int
    camera_id: int
    file_id: int
    processed_file: str


class AnalysisCompleteMessage(BaseModel):
    """분석 완료 메시지 (DeepStream -> FastAPI)"""
    type: Literal[MessageType.ANALYSIS_COMPLETE] = MessageType.ANALYSIS_COMPLETE
    request_id: str
    stream_id: int
    camera_id: int
    status: StatusType
    processed_count: int
    message: str


class AnalysisInterruptedMessage(BaseModel):
    """분석 중단 응답 메시지 (DeepStream -> FastAPI)"""
    type: Literal[MessageType.ANALYSIS_INTERRUPTED] = MessageType.ANALYSIS_INTERRUPTED
    request_id: str
    stream_id: int
    camera_id: int
    status: StatusType
    message: Optional[str] = None
    error_reason: Optional[str] = None


class AppTerminatedMessage(BaseModel):
    """앱 종료 응답 메시지 (DeepStream -> FastAPI)"""
    type: Literal[MessageType.APP_TERMINATED] = MessageType.APP_TERMINATED
    request_id: str
    status: StatusType
    message: str


class PushAckMessage(BaseModel):
    """파일 푸시 응답 메시지 (DeepStream -> FastAPI)"""
    type: Literal[MessageType.PUSH_ACK] = MessageType.PUSH_ACK
    request_id: str
    stream_id: int
    camera_id: int
    status: StatusType
    error_reason: Optional[str] = None


# FastAPI -> DeepStream 메시지들
class ExecuteAckMessage(BaseModel):
    """실행 확인 메시지 (FastAPI -> DeepStream)"""
    type: Literal[MessageType.EXECUTE_ACK] = MessageType.EXECUTE_ACK
    request_id: str
    instance_id: str
    config_verified: bool
    streams_count_verified: bool
    status: StatusType
    expected_config: Optional[str] = None
    received_config: Optional[str] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())


class StartAnalysisMessage(BaseModel):
    """분석 시작 메시지 (FastAPI -> DeepStream)"""
    type: Literal[MessageType.START_ANALYSIS] = MessageType.START_ANALYSIS
    request_id: str
    stream_id: int
    camera_id: int
    camera_type: AnalysisType
    path: str
    name: str
    output_dir: str


class FileItem(BaseModel):
    """파일 아이템"""
    file_type: Literal["file"] = "file"
    file_id: int
    file_path: str
    file_name: str
    output_path: str


class EOSItem(BaseModel):
    """EOS 아이템"""
    file_type: Literal["eos"] = "eos"


class PushFileMessage(BaseModel):
    """파일 푸시 메시지 (FastAPI -> DeepStream)"""
    type: Literal[MessageType.PUSH_FILE] = MessageType.PUSH_FILE
    request_id: str
    stream_id: int
    camera_id: int
    files_count: int
    files: List[Union[FileItem, EOSItem]]


class InterruptAnalysisMessage(BaseModel):
    """분석 중단 메시지 (FastAPI -> DeepStream)"""
    type: Literal[MessageType.INTERRUPT_ANALYSIS] = MessageType.INTERRUPT_ANALYSIS
    request_id: str
    stream_id: int
    camera_id: int
    reason: str = "user_cancelled"


class TerminateAppMessage(BaseModel):
    """앱 종료 메시지 (FastAPI -> DeepStream)"""
    type: Literal[MessageType.TERMINATE_APP] = MessageType.TERMINATE_APP
    request_id: str


class QueryMetricsMessage(BaseModel):
    """메트릭 조회 메시지 (FastAPI -> DeepStream)"""
    type: Literal[MessageType.QUERY_METRICS] = MessageType.QUERY_METRICS
    request_id: str


class QueryAnalysisStatusMessage(BaseModel):
    """분석 상태 조회 메시지 (FastAPI -> DeepStream)"""
    type: Literal[MessageType.QUERY_ANALYSIS_STATUS] = MessageType.QUERY_ANALYSIS_STATUS
    request_id: str
    stream_id: Optional[int] = None
    camera_id: Optional[int] = None


# 메트릭 및 상태 응답 모델들
class MetricsResponse(BaseModel):
    """메트릭 응답 (DeepStream -> FastAPI)"""
    type: Literal[MessageType.METRICS_RESPONSE] = MessageType.METRICS_RESPONSE
    request_id: str
    cpu_percent: float
    ram_mb: float
    gpu_percent: float
    vram_mb: float
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())


class ProcessingFile(BaseModel):
    """처리 중인 파일 정보"""
    file_id: int
    file_name: str
    progress_pct: float


class QueuedFile(BaseModel):
    """대기 중인 파일 정보"""
    file_id: int
    file_name: str


class FilesStatus(BaseModel):
    """파일 상태 정보"""
    processing: List[ProcessingFile] = []
    completed_count: int = 0
    queued_count: int = 0
    queued: List[QueuedFile] = []


class CameraStatus(BaseModel):
    """카메라 상태 정보"""
    camera_id: int
    status: Literal["running", "queued"]
    files: FilesStatus


class StreamStatus(BaseModel):
    """스트림 상태 정보"""
    stream_id: int
    status: Literal["running", "idle", "error"]
    cameras: List[CameraStatus] = []


class AnalysisStatusResponse(BaseModel):
    """분석 상태 응답 (DeepStream -> FastAPI)"""
    type: Literal[MessageType.ANALYSIS_STATUS] = MessageType.ANALYSIS_STATUS
    request_id: str
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())
    streams: Optional[List[StreamStatus]] = None  # 전체 조회시
    stream: Optional[StreamStatus] = None  # 특정 스트림 조회시
    stream_id: Optional[int] = None  # 특정 카메라 조회시
    camera: Optional[CameraStatus] = None  # 특정 카메라 조회시


# 유니온 타입으로 모든 메시지 정의
IncomingMessage = Union[
    AppReadyMessage,
    AnalysisStartedMessage,
    ProcessingStartedMessage,
    FileDoneMessage,
    AnalysisCompleteMessage,
    AnalysisInterruptedMessage,
    AppTerminatedMessage,
    PushAckMessage,
    MetricsResponse,
    AnalysisStatusResponse
]

OutgoingMessage = Union[
    ExecuteAckMessage,
    StartAnalysisMessage,
    PushFileMessage,
    InterruptAnalysisMessage,
    TerminateAppMessage,
    QueryMetricsMessage,
    QueryAnalysisStatusMessage
]