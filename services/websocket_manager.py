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
    QueryAnalysisStatusMessage, AnalysisStatusResponse, StatusType, FileItem, EOSItem,
    InitFile
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
        self._is_shutting_down: bool = False  # graceful shutdown 상태 플래그
        self._reconnection_stats: Dict[str, Dict] = {}  # 재연결 통계
        self._connection_history: List[Dict] = []  # 연결 이력
    
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
        # shutdown 중에는 새 연결 거부
        if self._is_shutting_down:
            # Close code 1013 (Try Again Later) - 일시적 서버 불가
            await websocket.close(code=1013, reason="Server temporarily unavailable")
            raise Exception("Server is shutting down, so new connections are rejected")
        
        await websocket.accept()
        connection_id = str(uuid.uuid4())
        connection = WebSocketConnection(websocket)
        self.connections[connection_id] = connection
        
        logger.info(f"새 WebSocket 연결: {connection_id} (총 연결 수: {len(self.connections)})")
        return connection_id
    
    def disconnect(self, connection_id: str):
        """WebSocket 연결 해제"""
        connection = self.connections.get(connection_id)
        if connection:
            # 연결 이력 기록
            disconnect_record = {
                "connection_id": connection_id,
                "instance_id": connection.instance_id,
                "disconnected_at": datetime.now(),
                "connection_duration": (datetime.now() - connection.connected_at).total_seconds() if connection.connected_at else 0,
                "was_authenticated": connection.is_authenticated
            }
            self._connection_history.append(disconnect_record)
            
            # 이력 크기 제한 (최근 100개만 유지)
            if len(self._connection_history) > 100:
                self._connection_history = self._connection_history[-100:]
            
            if connection.instance_id:
                # DeepStream 인스턴스 상태 업데이트
                deepstream_manager.update_instance_status(
                    connection.instance_id, 
                    ws_status=WSStatus.DISCONNECTED
                )
                logger.info(f"인스턴스 연결 해제: {connection.instance_id} (지속시간: {disconnect_record['connection_duration']:.1f}초)")
        
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
        """앱 준비 완료 메시지 처리 - 재연결 지원 포함"""
        try:
            message = AppReadyMessage(**message_data)
            connection.instance_id = message.instance_id
            connection.is_authenticated = True
            
            # 재연결 정보 확인
            is_reconnection = message_data.get("reconnection", False)
            last_close_code = message_data.get("last_close_code", 0)
            
            if is_reconnection:
                logger.info(f"클라이언트 {message.instance_id} 재연결 (마지막 종료 코드: {last_close_code})")
                await self._handle_client_reconnection(connection, message, last_close_code)
            else:
                logger.info(f"새 클라이언트 {message.instance_id} 연결")
            
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
                process_info.ws_connected = True  # WebSocket 연결 상태 업데이트
                logger.info(f"DeepStream-app으로부터 PID 수신: {message.instance_id} -> {message.process_id}")
            else:
                logger.warning(f"인스턴스에 해당하는 프로세스 정보를 찾을 수 없습니다: {message.instance_id}")
            
            # 검증 및 응답
            is_instance_id_valid = await self._verify_instance_id(message)
            is_streams_count_valid = await self._verify_streams_count(message)
            
            # 재연결인 경우 추가 정보 포함
            if is_reconnection:
                response = {
                    "type": "reconnection_ack",
                    "request_id": message.request_id,
                    "instance_id": message.instance_id,
                    "status": "ok" if (is_instance_id_valid and is_streams_count_valid) else "error",
                    "config_verified": is_instance_id_valid,
                    "streams_count_verified": is_streams_count_valid,
                    "session_restored": True if last_close_code in [1001, 1013] else False,
                    "server_status": "running"
                }
                await connection.websocket.send_text(json.dumps(response))
            else:
                # 기존 ExecuteAck 응답
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
            
            logger.info(f"앱 준비 완료 처리: {message.instance_id} (재연결: {is_reconnection})")
        
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
        """앱 종료 응답 처리 - 클라이언트 형식 확인"""
        try:
            # 클라이언트가 전송하는 정확한 형식 확인:
            # {
            #   "type": "app_terminated",
            #   "request_id": "original_request_id", 
            #   "status": "OK",  // 대문자 주의!
            #   "message": "Application terminated gracefully"
            # }
            
            request_id = message_data.get("request_id")
            status = message_data.get("status")
            termination_message = message_data.get("message", "")
            
            if status == "OK":  # 대문자 확인
                logger.info(f"DeepStream 클라이언트 {connection.instance_id} gracefully terminated")
                logger.info(f"Termination message: {termination_message}")
                
                # 클라이언트 리소스 정리
                await self._cleanup_client_resources(connection.instance_id)
                
                # 인스턴스 상태 업데이트
                deepstream_manager.update_instance_status(
                    connection.instance_id,
                    status=InstanceStatus.DISCONNECTED,
                    ws_status=WSStatus.DISCONNECTED
                )
                
                # 연결을 정상 종료 코드(1000)로 종료
                try:
                    await connection.websocket.close(code=1000, reason="Client terminated gracefully")
                except Exception as close_error:
                    logger.debug(f"WebSocket 연결 종료 중 예상된 오류: {close_error}")
                
            else:
                logger.warning(f"클라이언트 종료 실패: request_id={request_id}, status={status}, message={termination_message}")
                
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
                                 path: str, name: str, output_dir: str,
                                 init_file: Optional[InitFile] = None) -> bool:
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
                output_dir=output_dir,
                init_file=init_file
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
            files = []
            for file_data in files_data:
                files.append(FileItem(
                    file_id=file_data["file_id"],
                    file_path=file_data["file_path"],
                    file_name=file_data["file_name"],
                    output_path=file_data["output_path"]
                ))
            
            # EOS 마커 추가
            files.append(EOSItem())
            
            message = PushFileMessage(
                request_id=str(uuid.uuid4()),
                stream_id=stream_id,
                camera_id=camera_id,
                files_count=len(files_data),  # EOS 제외한 파일 개수
                files=files
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
    
    def is_shutting_down(self) -> bool:
        """현재 shutdown 진행 상태 확인"""
        return self._is_shutting_down
    
    def get_connection_stats(self) -> Dict[str, Any]:
        """연결 통계 정보 조회"""
        total_connections = len(self.connections)
        authenticated_connections = sum(
            1 for conn in self.connections.values() 
            if conn.is_authenticated and conn.instance_id
        )
        
        # 재연결 통계
        total_reconnections = sum(
            stats.get("reconnect_count", 0) 
            for stats in self._reconnection_stats.values()
        )
        
        # 평균 연결 지속 시간 계산
        if self._connection_history:
            avg_duration = sum(
                record["connection_duration"] 
                for record in self._connection_history[-20:]  # 최근 20개
            ) / min(len(self._connection_history), 20)
        else:
            avg_duration = 0
        
        return {
            "total_connections": total_connections,
            "authenticated_connections": authenticated_connections,
            "unauthenticated_connections": total_connections - authenticated_connections,
            "is_shutting_down": self._is_shutting_down,
            "reconnection_stats": {
                "total_reconnections": total_reconnections,
                "unique_clients_reconnected": len(self._reconnection_stats),
                "avg_connection_duration_seconds": round(avg_duration, 2)
            },
            "pending_requests": len(self.pending_requests)
        }
    
    def get_detailed_stats(self) -> Dict[str, Any]:
        """상세 통계 정보 조회 (디버깅/모니터링용)"""
        stats = self.get_connection_stats()
        
        # 연결별 상세 정보
        connections_detail = []
        for conn_id, conn in self.connections.items():
            detail = {
                "connection_id": conn_id,
                "instance_id": conn.instance_id,
                "is_authenticated": conn.is_authenticated,
                "connected_at": conn.connected_at.isoformat() if conn.connected_at else None,
                "last_ping": conn.last_ping.isoformat() if conn.last_ping else None,
                "connection_age_seconds": (datetime.now() - conn.connected_at).total_seconds() if conn.connected_at else 0
            }
            connections_detail.append(detail)
        
        # 재연결 상세 정보
        reconnection_detail = {
            instance_id: {
                "reconnect_count": info["reconnect_count"],
                "last_reconnect": info["last_reconnect"].isoformat(),
                "last_close_code": info["last_close_code"]
            }
            for instance_id, info in self._reconnection_stats.items()
        }
        
        stats.update({
            "connections_detail": connections_detail,
            "reconnection_detail": reconnection_detail,
            "recent_disconnections": [
                {
                    "instance_id": record["instance_id"],
                    "disconnected_at": record["disconnected_at"].isoformat(),
                    "duration_seconds": record["connection_duration"],
                    "was_authenticated": record["was_authenticated"]
                }
                for record in self._connection_history[-10:]  # 최근 10개
            ]
        })
        
        return stats
    
    async def graceful_shutdown(self, timeout: float = 30.0) -> None:
        """모든 WebSocket 연결을 graceful하게 종료"""
        # 중복 shutdown 방지
        if self._is_shutting_down:
            logger.warning("이미 graceful shutdown이 진행 중입니다")
            return
        
        self._is_shutting_down = True
        
        try:
            if not self.connections:
                logger.info("종료할 WebSocket 연결이 없습니다")
                return
            
            logger.info(f"WebSocket graceful shutdown 시작 (연결 수: {len(self.connections)}, 타임아웃: {timeout}초)")
            
            # 1단계: 모든 클라이언트에게 서버 종료 알림
            shutdown_tasks = []
            for connection_id, connection in self.connections.items():
                try:
                    # 인증된 DeepStream 인스턴스에게는 종료 메시지 전송
                    if connection.instance_id and connection.is_authenticated:
                        shutdown_task = self._send_shutdown_notification(connection)
                        shutdown_tasks.append(shutdown_task)
                    else:
                        # 일반 WebSocket 연결에게는 종료 코드와 함께 연결 종료
                        shutdown_task = self._close_connection_gracefully(connection_id, connection)
                        shutdown_tasks.append(shutdown_task)
                except Exception as e:
                    logger.error(f"연결 {connection_id} 종료 준비 실패: {e}")
            
            # 2단계: 모든 종료 작업을 병렬로 실행 (타임아웃 적용)
            initial_count = len(self.connections)
            successfully_closed = 0
            failed_closures = 0
            
            shutdown_start_time = datetime.now()
            
            if shutdown_tasks:
                try:
                    results = await asyncio.wait_for(
                        asyncio.gather(*shutdown_tasks, return_exceptions=True),
                        timeout=timeout
                    )
                    
                    # 결과 분석
                    for result in results:
                        if isinstance(result, Exception):
                            failed_closures += 1
                            logger.debug(f"Shutdown task 실패: {result}")
                        else:
                            successfully_closed += 1
                    
                    shutdown_duration = (datetime.now() - shutdown_start_time).total_seconds()
                    logger.info(f"Graceful shutdown 1차 완료 - 성공: {successfully_closed}, 실패: {failed_closures}, 소요시간: {shutdown_duration:.2f}초")
                    
                except asyncio.TimeoutError:
                    shutdown_duration = (datetime.now() - shutdown_start_time).total_seconds()
                    logger.warning(f"WebSocket graceful shutdown 타임아웃 ({timeout}초, 실제 소요: {shutdown_duration:.2f}초)")
                except Exception as e:
                    logger.error(f"WebSocket graceful shutdown 중 오류: {e}")
            
            # 2.5단계: 잠시 대기 (클라이언트 정리 시간 확보)
            if self.connections:
                logger.info("클라이언트 정리 시간 확보를 위해 2초 대기...")
                await asyncio.sleep(2)
            
            # 3단계: 강제로 남은 연결들 정리
            remaining_connections = list(self.connections.keys())
            if remaining_connections:
                logger.warning(f"강제 종료할 연결들: {len(remaining_connections)}개")
                
                # 강제 종료도 병렬로 처리
                force_close_tasks = []
                for connection_id in remaining_connections:
                    connection = self.connections.get(connection_id)
                    if connection:
                        task = self._force_close_connection(connection_id, connection)
                        force_close_tasks.append(task)
                
                if force_close_tasks:
                    try:
                        await asyncio.wait_for(
                            asyncio.gather(*force_close_tasks, return_exceptions=True),
                            timeout=5.0  # 강제 종료는 5초 제한
                        )
                    except asyncio.TimeoutError:
                        logger.error("강제 종료 타임아웃")
            
            final_count = len(self.connections)
            total_shutdown_duration = (datetime.now() - shutdown_start_time).total_seconds()
            logger.info(f"Shutdown 통계 - 시작: {initial_count}개, 종료: {final_count}개, 총 소요시간: {total_shutdown_duration:.2f}초")
            
            logger.info("WebSocket graceful shutdown 완료")
        finally:
            self._is_shutting_down = False
    
    async def _send_shutdown_notification(self, connection: WebSocketConnection) -> None:
        """인증된 DeepStream 인스턴스에게 서버 종료 알림"""
        try:
            # TerminateAppMessage 전송하여 DeepStream 앱 종료 요청
            request_id = str(uuid.uuid4())
            message = TerminateAppMessage(
                request_id=request_id
            )
            await connection.send_message(message)
            logger.info(f"인스턴스 {connection.instance_id}에게 종료 메시지 전송 (request_id: {request_id})")
            
            # 대기 중인 요청에 등록
            self.pending_requests[request_id] = {
                "instance_id": connection.instance_id,
                "type": "terminate_app",
                "sent_at": datetime.now()
            }
            
            # 응답 대기 (최대 5초)
            try:
                await asyncio.wait_for(
                    self._wait_for_termination_ack(connection, request_id),
                    timeout=5.0
                )
                logger.info(f"인스턴스 {connection.instance_id} graceful 종료 완료")
            except asyncio.TimeoutError:
                logger.warning(f"인스턴스 {connection.instance_id} 종료 응답 타임아웃 (5초)")
            
        except Exception as e:
            logger.error(f"인스턴스 {connection.instance_id} 종료 알림 실패: {e}")
        finally:
            # 대기 중인 요청 정리
            self.pending_requests.pop(request_id, None)
            # 최종적으로 WebSocket 연결 종료 (Close code 1001)
            await self._close_websocket_connection(connection)
    
    async def _close_connection_gracefully(self, connection_id: str, connection: WebSocketConnection) -> None:
        """일반 WebSocket 연결을 gracefully 종료"""
        try:
            # 서버 종료로 인한 graceful shutdown: Close code 1001 (Going Away)
            await connection.websocket.close(code=1001, reason="Server shutting down gracefully")
            logger.info(f"WebSocket 연결 {connection_id} gracefully 종료 (코드: 1001)")
        except Exception as e:
            logger.error(f"WebSocket 연결 {connection_id} 종료 실패: {e}")
        finally:
            self.disconnect(connection_id)
    
    async def _wait_for_termination_ack(self, connection: WebSocketConnection, request_id: str) -> None:
        """종료 응답 대기 - request_id 검증 포함"""
        try:
            while True:
                message_text = await connection.receive_message()
                message_data = json.loads(message_text)
                
                if (message_data.get("type") == MessageType.APP_TERMINATED and 
                    message_data.get("request_id") == request_id):
                    
                    status = message_data.get("status")
                    if status == "OK":
                        logger.info(f"인스턴스 {connection.instance_id} 종료 확인 (request_id: {request_id})")
                    else:
                        logger.warning(f"인스턴스 {connection.instance_id} 종료 실패: {status}")
                    break
                else:
                    # 다른 메시지는 일반 처리로 전달
                    await self._process_message(connection, message_text)
                    
        except (WebSocketDisconnect, Exception):
            # 연결이 종료되거나 오류 발생 시 정상적으로 처리
            logger.debug(f"인스턴스 {connection.instance_id} 종료 대기 중 연결 종료")
    
    async def _close_websocket_connection(self, connection: WebSocketConnection) -> None:
        """WebSocket 연결 종료"""
        try:
            if connection.websocket.client_state.name != "DISCONNECTED":
                await connection.websocket.close(code=1001, reason="Server shutting down")
        except Exception as e:
            logger.debug(f"WebSocket 연결 종료 중 예상된 오류: {e}")
    
    async def _cleanup_client_resources(self, instance_id: str) -> None:
        """클라이언트 리소스 정리"""
        try:
            logger.info(f"클라이언트 {instance_id} 리소스 정리 시작")
            
            # 1. 진행 중인 분석 작업 정리
            from services.deepstream_manager import deepstream_manager
            try:
                deepstream_manager.cleanup_instance_resources(instance_id)
            except Exception as e:
                logger.warning(f"DeepStream 매니저 리소스 정리 실패: {e}")
            
            # 2. 대기 중인 요청 정리
            pending_to_remove = []
            for req_id, req_data in self.pending_requests.items():
                if req_data.get("instance_id") == instance_id:
                    pending_to_remove.append(req_id)
            
            for req_id in pending_to_remove:
                self.pending_requests.pop(req_id, None)
                logger.debug(f"대기 중인 요청 제거: {req_id}")
            
            # 3. 프로세스 매니저에 알림
            from services.process_launcher import process_launcher
            try:
                process_info = process_launcher.get_process_by_instance_id(instance_id)
                if process_info:
                    process_info.ws_connected = False
                    logger.debug(f"프로세스 {instance_id} WebSocket 연결 상태 업데이트")
            except Exception as e:
                logger.warning(f"프로세스 매니저 상태 업데이트 실패: {e}")
            
            logger.info(f"클라이언트 {instance_id} 리소스 정리 완료")
            
        except Exception as e:
            logger.error(f"클라이언트 리소스 정리 중 오류: {e}")
    
    async def _handle_client_reconnection(self, connection: WebSocketConnection, message: Any, last_close_code: int) -> None:
        """재연결 클라이언트 처리"""
        try:
            instance_id = message.instance_id
            
            # 이전 세션 정보 복구 (필요한 경우)
            if last_close_code in [1001, 1013]:  # 서버 종료로 인한 재연결
                logger.info(f"서버 종료로 인한 재연결 - 세션 복구 시도: {instance_id}")
                await self._restore_client_session(instance_id)
            else:
                logger.info(f"일반 재연결: {instance_id} (코드: {last_close_code})")
            
            # 재연결 통계 업데이트
            if hasattr(self, '_reconnection_stats'):
                self._reconnection_stats[instance_id] = {
                    "last_reconnect": datetime.now(),
                    "last_close_code": last_close_code,
                    "reconnect_count": self._reconnection_stats.get(instance_id, {}).get("reconnect_count", 0) + 1
                }
            else:
                self._reconnection_stats = {
                    instance_id: {
                        "last_reconnect": datetime.now(),
                        "last_close_code": last_close_code,
                        "reconnect_count": 1
                    }
                }
                
        except Exception as e:
            logger.error(f"재연결 처리 중 오류: {e}")
    
    async def _restore_client_session(self, instance_id: str) -> bool:
        """클라이언트 세션 복구"""
        try:
            logger.info(f"클라이언트 {instance_id} 세션 복구 시작")
            
            # 1. DeepStream 매니저에서 이전 상태 확인
            from services.deepstream_manager import deepstream_manager
            instance = deepstream_manager.get_instance(instance_id)
            
            if instance:
                # 인스턴스가 존재하면 상태만 업데이트
                deepstream_manager.update_instance_status(
                    instance_id,
                    status=InstanceStatus.IDLE,
                    ws_status=WSStatus.CONNECTED
                )
                logger.info(f"인스턴스 {instance_id} 상태 복구 완료")
                return True
            else:
                logger.warning(f"복구할 인스턴스 {instance_id}를 찾을 수 없음")
                return False
                
        except Exception as e:
            logger.error(f"세션 복구 중 오류: {e}")
            return False


# 싱글톤 인스턴스
websocket_manager = WebSocketManager()