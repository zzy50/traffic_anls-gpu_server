import asyncio
import json
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set
from dataclasses import dataclass, field
from enum import Enum

from models.websocket_messages import (
    StreamStatus, CameraStatus, FilesStatus, ProcessingFile, QueuedFile,
    MetricsResponse, AnalysisStatusResponse, AnalysisType
)

logger = logging.getLogger(__name__)


class InstanceStatus(str, Enum):
    """DeepStream 인스턴스 상태"""
    IDLE = "idle"
    RUNNING = "running"
    ERROR = "error"
    DISCONNECTED = "disconnected"


class WSStatus(str, Enum):
    """WebSocket 연결 상태"""
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    RECONNECTING = "reconnecting"


@dataclass
class FileInfo:
    """파일 정보"""
    file_id: int
    file_path: str
    file_name: str
    output_path: str
    status: str = "pending"  # pending, processing, completed, error
    progress_pct: float = 0.0
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


@dataclass
class CameraInfo:
    """카메라 분석 정보"""
    camera_id: int
    stream_id: int
    type: AnalysisType
    path: str
    name: str
    output_dir: str
    status: str = "queued"  # queued, running, completed, interrupted, error
    files: List[FileInfo] = field(default_factory=list)
    current_file_id: Optional[int] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


@dataclass
class StreamInfo:
    """스트림 슬롯 정보"""
    stream_id: int
    status: str = "idle"  # idle, running, error
    current_camera_id: Optional[int] = None
    camera_queue: List[int] = field(default_factory=list)  # 대기 중인 camera_id들


@dataclass
class DeepStreamInstance:
    """DeepStream 인스턴스 정보"""
    instance_id: str
    config_path: str
    streams_count: int
    gpu_allocated: List[int]
    status: InstanceStatus = InstanceStatus.IDLE
    ws_status: WSStatus = WSStatus.DISCONNECTED
    launched_at: Optional[datetime] = None
    log_path: Optional[str] = None
    last_ping: Optional[datetime] = None
    
    # 내부 상태
    streams: Dict[int, StreamInfo] = field(default_factory=dict)
    cameras: Dict[int, CameraInfo] = field(default_factory=dict)
    last_metrics: Optional[Dict] = None
    last_metrics_time: Optional[datetime] = None


class DeepStreamManager:
    """DeepStream 인스턴스들을 관리하는 중앙 매니저"""
    
    def __init__(self):
        self.instances: Dict[str, DeepStreamInstance] = {}
        self.sample_data = self._load_sample_data()
        self._initialize_sample_instances()
    
    def _load_sample_data(self) -> Dict:
        """샘플 데이터 로드"""
        try:
            with open("sample_data.json", "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"샘플 데이터 로드 실패: {e}")
            return {}
    
    def _initialize_sample_instances(self):
        """샘플 데이터로 초기 인스턴스들 생성"""
        for instance_data in self.sample_data.get("deepstream_instances", []):
            instance = DeepStreamInstance(
                instance_id=instance_data["instance_id"],
                config_path=instance_data["config_path"],
                streams_count=instance_data["streams_count"],
                gpu_allocated=instance_data["gpu_allocated"],
                status=InstanceStatus(instance_data["status"]),
                ws_status=WSStatus(instance_data["ws_status"]),
                launched_at=datetime.fromisoformat(instance_data["launched_at"]),
                log_path=instance_data["log_path"]
            )
            
            # 스트림 초기화
            for i in range(instance.streams_count):
                instance.streams[i] = StreamInfo(stream_id=i)
            
            self.instances[instance.instance_id] = instance
            logger.info(f"샘플 인스턴스 생성: {instance.instance_id}")
    
    def get_instance(self, instance_id: str) -> Optional[DeepStreamInstance]:
        """인스턴스 조회"""
        return self.instances.get(instance_id)
    
    def get_all_instances(self) -> List[DeepStreamInstance]:
        """모든 인스턴스 조회"""
        return list(self.instances.values())
    
    def register_instance(self, instance_id: str, config_path: str, 
                         streams_count: int, gpu_allocated: List[int]) -> DeepStreamInstance:
        """새 인스턴스 등록"""
        instance = DeepStreamInstance(
            instance_id=instance_id,
            config_path=config_path,
            streams_count=streams_count,
            gpu_allocated=gpu_allocated,
            launched_at=datetime.now()
        )
        
        # 스트림 초기화
        for i in range(streams_count):
            instance.streams[i] = StreamInfo(stream_id=i)
        
        self.instances[instance_id] = instance
        logger.info(f"새 인스턴스 등록: {instance_id}")
        return instance
    
    def update_instance_status(self, instance_id: str, 
                              status: InstanceStatus = None,
                              ws_status: WSStatus = None):
        """인스턴스 상태 업데이트"""
        instance = self.get_instance(instance_id)
        if not instance:
            return
        
        if status:
            instance.status = status
        if ws_status:
            instance.ws_status = ws_status
        
        instance.last_ping = datetime.now()
    
    def get_available_stream(self, instance_id: str) -> Optional[int]:
        """사용 가능한 스트림 슬롯 찾기"""
        instance = self.get_instance(instance_id)
        if not instance:
            return None
        
        for stream_id, stream in instance.streams.items():
            if stream.status == "idle":
                return stream_id
        
        return None
    
    def start_analysis(self, instance_id: str, stream_id: int, camera_id: int,
                      analysis_type: AnalysisType, path: str, name: str, 
                      output_dir: str) -> bool:
        """분석 시작"""
        instance = self.get_instance(instance_id)
        if not instance:
            return False
        
        stream = instance.streams.get(stream_id)
        if not stream or stream.status != "idle":
            # 스트림이 사용 중이면 카메라를 큐에 추가
            if stream and camera_id not in stream.camera_queue:
                stream.camera_queue.append(camera_id)
            return False
        
        # 카메라 정보 생성
        camera_info = CameraInfo(
            camera_id=camera_id,
            stream_id=stream_id,
            type=analysis_type,
            path=path,
            name=name,
            output_dir=output_dir,
            status="running",
            started_at=datetime.now()
        )
        
        # 상태 업데이트
        stream.status = "running"
        stream.current_camera_id = camera_id
        instance.cameras[camera_id] = camera_info
        
        logger.info(f"분석 시작: {instance_id}, stream_{stream_id}, camera_{camera_id}")
        return True
    
    def add_files_to_camera(self, instance_id: str, camera_id: int, 
                           files_data: List[Dict]) -> bool:
        """카메라에 파일들 추가"""
        instance = self.get_instance(instance_id)
        if not instance:
            return False
        
        camera = instance.cameras.get(camera_id)
        if not camera:
            return False
        
        for file_data in files_data:
            file_info = FileInfo(
                file_id=file_data["file_id"],
                file_path=file_data["file_path"],
                file_name=file_data["file_name"],
                output_path=file_data["output_path"]
            )
            camera.files.append(file_info)
        
        logger.info(f"파일 추가: camera_{camera_id}, {len(files_data)}개 파일")
        return True
    
    def start_file_processing(self, instance_id: str, camera_id: int, 
                             file_id: int) -> bool:
        """파일 처리 시작"""
        instance = self.get_instance(instance_id)
        if not instance:
            return False
        
        camera = instance.cameras.get(camera_id)
        if not camera:
            return False
        
        for file_info in camera.files:
            if file_info.file_id == file_id:
                file_info.status = "processing"
                file_info.started_at = datetime.now()
                camera.current_file_id = file_id
                return True
        
        return False
    
    def complete_file_processing(self, instance_id: str, camera_id: int, 
                               file_id: int) -> bool:
        """파일 처리 완료"""
        instance = self.get_instance(instance_id)
        if not instance:
            return False
        
        camera = instance.cameras.get(camera_id)
        if not camera:
            return False
        
        for file_info in camera.files:
            if file_info.file_id == file_id:
                file_info.status = "completed"
                file_info.completed_at = datetime.now()
                file_info.progress_pct = 100.0
                
                if camera.current_file_id == file_id:
                    camera.current_file_id = None
                
                return True
        
        return False
    
    def complete_camera_analysis(self, instance_id: str, camera_id: int) -> bool:
        """카메라 분석 완료"""
        instance = self.get_instance(instance_id)
        if not instance:
            return False
        
        camera = instance.cameras.get(camera_id)
        if not camera:
            return False
        
        stream = instance.streams.get(camera.stream_id)
        if not stream:
            return False
        
        # 카메라 상태 업데이트
        camera.status = "completed"
        camera.completed_at = datetime.now()
        camera.current_file_id = None
        
        # 스트림 상태 업데이트
        stream.current_camera_id = None
        
        # 대기 중인 카메라가 있으면 다음 카메라 시작
        if stream.camera_queue:
            next_camera_id = stream.camera_queue.pop(0)
            # 다음 카메라 분석은 별도 로직에서 처리
            logger.info(f"다음 카메라 대기 중: camera_{next_camera_id}")
        else:
            stream.status = "idle"
        
        logger.info(f"카메라 분석 완료: camera_{camera_id}")
        return True
    
    def interrupt_analysis(self, instance_id: str, camera_id: int) -> bool:
        """분석 중단"""
        instance = self.get_instance(instance_id)
        if not instance:
            return False
        
        camera = instance.cameras.get(camera_id)
        if not camera:
            return False
        
        stream = instance.streams.get(camera.stream_id)
        if not stream:
            return False
        
        # 카메라 상태 업데이트
        camera.status = "interrupted"
        camera.completed_at = datetime.now()
        camera.current_file_id = None
        
        # 처리 중인 파일들 중단
        for file_info in camera.files:
            if file_info.status == "processing":
                file_info.status = "interrupted"
        
        # 스트림 상태 업데이트
        stream.current_camera_id = None
        stream.status = "idle"
        
        logger.info(f"분석 중단: camera_{camera_id}")
        return True
    
    def update_metrics(self, instance_id: str, metrics: Dict):
        """메트릭 업데이트"""
        instance = self.get_instance(instance_id)
        if not instance:
            return
        
        instance.last_metrics = metrics
        instance.last_metrics_time = datetime.now()
    
    def get_analysis_status(self, instance_id: str, stream_id: Optional[int] = None,
                           camera_id: Optional[int] = None) -> Optional[Dict]:
        """분석 상태 조회"""
        instance = self.get_instance(instance_id)
        if not instance:
            return None
        
        if camera_id is not None:
            # 특정 카메라 상태 조회
            camera = instance.cameras.get(camera_id)
            if not camera:
                return None
            
            return self._build_camera_status_response(camera)
        
        elif stream_id is not None:
            # 특정 스트림 상태 조회
            stream = instance.streams.get(stream_id)
            if not stream:
                return None
            
            return self._build_stream_status_response(instance, stream)
        
        else:
            # 전체 상태 조회
            return self._build_all_streams_status_response(instance)
    
    def _build_camera_status_response(self, camera: CameraInfo) -> Dict:
        """카메라 상태 응답 생성"""
        processing_files = []
        queued_files = []
        completed_count = 0
        
        for file_info in camera.files:
            if file_info.status == "processing":
                processing_files.append(ProcessingFile(
                    file_id=file_info.file_id,
                    file_name=file_info.file_name,
                    progress_pct=file_info.progress_pct
                ))
            elif file_info.status == "pending":
                queued_files.append(QueuedFile(
                    file_id=file_info.file_id,
                    file_name=file_info.file_name
                ))
            elif file_info.status == "completed":
                completed_count += 1
        
        files_status = FilesStatus(
            processing=processing_files,
            completed_count=completed_count,
            queued_count=len(queued_files),
            queued=queued_files
        )
        
        camera_status = CameraStatus(
            camera_id=camera.camera_id,
            status=camera.status,
            files=files_status
        )
        
        return {
            "stream_id": camera.stream_id,
            "camera": camera_status
        }
    
    def _build_stream_status_response(self, instance: DeepStreamInstance, 
                                    stream: StreamInfo) -> Dict:
        """스트림 상태 응답 생성"""
        cameras = []
        
        # 현재 처리 중인 카메라
        if stream.current_camera_id:
            camera = instance.cameras.get(stream.current_camera_id)
            if camera:
                camera_status = self._build_single_camera_status(camera)
                cameras.append(camera_status)
        
        # 대기 중인 카메라들
        for camera_id in stream.camera_queue:
            camera = instance.cameras.get(camera_id)
            if camera:
                camera_status = self._build_single_camera_status(camera)
                cameras.append(camera_status)
        
        stream_status = StreamStatus(
            stream_id=stream.stream_id,
            status=stream.status,
            cameras=cameras
        )
        
        return {"stream": stream_status}
    
    def _build_all_streams_status_response(self, instance: DeepStreamInstance) -> Dict:
        """전체 스트림 상태 응답 생성"""
        streams = []
        
        for stream in instance.streams.values():
            stream_data = self._build_stream_status_response(instance, stream)
            streams.append(stream_data["stream"])
        
        return {"streams": streams}
    
    def _build_single_camera_status(self, camera: CameraInfo) -> CameraStatus:
        """단일 카메라 상태 생성"""
        processing_files = []
        queued_files = []
        completed_count = 0
        
        for file_info in camera.files:
            if file_info.status == "processing":
                processing_files.append(ProcessingFile(
                    file_id=file_info.file_id,
                    file_name=file_info.file_name,
                    progress_pct=file_info.progress_pct
                ))
            elif file_info.status == "pending":
                queued_files.append(QueuedFile(
                    file_id=file_info.file_id,
                    file_name=file_info.file_name
                ))
            elif file_info.status == "completed":
                completed_count += 1
        
        files_status = FilesStatus(
            processing=processing_files,
            completed_count=completed_count,
            queued_count=len(queued_files),
            queued=queued_files
        )
        
        return CameraStatus(
            camera_id=camera.camera_id,
            status=camera.status,
            files=files_status
        )


# 싱글톤 인스턴스
deepstream_manager = DeepStreamManager()