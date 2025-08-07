import asyncio
import json
import logging
import os
import subprocess
import time
import uuid
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

from services.deepstream_manager import deepstream_manager, InstanceStatus, WSStatus

logger = logging.getLogger(__name__)


@dataclass
class ConfigPaths:
    """설정 파일 경로들을 관리하는 데이터클래스"""
    log_dir_in_container: str
    main_config_file: str
    logging_config_file: str
    websocket_config_file: str
    
    @classmethod
    def from_log_dir(cls, log_dir: str, instance_id: str) -> "ConfigPaths":
        """log_dir을 기준으로 모든 경로 생성"""
        log_dir_in_container = cls._convert_to_container_path(log_dir)
        
        return cls(
            log_dir_in_container=log_dir_in_container,
            main_config_file=f"{log_dir_in_container}/ds_config_{instance_id}.txt",
            logging_config_file=f"{log_dir_in_container}/logging_config.txt",
            websocket_config_file=f"{log_dir_in_container}/websocket_config.txt"
        )
    
    @staticmethod
    def _convert_to_container_path(host_path: str) -> str:
        """호스트 경로를 컨테이너 경로로 변환"""
        return host_path.replace(
            "/mnt/storage/admin_storage/deepstream_vmnt/", 
            "/opt/nvidia/deepstream/deepstream/cityeyelab/vmnt/"
        )


@dataclass
class ProcessInfo:
    """실행된 프로세스 정보"""
    process_id: str  # 내부 관리용 UUID
    instance_id: str  # APP_ID
    log_dir: str
    streams_count: Optional[int] = None  # launch 시 전달된 스트림 개수
    host_pid: Optional[int] = None  # 호스트의 subprocess PID
    container_pid: Optional[int] = None  # 컨테이너 내부 PID
    status: str = "launching"  # launching, running, stopped, error
    launched_at: datetime = field(default_factory=datetime.now)
    command: Optional[str] = None
    error_message: Optional[str] = None


class ProcessLauncher:
    """DeepStream 프로세스 실행 및 관리"""
    
    def __init__(self):
        self.processes: Dict[str, ProcessInfo] = {}
        self.default_container = "deepstream_container"
    
    def _get_config_template_paths(self) -> Dict[str, Path]:
        """템플릿 설정 파일들의 경로를 반환"""
        return {
            "ds_config": Path("ds_configs/ds_config.txt"),
            "primary_gie": Path("ds_configs/config_infer_primary_yoloV8.txt"),
            "tracker": Path("ds_configs/config_tracker_NvSORT_custom.yml"),
            "labelfile": Path("ds_configs/info_cls-7_bike.txt"),
            "logging": Path("ds_configs/logging_config.txt"),
            "websocket": Path("ds_configs/websocket_config.txt")
        }
    
    def generate_instance_id(self, prefix: str = "stream") -> str:
        """고유한 인스턴스 ID 생성"""
        timestamp = datetime.now().strftime("%y%m%d_%H%M%S")
        unique_suffix = str(uuid.uuid4())[:8]
        return f"{prefix}_{timestamp}_{unique_suffix}"
    
    def check_container_running(self, container_name: str) -> bool:
        """Docker 컨테이너 실행 여부 확인"""
        try:
            check_cmd = ["docker", "inspect", "-f", "{{.State.Running}}", container_name]
            result = subprocess.run(
                check_cmd, 
                capture_output=True, 
                text=True, 
                timeout=10
            )
            
            if result.returncode == 0:
                is_running = result.stdout.strip().lower() == "true"
                if is_running:
                    logger.debug(f"컨테이너 실행 상태 확인: {container_name} - 실행 중")
                else:
                    logger.warning(f"컨테이너가 실행 중이 아닙니다: {container_name}")
                return is_running
            else:
                logger.error(f"컨테이너 상태 확인 실패: {container_name} - {result.stderr.strip()}")
                return False
                
        except subprocess.TimeoutExpired:
            logger.error(f"컨테이너 상태 확인 시간 초과: {container_name}")
            return False
        except Exception as e:
            logger.error(f"컨테이너 상태 확인 중 오류 발생: {container_name} - {str(e)}")
            return False

    
    async def launch_deepstream_app(
        self,
        log_dir: str,
        streams_count: Optional[int] = None,
        instance_id: Optional[str] = None,
    ) -> Tuple[bool, str, Optional[ProcessInfo]]:
        """
        DeepStream 앱 실행
        
        Args:
            log_dir: 로그 디렉토리 경로
            (/mnt/storage/admin_storage/deepstream_vmnt/DeepStream-Yolo/logs)
            streams_count: 스트림 개수 (설정에서 자동 추출 가능)
            instance_id: 인스턴스 ID (없으면 자동 생성)
        
        Returns:
            (성공여부, 메시지, 프로세스정보)
        """
        try:
            # 파라미터 기본값 설정
            if not instance_id:
                instance_id = self.generate_instance_id()
            
            docker_container = "infer_traffic"
            app_path_in_container = "/opt/nvidia/deepstream/deepstream/cityeyelab/vmnt/DeepStream-Yolo/custom_app_7.1/dist/deepstream-app"
            config_path_dict = self._get_config_template_paths()


            # 컨테이너 실행 여부 확인
            if not self.check_container_running(docker_container):
                error_msg = f"Docker 컨테이너가 실행 중이 아닙니다: {docker_container}. 컨테이너를 먼저 실행해주세요."
                logger.error(error_msg)
                return False, error_msg, None

            # 프로세스 정보 생성
            process_id = str(uuid.uuid4())
            process_info = ProcessInfo(
                process_id=process_id,
                instance_id=instance_id,
                log_dir=log_dir,
                streams_count=streams_count
            )

            # streams_count가 없으면 기본값 1로 설정
            if streams_count and streams_count <= 0:
                streams_count = 1

            # 설정 파일 생성 및 경로 정보 가져오기
            config_paths = self.setup_config(log_dir, streams_count, instance_id, config_path_dict)
            
            # DeepStream 실행 명령 구성
            deepstream_cmd = [app_path_in_container, "-c", config_paths.main_config_file]
            
            # Docker exec 명령 구성
            docker_cmd = [
                "docker", "exec", "-d",  # -d는 detached 모드
                "-e", f"APP_ID={instance_id}",
                "-e", f"DS_MAIN_CONFIG_FILE={config_paths.main_config_file}",
                "-e", f"DS_WS_CONFIG_FILE={config_paths.websocket_config_file}",
                "-e", f"DS_LOG_CONFIG_FILE={config_paths.logging_config_file}",
                "-e", f"DS_LOG_BASE_DIR={config_paths.log_dir_in_container}",
                docker_container
            ] + deepstream_cmd
            
            process_info.command = ' '.join(docker_cmd)
            
            # 프로세스 실행
            logger.info(f"DeepStream 앱 실행 시작: {instance_id}")
            logger.debug(f"실행 명령: {process_info.command}")
            
            proc = subprocess.Popen(
                docker_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            
            process_info.host_pid = proc.pid
            process_info.status = "running"
            
            # 프로세스 등록
            self.processes[process_id] = process_info
            
            # DeepStream 매니저에 인스턴스 등록
            if streams_count:
                deepstream_manager.register_instance(
                    instance_id, log_dir, streams_count
                )
            
            logger.info(f"DeepStream 앱 실행 성공: {instance_id} (Host PID: {proc.pid})")
            
            return True, f"DeepStream 앱이 성공적으로 실행되었습니다: {instance_id}", process_info
        
        except Exception as e:
            error_msg = f"DeepStream 앱 실행 실패: {str(e)}"
            logger.error(error_msg)
            
            if 'process_info' in locals():
                process_info.status = "error"
                process_info.error_message = error_msg
                self.processes[process_info.process_id] = process_info
            
            return False, error_msg, None

    def setup_config(self, log_dir: str, streams_count: int, instance_id: str, config_path_dict: Dict[str, Path]) -> ConfigPaths:
        """
        template.txt를 기반으로 새로운 config 파일을 생성하고 ConfigPaths 객체 반환
        
        Args:
            log_dir: 로그 디렉토리 경로 (호스트)
            streams_count: 스트림 개수
            instance_id: 인스턴스 ID
            config_path_dict: 템플릿 설정 파일들의 경로
            
        Returns:
            ConfigPaths: 생성된 설정 파일들의 경로 정보
        """
        try:
            # 필요한 설정 파일들을 log_dir로 복사
            shutil.copy(config_path_dict["primary_gie"], log_dir)
            shutil.copy(config_path_dict["tracker"], log_dir)
            shutil.copy(config_path_dict["labelfile"], log_dir)
            shutil.copy(config_path_dict["logging"], log_dir)
            shutil.copy(config_path_dict["websocket"], log_dir)

            # template 파일 읽기
            ds_template_path = config_path_dict["ds_config"]
            if not ds_template_path.exists():
                raise FileNotFoundError(f"Template 파일을 찾을 수 없습니다: {ds_template_path}")
            
            with open(ds_template_path, 'r', encoding='utf-8') as f:
                ds_config_content = f.read()
    
            # ConfigPaths 객체 생성 (모든 경로 계산)
            config_paths = ConfigPaths.from_log_dir(log_dir, instance_id)

            # 메인 config 파일의 호스트 경로 생성
            ds_config_filename = f"ds_config_{instance_id}.txt"
            ds_config_host_path = Path(log_dir) / ds_config_filename

            # template에서 [application] 섹션의 log-dir 수정
            lines = ds_config_content.split('\n')
            modified_lines = []
            
            for line in lines:
                # if line.strip().startswith('log-dir='):
                #     modified_lines.append(f'log-dir={config_paths.log_dir_in_container}')
                # else:
                #     modified_lines.append(line)
                modified_lines.append(line)
            
            # [source0] 섹션을 찾아서 streams_count만큼 복사
            source0_section = []
            in_source0_section = False
            
            for line in lines:
                if line.strip() == '[source0]':
                    in_source0_section = True
                    source0_section.append(line)
                elif in_source0_section and line.strip().startswith('['):
                    # 다른 섹션이 시작되면 source0 섹션 끝
                    break
                elif in_source0_section:
                    source0_section.append(line)
            
            # [source0]을 [source1], [source2], ... 로 복사
            additional_sources = []
            for i in range(1, streams_count):
                source_section = []
                for line in source0_section:
                    if line.strip() == '[source0]':
                        source_section.append(f'[source{i}]')
                    else:
                        source_section.append(line)
                additional_sources.extend(source_section)
                additional_sources.append('')  # 섹션 간 빈 줄 추가
            
            # 최종 config 내용 생성
            final_content = '\n'.join(modified_lines)
            if additional_sources:
                final_content += '\n\n' + '\n'.join(additional_sources)
            
            # config 파일 저장
            with open(ds_config_host_path, 'w', encoding='utf-8') as f:
                f.write(final_content)
            
            logger.info(f"Config 파일 생성 완료: {ds_config_host_path} (streams: {streams_count})")
            return config_paths
            
        except Exception as e:
            error_msg = f"Config 파일 생성 실패: {str(e)}"
            logger.error(error_msg)
            raise Exception(error_msg)

    def get_process_info(self, process_id: str) -> Optional[ProcessInfo]:
        """프로세스 정보 조회"""
        return self.processes.get(process_id)
    
    def get_process_by_instance_id(self, instance_id: str) -> Optional[ProcessInfo]:
        """인스턴스 ID로 프로세스 조회"""
        for process_info in self.processes.values():
            if process_info.instance_id == instance_id:
                return process_info
        return None
    
    def get_all_processes(self) -> List[ProcessInfo]:
        """모든 프로세스 목록 조회"""
        return list(self.processes.values())
    
    async def terminate_process(self, process_id: str) -> Tuple[bool, str]:
        """프로세스 종료"""
        process_info = self.get_process_info(process_id)
        if not process_info:
            return False, f"프로세스를 찾을 수 없습니다: {process_id}"
        
        # 컨테이너 실행 여부 확인
        if not self.check_container_running(process_info.docker_container):
            logger.warning(f"컨테이너가 실행 중이 아니므로 프로세스가 이미 종료된 것으로 간주합니다: {process_info.instance_id}")
            process_info.status = "stopped"
            return True, f"컨테이너가 실행 중이 아니므로 프로세스가 이미 종료된 것으로 처리되었습니다: {process_info.instance_id}"
        
        try:
            # 컨테이너 내부 프로세스 종료
            if process_info.container_pid:
                kill_cmd = [
                    "docker", "exec", process_info.docker_container,
                    "kill", "-TERM", str(process_info.container_pid)
                ]
                subprocess.run(kill_cmd, capture_output=True, timeout=10)
            
            # APP_ID로 프로세스 강제 종료
            kill_by_app_id_cmd = [
                "docker", "exec", process_info.docker_container,
                "pkill", "-f", f"APP_ID={process_info.instance_id}"
            ]
            subprocess.run(kill_by_app_id_cmd, capture_output=True, timeout=10)
            
            process_info.status = "stopped"
            
            # DeepStream 매니저에서 인스턴스 상태 업데이트
            deepstream_manager.update_instance_status(
                process_info.instance_id,
                status=InstanceStatus.DISCONNECTED,
                ws_status=WSStatus.DISCONNECTED
            )
            
            logger.info(f"프로세스 종료 완료: {process_info.instance_id}")
            return True, f"프로세스가 성공적으로 종료되었습니다: {process_info.instance_id}"
        
        except Exception as e:
            error_msg = f"프로세스 종료 실패: {str(e)}"
            logger.error(error_msg)
            process_info.status = "error"
            process_info.error_message = error_msg
            return False, error_msg
    
    async def check_process_status(self, process_id: str) -> Tuple[bool, str]:
        """프로세스 상태 확인"""
        process_info = self.get_process_info(process_id)
        if not process_info:
            return False, f"프로세스를 찾을 수 없습니다: {process_id}"
        
        # 컨테이너 실행 여부 확인
        if not self.check_container_running(process_info.docker_container):
            logger.warning(f"컨테이너가 실행 중이 아니므로 프로세스 상태를 확인할 수 없습니다: {process_info.instance_id}")
            process_info.status = "stopped"
            return False, f"컨테이너가 실행 중이 아닙니다: {process_info.docker_container}"
        
        try:
            # 컨테이너 내부에서 프로세스 상태 확인
            check_cmd = [
                "docker", "exec", process_info.docker_container,
                "pgrep", "-f", f"APP_ID={process_info.instance_id}"
            ]
            
            result = subprocess.run(
                check_cmd, 
                capture_output=True, 
                text=True, 
                timeout=5
            )
            
            if result.returncode == 0 and result.stdout.strip():
                process_info.status = "running"
                return True, "프로세스가 실행 중입니다"
            else:
                if process_info.status == "running":
                    process_info.status = "stopped"
                return False, "프로세스가 실행되지 않고 있습니다"
        
        except Exception as e:
            error_msg = f"프로세스 상태 확인 실패: {str(e)}"
            logger.error(error_msg)
            return False, error_msg
    
    async def cleanup_stopped_processes(self):
        """중지된 프로세스들 정리"""
        to_remove = []
        
        for process_id, process_info in self.processes.items():
            is_running, _ = await self.check_process_status(process_id)
            if not is_running and process_info.status in ["stopped", "error"]:
                # 일정 시간 후 목록에서 제거 (예: 1시간)
                if (datetime.now() - process_info.launched_at).seconds > 3600:
                    to_remove.append(process_id)
        
        for process_id in to_remove:
            del self.processes[process_id]
            logger.info(f"중지된 프로세스 정리: {process_id}")
    
    def get_process_logs(self, process_id: str, lines: int = 100) -> Tuple[bool, str, Optional[str]]:
        """프로세스 로그 조회 - DeepStream-app에서 로그를 자체 관리하므로 현재 비활성화"""
        process_info = self.get_process_info(process_id)
        if not process_info:
            return False, f"프로세스를 찾을 수 없습니다: {process_id}", None
        
        # DeepStream-app에서 로그를 자체 관리하므로 FastAPI에서는 로그 조회 불가
        return False, "로그는 DeepStream-app에서 자체 관리됩니다. 컨테이너 내부에서 직접 조회하세요.", None


# 싱글톤 인스턴스
process_launcher = ProcessLauncher()