# DeepStream 프로세스 실행 엔드포인트 상세 분석

<br>

# 1. 개요

## 1.1. 엔드포인트 정보

**경로:** `POST /deepstream/processes/launch`

**목적:** FastAPI에서 Docker 컨테이너 내부의 DeepStream 애플리케이션을 실행하고 관리하는 기능을 제공합니다. 이 엔드포인트는 새로운 DeepStream 인스턴스를 생성하고, 해당 인스턴스가 WebSocket을 통해 FastAPI와 통신할 수 있도록 설정합니다.

**주요 특징:**
- Docker 컨테이너 내부에서 `deepstream-app` 실행
- 고유한 인스턴스 ID를 통한 프로세스 식별
- WebSocket 기반 양방향 통신을 위한 환경변수 설정
- 실시간 프로세스 상태 모니터링

<br>

# 2. 요청-응답 데이터 명세

## 2.1. 요청 데이터 (LaunchRequest)

```json
{
  "config_path": "string",           // 필수: DeepStream 설정 파일 경로
  "streams_count": 3,                // 선택: 스트림 개수 (기본값: null)
  "instance_id": "stream_241231_12345678", // 선택: 인스턴스 ID (기본값: 자동생성)
  "docker_container": "deepstream_container", // 선택: 컨테이너 이름 (기본값: "deepstream_container")
  "additional_args": ["--arg1", "--arg2"]      // 선택: 추가 deepstream-app 인자
}
```

### 필드 상세 설명:

- **`config_path`** (string, 필수): DeepStream 설정 파일의 절대 경로. 컨테이너 내부에서 접근 가능한 경로여야 함
- **`streams_count`** (int, 선택): 처리할 스트림의 개수. 설정 파일에서 자동 추출 가능하므로 선택사항
- **`instance_id`** (string, 선택): 인스턴스를 식별하는 고유 ID. 미제공 시 `stream_{timestamp}_{uuid8자리}` 형식으로 자동 생성
- **`docker_container`** (string, 선택): 실행할 Docker 컨테이너 이름. 기본값은 "deepstream_container"
- **`additional_args`** (List[string], 선택): deepstream-app에 전달할 추가 명령줄 인자

<br>

## 2.2. 응답 데이터 (LaunchResponse)

### 성공 응답:
```json
{
  "success": true,
  "message": "DeepStream 앱이 성공적으로 실행되었습니다: stream_241231_12345678",
  "process_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "instance_id": "stream_241231_12345678",
  "host_pid": 12345,
  "log_path": null
}
```

### 실패 응답:
```json
{
  "success": false,
  "message": "DeepStream 앱 실행 실패: Docker container not found",
  "process_id": null,
  "instance_id": null,
  "host_pid": null,
  "log_path": null
}
```

### 필드 상세 설명:

- **`success`** (boolean): 실행 성공 여부
- **`message`** (string): 실행 결과 메시지
- **`process_id`** (string, 선택): 내부 관리용 프로세스 UUID (성공 시에만 제공)
- **`instance_id`** (string, 선택): 인스턴스 식별자 (성공 시에만 제공)  
- **`host_pid`** (int, 선택): 호스트에서의 subprocess PID (성공 시에만 제공)
- **`log_path`** (string, 선택): 로그 파일 경로 (현재 구현에서는 null)

<br>

# 3. 실행 흐름 상세 분석

## 3.1. 전체 실행 흐름 다이어그램

```
[Client] → [FastAPI Router] → [ProcessLauncher] → [Docker Container] → [DeepStream App]
    ↓              ↓                  ↓                    ↓              ↓
Request         Validation        Process            Container         App Start
Reception       & Routing         Creation           Execution         & WS Connect
```

<br>

## 3.2. 단계별 실행 과정

### 단계 1: 요청 수신 및 라우팅
**위치:** `routes/deepstream/processes.py` → `launch_deepstream_app()`

```python
@router.post("/launch", response_model=LaunchResponse)
async def launch_deepstream_app(request: LaunchRequest):
    success, message, process_info = await process_launcher.launch_deepstream_app(
        config_path=request.config_path,
        streams_count=request.streams_count,
        instance_id=request.instance_id,
        docker_container=request.docker_container,
        additional_args=request.additional_args
    )
```

**수행 작업:**
- HTTP POST 요청을 받아 `LaunchRequest` 모델로 검증
- 파라미터를 `ProcessLauncher` 서비스로 전달
- 결과에 따라 `LaunchResponse` 반환

<br>

### 단계 2: 파라미터 처리 및 기본값 설정
**위치:** `services/process_launcher.py` → `ProcessLauncher.launch_deepstream_app()`

```python
# 파라미터 기본값 설정
if not instance_id:
    instance_id = self.generate_instance_id()  # stream_{timestamp}_{uuid8자리}

if not docker_container:
    docker_container = self.default_container  # "deepstream_container"

if not additional_args:
    additional_args = []

# 컨테이너 실행 여부 확인
if not self.check_container_running(docker_container):
    error_msg = f"Docker 컨테이너가 실행 중이 아닙니다: {docker_container}. 컨테이너를 먼저 실행해주세요."
    logger.error(error_msg)
    return False, error_msg, None
```

**수행 작업:**
- `instance_id` 미제공 시 자동 생성: `stream_YYMMDD_HHMMSS_{8자리UUID}`
- `docker_container` 기본값 설정
- `additional_args` 빈 리스트로 초기화
- **컨테이너 실행 상태 확인**: `docker inspect` 명령으로 컨테이너가 실행 중인지 확인
- 컨테이너가 실행 중이 아닐 경우 오류 로그 기록 및 실행 중단

<br>

### 단계 3: 프로세스 정보 객체 생성
**위치:** `services/process_launcher.py`

```python
# 프로세스 정보 생성
process_id = str(uuid.uuid4())  # 내부 관리용 UUID
process_info = ProcessInfo(
    process_id=process_id,
    instance_id=instance_id,
    config_path=config_path,
    docker_container=docker_container,
    streams_count=streams_count,
    status="launching",
    launched_at=datetime.now()
)
```

**생성되는 ProcessInfo 객체:**
- `process_id`: 내부 관리용 UUID (예: "a1b2c3d4-e5f6-7890-abcd-ef1234567890")
- `instance_id`: 애플리케이션 식별자 (예: "stream_241231_123456_abcd1234")
- `config_path`: 설정 파일 경로
- `docker_container`: 컨테이너 이름
- `streams_count`: 스트림 개수
- `status`: 초기 상태 "launching"
- `launched_at`: 실행 시각

<br>

### 단계 4: Docker 실행 명령 구성
**위치:** `services/process_launcher.py`

```python
# DeepStream 실행 명령 구성
deepstream_cmd = ["deepstream-app", "-c", config_path] + additional_args

# Docker exec 명령 구성  
docker_cmd = [
    "docker", "exec", "-d",          # -d는 detached 모드
    "-e", f"APP_ID={instance_id}",   # 환경변수 설정
    docker_container
] + deepstream_cmd
```

**최종 명령 예시:**
```bash
docker exec -d -e APP_ID=stream_241231_123456_abcd1234 deepstream_container deepstream-app -c /path/to/config.txt
```

**주요 구성 요소:**
- `-d`: detached 모드로 백그라운드 실행
- `-e APP_ID={instance_id}`: DeepStream 앱이 WebSocket 연결 시 사용할 식별자
- 컨테이너 이름과 deepstream-app 실행 명령

<br>

### 단계 5: 프로세스 실행
**위치:** `services/process_launcher.py`

```python
proc = subprocess.Popen(
    docker_cmd,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE
)

process_info.host_pid = proc.pid  # 호스트에서의 subprocess PID
process_info.status = "running"
```

**수행 작업:**
- `subprocess.Popen()`으로 Docker 명령 실행
- 호스트에서의 subprocess PID 기록
- 프로세스 상태를 "running"으로 변경

<br>

### 단계 6: 프로세스 등록 및 매니저 연동
**위치:** `services/process_launcher.py`

```python
# 프로세스 등록
self.processes[process_id] = process_info

# DeepStream 매니저에 인스턴스 등록
if streams_count:
    deepstream_manager.register_instance(
        instance_id, config_path, streams_count
    )
```

**수행 작업:**
- ProcessLauncher 내부 딕셔너리에 프로세스 정보 저장
- DeepStreamManager에 인스턴스 등록 (streams_count가 있는 경우)
- 스트림 슬롯 초기화 (0부터 streams_count-1까지)

<br>

### 단계 7: DeepStream 애플리케이션 내부 초기화
**위치:** Docker 컨테이너 내부

DeepStream 애플리케이션이 시작되면서 다음 작업들이 수행됩니다:

1. **환경변수 인식:**
   ```c
   const char* app_id = getenv("APP_ID");  // instance_id 값 획득
   ```

2. **로그 경로 설정:** (REQUEST.md 참조)
   ```
   /opt/nvidia/deepstream/deepstream/cityeyelab/vmnt/DeepStream-Yolo/logs/
   instid_<instance_id>-pid_<process-id>-date_<실행시각>/
   instid_<instance_id>-pid_<process-id>-date_<실행시각>.log
   ```

3. **WebSocket 클라이언트 초기화:**
   - FastAPI WebSocket 서버에 연결 시도
   - `app_ready` 메시지로 초기 handshake 수행

4. **스트림 파이프라인 초기화:**
   - 설정 파일 기반으로 GStreamer 파이프라인 생성
   - 스트림 슬롯별 큐 시스템 초기화

<br>

## 3.3. WebSocket 연결 및 Handshake

### 단계 8: WebSocket 연결 establishment
**위치:** `services/websocket_manager.py`

DeepStream 앱이 WebSocket 서버에 연결하면 다음 handshake가 진행됩니다:

1. **DeepStream → FastAPI (app_ready 메시지):**
```json
{
  "action": "app_ready",
  "request_id": "<UUID>",
  "instance_id": "stream_241231_123456_abcd1234",
  "config_path": "/path/to/config.txt",
  "streams_count": 3,
  "status": "ok",
  "version": "DeepStream-Yolo v7.1",
  "gpu_allocated": [0, 1, 2],
  "start_time": "2024-12-31T12:34:56+09:00"
}
```

2. **FastAPI → DeepStream (execute_ack 응답):**
```json
{
  "event": "execute_ack", 
  "request_id": "<UUID>",
  "instance_id": "stream_241231_123456_abcd1234",
  "config_verified": true,
  "streams_count_verified": true,
  "status": "confirmed",
  "timestamp": "2024-12-31T12:34:57+09:00"
}
```

3. **상태 업데이트:**
   - `DeepStreamManager`에서 인스턴스 상태를 `IDLE`로 변경
   - WebSocket 상태를 `CONNECTED`로 변경
   - `ProcessLauncher`에서 `container_pid` 업데이트

<br>

# 4. 데이터 흐름 및 상태 관리

## 4.1. 프로세스 상태 생명주기

```
launching → running → (connected via WebSocket) → idle → (processing) → stopped/error
```

### 상태 설명:
- **launching**: 프로세스 생성 중
- **running**: Docker 프로세스 실행 중, WebSocket 연결 대기
- **connected**: WebSocket handshake 완료, 작업 대기 상태
- **idle**: 분석 작업 수행 가능 상태
- **processing**: 스트림 분석 수행 중
- **stopped**: 정상 종료
- **error**: 오류로 인한 비정상 상태

<br>

## 4.2. 관련 데이터베이스/저장소

### ProcessLauncher.processes (In-Memory)
```python
{
  "process_id": ProcessInfo {
    process_id: "uuid-string",
    instance_id: "stream_241231_123456_abcd1234", 
    config_path: "/path/to/config.txt",
    docker_container: "deepstream_container",
    streams_count: 3,
    host_pid: 12345,
    container_pid: 67890,  # WebSocket handshake 시 업데이트
    status: "running",
    launched_at: datetime.now(),
    log_path: None,  # 현재 미구현
    command: "docker exec -d ...",
    error_message: None
  }
}
```

### DeepStreamManager.instances (In-Memory)  
```python
{
  "instance_id": DeepStreamInstance {
    instance_id: "stream_241231_123456_abcd1234",
    config_path: "/path/to/config.txt", 
    streams_count: 3,
    status: InstanceStatus.IDLE,
    ws_status: WSStatus.CONNECTED,
    launched_at: datetime.now(),
    log_path: None,
    last_ping: datetime.now(),
    streams: {
      0: StreamInfo(stream_id=0, status="idle", camera_queue=[]),
      1: StreamInfo(stream_id=1, status="idle", camera_queue=[]),
      2: StreamInfo(stream_id=2, status="idle", camera_queue=[])
    },
    last_metrics: None,
    last_metrics_time: None
  }
}
```

<br>

# 5. 오류 처리 및 예외 상황

## 5.1. 주요 오류 시나리오

### Docker 컨테이너 실행 상태 오류:
```json
{
  "success": false,
  "message": "Docker 컨테이너가 실행 중이 아닙니다: deepstream_container. 컨테이너를 먼저 실행해주세요."
}
```

### Docker 컨테이너 접근 오류:
```json
{
  "success": false,
  "message": "DeepStream 앱 실행 실패: No such container: deepstream_container"
}
```

### 설정 파일 경로 오류:
```json
{
  "success": false, 
  "message": "DeepStream 앱 실행 실패: Config file not found: /invalid/path.txt"
}
```

### 프로세스 실행 오류:
```json
{
  "success": false,
  "message": "DeepStream 앱 실행 실패: Permission denied"
}
```

<br>

## 5.2. 오류 처리 메커니즘

1. **Exception 캐치**: 모든 예외는 `try-catch`로 처리
2. **상태 업데이트**: 오류 발생 시 `process_info.status = "error"`로 변경
3. **오류 메시지 저장**: `process_info.error_message`에 상세 오류 정보 기록
4. **로깅**: 모든 오류는 로거를 통해 기록
5. **응답 생성**: 성공=False로 설정하여 클라이언트에 전달

<br>

# 6. 컨테이너 상태 관리

## 6.1. 컨테이너 실행 여부 확인

**전제 조건**: 본 FastAPI 프로젝트는 Docker 컨테이너가 이미 실행 중이라는 가정 하에 구성됩니다. 컨테이너의 실행은 개발자가 직접 수행해야 합니다.

**확인 메커니즘**: 모든 Docker 관련 작업 전에 `check_container_running()` 메서드를 통해 컨테이너 상태를 확인합니다.

```python
def check_container_running(self, container_name: str) -> bool:
    """Docker 컨테이너 실행 여부 확인"""
    check_cmd = ["docker", "inspect", "-f", "{{.State.Running}}", container_name]
    result = subprocess.run(check_cmd, capture_output=True, text=True, timeout=10)
    
    if result.returncode == 0:
        is_running = result.stdout.strip().lower() == "true"
        return is_running
    return False
```

**적용 범위**:
- `launch_deepstream_app()`: 프로세스 실행 전 컨테이너 상태 확인
- `terminate_process()`: 프로세스 종료 전 컨테이너 상태 확인 (실행 중이 아닐 경우 이미 종료된 것으로 간주)
- `check_process_status()`: 프로세스 상태 조회 전 컨테이너 상태 확인

**로깅 전략**:
- 컨테이너 실행 중: DEBUG 레벨 로그
- 컨테이너 실행 중이 아님: WARNING 레벨 로그  
- 컨테이너 상태 확인 실패: ERROR 레벨 로그

<br>

# 7. 보안 및 리소스 관리

## 7.1. 보안 고려사항

- **컨테이너 격리**: Docker 컨테이너를 통한 프로세스 격리
- **환경변수 전달**: 민감 정보는 환경변수로 안전하게 전달
- **프로세스 식별**: 고유한 APP_ID를 통한 프로세스 식별 및 추적

## 7.2. 리소스 관리

- **프로세스 추적**: host_pid와 container_pid를 통한 이중 추적
- **메모리 관리**: In-memory 딕셔너리를 통한 프로세스 정보 관리
- **정리 메커니즘**: cleanup_stopped_processes 엔드포인트를 통한 리소스 정리

<br>

# 8. 모니터링 및 디버깅

## 8.1. 로깅 정보

```
INFO - DeepStream 앱 실행 시작: stream_241231_123456_abcd1234
DEBUG - 실행 명령: docker exec -d -e APP_ID=stream_241231_123456_abcd1234 deepstream_container deepstream-app -c /path/to/config.txt
INFO - DeepStream 앱 실행 성공: stream_241231_123456_abcd1234 (Host PID: 12345)
```

## 8.2. 상태 조회 엔드포인트

- `GET /deepstream/processes/`: 모든 프로세스 목록 조회
- `GET /deepstream/processes/{process_id}`: 특정 프로세스 상태 조회  
- `GET /deepstream/processes/by-instance/{instance_id}`: 인스턴스 ID로 프로세스 조회
- `GET /deepstream/instances/`: 모든 인스턴스 목록 조회
- `GET /deepstream/instances/{instance_id}`: 특정 인스턴스 상태 조회

<br>

# 9. 향후 개선 사항

## 9.1. 현재 미구현 기능

1. **로그 경로 설정**: REQUEST.md에 명시된 로그 경로 규칙 구현 필요
2. **로그 로테이션**: 2MB 제한, 최대 10개 파일 로테이션 구현 필요
3. **컨테이너 PID 획득**: WebSocket handshake 없이도 컨테이너 내부 PID 추적
4. **설정 파일 검증**: config_path 유효성 검사 강화

## 9.2. 성능 최적화

1. **비동기 처리**: subprocess 실행의 완전한 비동기화
2. **연결 풀링**: Docker 명령 실행 최적화
3. **상태 캐싱**: 프로세스 상태 조회 성능 향상
4. **배치 처리**: 다중 인스턴스 동시 실행 지원

<br> 