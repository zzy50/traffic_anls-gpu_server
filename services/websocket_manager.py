import asyncio
import json
import logging
import uuid
from datetime import datetime
from typing import Dict, List, Optional, Callable, Any
from fastapi import WebSocket, WebSocketDisconnect

from models.websocket_messages import (
    MessageType, IncomingMessage, OutgoingMessage,
    AppReadyMessage, ExecuteAckMessage, StartAnalysisMessage, AnalysisStartedMessage,
    PushFileMessage, PushAckMessage, ProcessingStartedMessage, FileDoneMessage,
    AnalysisCompleteMessage, InterruptAnalysisMessage, AnalysisInterruptedMessage,
    TerminateAppMessage, AppTerminatedMessage, QueryMetricsMessage, MetricsResponse,
    QueryAnalysisStatusMessage, AnalysisStatusResponse, StatusType, FileItem, EOSItem
)
from services.deepstream_manager import deepstream_manager, InstanceStatus, WSStatus

logger = logging.getLogger(__name__)


class WebSocketConnection:
    """개별 WebSocket 연결 정보"""
    
    def __init__(self, websocket: WebSocket, instance_id: str = None):
        self.websocket = websocket
        self.instance_id = instance_id
        self.connected_at = datetime.now()
        self.last_ping = datetime.now()
        self.is_authenticated = False
    
    async def send_message(self, message: OutgoingMessage):
        """메시지 전송"""
        try:
            message_json = message.model_dump_json()
            await self.websocket.send_text(message_json)
            logger.debug(f"메시지 전송: {self.instance_id} -> {type(message).__name__}")
        except Exception as e:
            logger.error(f"메시지 전송 실패: {self.instance_id}, {e}")
            raise
    
    async def receive_message(self) -> Optional[str]:
        """메시지 수신"""
        try:
            return await self.websocket.receive_text()
        except WebSocketDisconnect:
            logger.info(f"WebSocket 연결 종료: {self.instance_id}")
            raise
        except Exception as e:
            logger.error(f"메시지 수신 실패: {self.instance_id}, {e}")
            raise


class WebSocketManager:
    """WebSocket 연결들을 관리하는 중앙 매니저"""
    
    def __init__(self):
        self.connections: Dict[str, WebSocketConnection] = {}
        self.message_handlers = self._setup_message_handlers()
        self.pending_requests: Dict[str, Dict] = {}  # request_id -> response callback
    
    def _setup_message_handlers(self) -> Dict[str, Callable]:
        """메시지 핸들러 설정"""
        return {
            MessageType.APP_READY: self._handle_app_ready,
            MessageType.ANALYSIS_STARTED: self._handle_analysis_started,
            MessageType.PUSH_ACK: self._handle_push_ack,
            MessageType.PROCESSING_STARTED: self._handle_processing_started,
            MessageType.FILE_DONE: self._handle_file_done,
            MessageType.ANALYSIS_COMPLETE: self._handle_analysis_complete,
            MessageType.ANALYSIS_INTERRUPTED: self._handle_analysis_interrupted,
            MessageType.APP_TERMINATED: self._handle_app_terminated,
            MessageType.METRICS_RESPONSE: self._handle_metrics_response,
            MessageType.ANALYSIS_STATUS: self._handle_analysis_status,
        }
    
    async def connect(self, websocket: WebSocket) -> str:
        """새로운 WebSocket 연결 처리"""
        await websocket.accept()
        connection_id = str(uuid.uuid4())
        connection = WebSocketConnection(websocket)
        self.connections[connection_id] = connection
        
        logger.info(f"새 WebSocket 연결: {connection_id}")
        return connection_id
    
    def disconnect(self, connection_id: str):
        """WebSocket 연결 해제"""
        connection = self.connections.get(connection_id)
        if connection and connection.instance_id:
            # DeepStream 인스턴스 상태 업데이트
            deepstream_manager.update_instance_status(
                connection.instance_id, 
                ws_status=WSStatus.DISCONNECTED
            )
            logger.info(f"인스턴스 연결 해제: {connection.instance_id}")
        
        self.connections.pop(connection_id, None)
        logger.info(f"WebSocket 연결 해제: {connection_id}")
    
    async def handle_connection(self, connection_id: str):
        """WebSocket 연결 처리 루프"""
        connection = self.connections.get(connection_id)
        if not connection:
            return
        
        try:
            while True:
                message_text = await connection.receive_message()
                await self._process_message(connection, message_text)
        
        except WebSocketDisconnect:
            logger.info(f"클라이언트 연결 종료: {connection_id}")
        except Exception as e:
            logger.error(f"연결 처리 오류: {connection_id}, {e}")
        finally:
            self.disconnect(connection_id)
    
    async def _process_message(self, connection: WebSocketConnection, message_text: str):
        """수신된 메시지 처리"""
        try:
            message_data = json.loads(message_text)
            message_type = message_data.get("type")
            
            if not message_type:
                logger.warning(f"메시지 타입 없음: {message_text[:100]}")
                return
            
            handler = self.message_handlers.get(message_type)
            if handler:
                await handler(connection, message_data)
            else:
                logger.warning(f"알 수 없는 메시지 타입: {message_type}")
        
        except json.JSONDecodeError as e:
            logger.error(f"JSON 파싱 오류: {e}, 메시지: {message_text[:100]}")
        except Exception as e:
            logger.error(f"메시지 처리 오류: {e}")
    
    async def _handle_app_ready(self, connection: WebSocketConnection, message_data: Dict):
        """앱 준비 완료 메시지 처리"""
        try:
            message = AppReadyMessage(**message_data)
            connection.instance_id = message.instance_id
            connection.is_authenticated = True
            
            # DeepStream 매니저에 인스턴스 등록/업데이트
            instance = deepstream_manager.get_instance(message.instance_id)
            if not instance:
                deepstream_manager.register_instance(
                    message.instance_id,
                    message.config_path,
                    message.streams_count
                )
            
            deepstream_manager.update_instance_status(
                message.instance_id,
                status=InstanceStatus.IDLE,
                ws_status=WSStatus.CONNECTED
            )
            
            # ProcessLauncher에서 해당 인스턴스의 프로세스 정보 업데이트
            from services.process_launcher import process_launcher
            process_info = process_launcher.get_process_by_instance_id(message.instance_id)
            if process_info:
                process_info.container_pid = message.process_id
                logger.info(f"DeepStream-app으로부터 PID 수신: {message.instance_id} -> {message.process_id}")
            else:
                logger.warning(f"인스턴스에 해당하는 프로세스 정보를 찾을 수 없습니다: {message.instance_id}")
            
            # 검증 및 응답
            is_instance_id_valid = await self._verify_instance_id(message)
            is_streams_count_valid = await self._verify_streams_count(message)
            
            response = ExecuteAckMessage(
                request_id=message.request_id,
                instance_id=message.instance_id,
                config_verified=is_instance_id_valid,
                streams_count_verified=is_streams_count_valid,
                status=StatusType.OK if (is_instance_id_valid and is_streams_count_valid) else StatusType.ERROR
            )
            
            if not is_instance_id_valid:
                response.error_code = "CONFIG_MISMATCH"
                response.error_message = "Config verification failed"
            elif not is_streams_count_valid:
                response.error_code = "STREAMS_COUNT_MISMATCH"
                response.error_message = "Streams count verification failed"
            
            await connection.send_message(response)
            logger.info(f"앱 준비 완료 처리: {message.instance_id}")
        
        except Exception as e:
            logger.error(f"앱 준비 메시지 처리 오류: {e}")
    
    async def _verify_instance_id(self, message: AppReadyMessage) -> bool:
        """인스턴스 설정 검증"""
        # 기본적인 인스턴스 ID 검증
        return message.instance_id is not None and len(message.instance_id) > 0
    
    async def _verify_streams_count(self, message: AppReadyMessage) -> bool:
        """streams_count 검증"""
        try:
            # ProcessLauncher에서 해당 인스턴스의 프로세스 정보 조회
            from services.process_launcher import process_launcher
            process_info = process_launcher.get_process_by_instance_id(message.instance_id)
            
            if not process_info:
                logger.warning(f"인스턴스에 해당하는 프로세스 정보를 찾을 수 없습니다: {message.instance_id}")
                return False
            
            # launch 시 전달된 streams_count가 없으면 기본 검증 수행
            if process_info.streams_count is None:
                logger.info(f"Launch 시 streams_count가 없어 기본 검증 수행: {message.instance_id}")
                return message.streams_count > 0
            
            # launch 시 전달된 streams_count와 deepstream-app이 보고한 값 비교
            if process_info.streams_count != message.streams_count:
                logger.error(f"Streams count 불일치 - 예상: {process_info.streams_count}, 실제: {message.streams_count}")
                return False
            
            logger.info(f"Streams count 검증 성공: {message.instance_id} -> {message.streams_count}")
            return True
            
        except Exception as e:
            logger.error(f"Streams count 검증 중 오류: {e}")
            return False
    

    
    async def _handle_analysis_started(self, connection: WebSocketConnection, message_data: Dict):
        """분석 시작 응답 처리"""
        try:
            message = AnalysisStartedMessage(**message_data)
            
            if message.status == StatusType.OK:
                # 성공적으로 분석 시작됨
                logger.info(f"분석 시작 확인: stream_{message.stream_id}, camera_{message.camera_id}")
            else:
                # 분석 시작 실패
                logger.warning(f"분석 시작 실패: {message.error_reason}")
        
        except Exception as e:
            logger.error(f"분석 시작 응답 처리 오류: {e}")
    
    async def _handle_push_ack(self, connection: WebSocketConnection, message_data: Dict):
        """파일 푸시 응답 처리"""
        try:
            message = PushAckMessage(**message_data)
            
            if message.status == StatusType.OK:
                logger.info(f"파일 푸시 확인: stream_{message.stream_id}, camera_{message.camera_id}")
            else:
                logger.warning(f"파일 푸시 실패: {message.error_reason}")
        
        except Exception as e:
            logger.error(f"파일 푸시 응답 처리 오류: {e}")
    
    async def _handle_processing_started(self, connection: WebSocketConnection, message_data: Dict):
        """파일 처리 시작 메시지 처리"""
        try:
            message = ProcessingStartedMessage(**message_data)
            
            # DeepStream 매니저에 파일 처리 시작 알림
            deepstream_manager.start_file_processing(
                connection.instance_id,
                message.camera_id,
                message.file_id
            )
            
            logger.info(f"파일 처리 시작: {message.current_file}")
        
        except Exception as e:
            logger.error(f"파일 처리 시작 메시지 처리 오류: {e}")
    
    async def _handle_file_done(self, connection: WebSocketConnection, message_data: Dict):
        """파일 처리 완료 메시지 처리"""
        try:
            message = FileDoneMessage(**message_data)
            
            # DeepStream 매니저에 파일 처리 완료 알림
            deepstream_manager.complete_file_processing(
                connection.instance_id,
                message.camera_id,
                message.file_id
            )
            
            logger.info(f"파일 처리 완료: {message.processed_file}")
        
        except Exception as e:
            logger.error(f"파일 처리 완료 메시지 처리 오류: {e}")
    
    async def _handle_analysis_complete(self, connection: WebSocketConnection, message_data: Dict):
        """분석 완료 메시지 처리"""
        try:
            message = AnalysisCompleteMessage(**message_data)
            
            # DeepStream 매니저에 분석 완료 알림
            deepstream_manager.complete_camera_analysis(
                connection.instance_id,
                message.camera_id
            )
            
            logger.info(f"분석 완료: camera_{message.camera_id}, 처리된 파일 수: {message.processed_count}")
        
        except Exception as e:
            logger.error(f"분석 완료 메시지 처리 오류: {e}")
    
    async def _handle_analysis_interrupted(self, connection: WebSocketConnection, message_data: Dict):
        """분석 중단 응답 처리"""
        try:
            message = AnalysisInterruptedMessage(**message_data)
            
            if message.status == StatusType.OK:
                # 성공적으로 중단됨
                deepstream_manager.interrupt_analysis(
                    connection.instance_id,
                    message.camera_id
                )
                logger.info(f"분석 중단 확인: camera_{message.camera_id}")
            else:
                logger.warning(f"분석 중단 실패: {message.error_reason}")
        
        except Exception as e:
            logger.error(f"분석 중단 응답 처리 오류: {e}")
    
    async def _handle_app_terminated(self, connection: WebSocketConnection, message_data: Dict):
        """앱 종료 응답 처리"""
        try:
            message = AppTerminatedMessage(**message_data)
            
            # 인스턴스 상태 업데이트
            deepstream_manager.update_instance_status(
                connection.instance_id,
                status=InstanceStatus.DISCONNECTED,
                ws_status=WSStatus.DISCONNECTED
            )
            
            logger.info(f"앱 종료 확인: {connection.instance_id}")
        
        except Exception as e:
            logger.error(f"앱 종료 응답 처리 오류: {e}")
    
    async def _handle_metrics_response(self, connection: WebSocketConnection, message_data: Dict):
        """메트릭 응답 처리"""
        try:
            message = MetricsResponse(**message_data)
            
            # DeepStream 매니저에 메트릭 업데이트
            metrics = {
                "cpu_percent": message.cpu_percent,
                "ram_mb": message.ram_mb,
                "gpu_percent": message.gpu_percent,
                "vram_mb": message.vram_mb
            }
            deepstream_manager.update_metrics(connection.instance_id, metrics)
            
            logger.debug(f"메트릭 업데이트: {connection.instance_id}")
        
        except Exception as e:
            logger.error(f"메트릭 응답 처리 오류: {e}")
    
    async def _handle_analysis_status(self, connection: WebSocketConnection, message_data: Dict):
        """분석 상태 응답 처리"""
        try:
            message = AnalysisStatusResponse(**message_data)
            logger.debug(f"분석 상태 응답: {connection.instance_id}")
        
        except Exception as e:
            logger.error(f"분석 상태 응답 처리 오류: {e}")
    
    # 외부에서 호출할 수 있는 메시지 전송 메서드들
    async def send_start_analysis(self, instance_id: str, stream_id: int, 
                                 camera_id: int, analysis_type: str,
                                 path: str, name: str, output_dir: str) -> bool:
        """분석 시작 메시지 전송"""
        connection = self._get_connection_by_instance(instance_id)
        if not connection:
            return False
        
        try:
            message = StartAnalysisMessage(
                request_id=str(uuid.uuid4()),
                stream_id=stream_id,
                camera_id=camera_id,
                camera_type=analysis_type,
                path=path,
                name=name,
                output_dir=output_dir
            )
            await connection.send_message(message)
            return True
        
        except Exception as e:
            logger.error(f"분석 시작 메시지 전송 오류: {e}")
            return False
    
    async def send_push_file(self, instance_id: str, stream_id: int,
                            camera_id: int, files_data: List[Dict]) -> bool:
        """파일 푸시 메시지 전송"""
        connection = self._get_connection_by_instance(instance_id)
        if not connection:
            return False
        
        try:
            items = []
            for file_data in files_data:
                items.append(FileItem(
                    file_id=file_data["file_id"],
                    file_path=file_data["file_path"],
                    file_name=file_data["file_name"],
                    output_path=file_data["output_path"]
                ))
            
            # EOS 마커 추가
            items.append(EOSItem())
            
            message = PushFileMessage(
                request_id=str(uuid.uuid4()),
                stream_id=stream_id,
                camera_id=camera_id,
                items_count=len(files_data),  # EOS 제외한 파일 개수
                items=items
            )
            await connection.send_message(message)
            return True
        
        except Exception as e:
            logger.error(f"파일 푸시 메시지 전송 오류: {e}")
            return False
    
    async def send_interrupt_analysis(self, instance_id: str, stream_id: int,
                                    camera_id: int, reason: str = "user_cancelled") -> bool:
        """분석 중단 메시지 전송"""
        connection = self._get_connection_by_instance(instance_id)
        if not connection:
            return False
        
        try:
            message = InterruptAnalysisMessage(
                request_id=str(uuid.uuid4()),
                stream_id=stream_id,
                camera_id=camera_id,
                reason=reason
            )
            await connection.send_message(message)
            return True
        
        except Exception as e:
            logger.error(f"분석 중단 메시지 전송 오류: {e}")
            return False
    
    async def send_terminate_app(self, instance_id: str) -> bool:
        """앱 종료 메시지 전송"""
        connection = self._get_connection_by_instance(instance_id)
        if not connection:
            return False
        
        try:
            message = TerminateAppMessage(
                request_id=str(uuid.uuid4())
            )
            await connection.send_message(message)
            return True
        
        except Exception as e:
            logger.error(f"앱 종료 메시지 전송 오류: {e}")
            return False
    
    async def send_query_metrics(self, instance_id: str) -> bool:
        """메트릭 조회 메시지 전송"""
        connection = self._get_connection_by_instance(instance_id)
        if not connection:
            return False
        
        try:
            message = QueryMetricsMessage(
                request_id=str(uuid.uuid4())
            )
            await connection.send_message(message)
            return True
        
        except Exception as e:
            logger.error(f"메트릭 조회 메시지 전송 오류: {e}")
            return False
    
    async def send_query_analysis_status(self, instance_id: str, 
                                       stream_id: Optional[int] = None,
                                       camera_id: Optional[int] = None) -> bool:
        """분석 상태 조회 메시지 전송"""
        connection = self._get_connection_by_instance(instance_id)
        if not connection:
            return False
        
        try:
            message = QueryAnalysisStatusMessage(
                request_id=str(uuid.uuid4()),
                stream_id=stream_id,
                camera_id=camera_id
            )
            await connection.send_message(message)
            return True
        
        except Exception as e:
            logger.error(f"분석 상태 조회 메시지 전송 오류: {e}")
            return False
    
    def _get_connection_by_instance(self, instance_id: str) -> Optional[WebSocketConnection]:
        """인스턴스 ID로 연결 찾기"""
        for connection in self.connections.values():
            if connection.instance_id == instance_id and connection.is_authenticated:
                return connection
        return None
    
    def get_connected_instances(self) -> List[str]:
        """연결된 인스턴스 목록 조회"""
        return [
            conn.instance_id for conn in self.connections.values()
            if conn.instance_id and conn.is_authenticated
        ]


# 싱글톤 인스턴스
websocket_manager = WebSocketManager()