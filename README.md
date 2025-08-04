# DeepStream 제어 FastAPI 서버

이 프로젝트는 다수의 DeepStream-Yolo 앱을 제어하는 FastAPI 서버입니다. WebSocket을 통한 양방향 통신을 지원하며, 영상 분석 요청 관리, 상태 모니터링, 메트릭 수집 등의 기능을 제공합니다.

## 🏗️ 시스템 아키텍처

```
외부 클라이언트 ←→ FastAPI 서버 ←→ [WebSocket] ←→ DeepStream-Yolo 앱들
                      ↓
                 상태 관리 시스템
                 (인스턴스, 스트림, 카메라)
```

### 주요 컴포넌트

- **FastAPI 서버**: WebSocket 서버 역할, REST API 제공
- **프로세스 런처**: Docker 컨테이너 내 DeepStream 앱 실행 및 관리
- **DeepStream-Yolo 앱**: WebSocket 클라이언트 역할, 실제 영상 분석 수행
- **상태 관리자**: 인스턴스별 스트림 슬롯 및 분석 상태 관리
- **WebSocket 관리자**: 연결 관리 및 메시지 라우팅

## 📦 프로젝트 구조

```
├── main.py                          # FastAPI 앱 진입점
├── sample_data.json                 # 테스트용 샘플 데이터
├── README.md                        # 프로젝트 문서
├── models/
│   └── websocket_messages.py        # WebSocket 메시지 모델들
├── services/
│   ├── deepstream_manager.py        # DeepStream 인스턴스 상태 관리
│   ├── websocket_manager.py         # WebSocket 연결 관리
│   └── process_launcher.py          # DeepStream 프로세스 실행 및 관리
└── routes/
    └── handle_deepstream.py         # DeepStream 제어 API 라우터
```

## 🚀 실행 방법

### 1. 의존성 설치

```bash
pip install fastapi uvicorn websockets pydantic
```

### 2. 서버 실행

```bash
python main.py
```

또는

```bash
uvicorn main:app --host 0.0.0.0 --port 18000 --reload
```

### 3. API 문서 확인

브라우저에서 `http://localhost:18000/docs` 접속

## 📡 WebSocket 통신 프로토콜

### DeepStream → FastAPI (수신 메시지)

1. **앱 준비 완료** (`app_ready`)
2. **분석 시작 응답** (`analysis_started`)
3. **파일 처리 시작** (`processing_started`)
4. **파일 처리 완료** (`file_done`)
5. **분석 완료** (`analysis_complete`)
6. **분석 중단 응답** (`analysis_interrupted`)
7. **앱 종료 응답** (`app_terminated`)
8. **메트릭 응답** (`metrics_response`)
9. **분석 상태 응답** (`analysis_status`)

### FastAPI → DeepStream (송신 메시지)

1. **실행 확인** (`execute_ack`)
2. **분석 시작** (`start_analysis`)
3. **파일 푸시** (`push_file`)
4. **분석 중단** (`interrupt_analysis`)
5. **앱 종료** (`terminate_app`)
6. **메트릭 조회** (`query_metrics`)
7. **분석 상태 조회** (`query_analysis_status`)

## 🔧 주요 API 엔드포인트

### 프로세스 실행 및 관리

- `POST /deepstream/launch` - DeepStream 앱 실행
- `GET /deepstream/processes` - 모든 프로세스 목록 조회
- `GET /deepstream/processes/{process_id}` - 특정 프로세스 상태 조회
- `POST /deepstream/processes/{process_id}/terminate` - 프로세스 종료
- `GET /deepstream/processes/{process_id}/logs` - 프로세스 로그 조회
- `GET /deepstream/processes/by-instance/{instance_id}` - 인스턴스 ID로 프로세스 조회
- `POST /deepstream/processes/cleanup` - 중지된 프로세스들 정리

### 인스턴스 관리

- `GET /deepstream/instances` - 모든 인스턴스 조회
- `GET /deepstream/instances/{instance_id}` - 특정 인스턴스 조회
- `POST /deepstream/instances/{instance_id}/terminate` - 인스턴스 종료

### 분석 제어

- `POST /deepstream/analysis/start` - 영상 분석 시작
- `POST /deepstream/analysis/{instance_id}/interrupt` - 분석 중단
- `GET /deepstream/analysis/status` - 전체 분석 상태 조회
- `GET /deepstream/analysis/status/{instance_id}` - 특정 인스턴스 분석 상태

### 메트릭 조회

- `GET /deepstream/metrics` - 모든 인스턴스 메트릭
- `GET /deepstream/metrics/{instance_id}` - 특정 인스턴스 메트릭
- `POST /deepstream/metrics/{instance_id}/refresh` - 메트릭 새로고침

### WebSocket 연결

- `WS /deepstream/ws` - DeepStream 앱과의 WebSocket 연결

## 🧪 테스트 기능

### 테스트 엔드포인트

- `GET /deepstream/test/sample-data` - 샘플 데이터 조회
- `GET /deepstream/test/scenarios` - 테스트 시나리오 목록
- `POST /deepstream/test/mock-analysis` - 모의 분석 요청
- `POST /deepstream/test/simulate-handshake/{instance_id}` - 핸드셰이크 시뮬레이션
- `POST /deepstream/test/simulate-metrics/{instance_id}` - 메트릭 업데이트 시뮬레이션
- `POST /deepstream/test/simulate-file-processing/{instance_id}` - 파일 처리 상태 시뮬레이션
- `POST /deepstream/test/reset-instance/{instance_id}` - 인스턴스 상태 리셋

### 테스트 시나리오 예시

#### 1. 인스턴스 상태 확인

```bash
curl -X GET "http://localhost:18000/deepstream/instances"
```

#### 2. 핸드셰이크 시뮬레이션

```bash
curl -X POST "http://localhost:18000/deepstream/test/simulate-handshake/stream_alpha"
```

#### 3. 모의 분석 요청

```bash
curl -X POST "http://localhost:18000/deepstream/test/mock-analysis"
```

#### 4. 분석 상태 조회

```bash
curl -X GET "http://localhost:18000/deepstream/analysis/status/stream_alpha"
```

#### 5. 메트릭 시뮬레이션

```bash
curl -X POST "http://localhost:18000/deepstream/test/simulate-metrics/stream_alpha"
```

#### 6. DeepStream 앱 실행

```bash
curl -X POST "http://localhost:18000/deepstream/launch" \
  -H "Content-Type: application/json" \
  -d '{
    "config_path": "/opt/nvidia/deepstream/deepstream/cityeyelab/vmnt/DeepStream-Yolo/configs/deepstream_app_config.txt",
    "streams_count": 3,
    "gpu_allocated": [0, 1],
    "docker_container": "deepstream_container"
  }'
```

#### 7. 프로세스 목록 조회

```bash
curl -X GET "http://localhost:18000/deepstream/processes"
```

#### 8. 프로세스 로그 조회

```bash
curl -X GET "http://localhost:18000/deepstream/processes/{process_id}/logs?lines=50"
```

## 📊 샘플 데이터 구조

`sample_data.json`에는 다음과 같은 테스트 데이터가 포함되어 있습니다:

- **deepstream_instances**: 3개의 샘플 인스턴스 (stream_alpha, stream_beta, stream_gamma)
- **analysis_requests**: 폴더 및 파일 단위 분석 요청 샘플
- **stream_status_samples**: 다양한 상태의 스트림/카메라/파일 정보
- **metrics_samples**: CPU, RAM, GPU 사용률 샘플
- **test_scenarios**: 성공/실패 시나리오들
- **error_scenarios**: 오류 상황 시뮬레이션 데이터
- **launch_examples**: 프로세스 실행 요청 샘플 (기본, 고급, 커스텀)
- **process_examples**: 프로세스 상태 샘플 (실행 중, 중지됨, 오류)
- **docker_settings**: Docker 컨테이너 및 경로 설정

## 🔐 WebSocket 인증 및 보안

- DeepStream 앱은 연결 시 `app_ready` 메시지로 인증
- 인스턴스 ID와 설정 경로 검증
- 연결 상태 모니터링 및 자동 재연결 지원

## 📝 로그 관리

- 로그 파일: `logs/gpu_server.log`
- 로테이션: 5MB 제한, 최대 5개 백업
- 포맷: `YYYY-MM-DD HH:MM:SS.mmm - 로거명 - 레벨 - 메시지`

## 🔧 설정 사항

### 환경 변수

- `APP_ID`: DeepStream 앱 실행 시 인스턴스 식별자

### 주요 설정

- 서버 포트: 18000
- WebSocket 연결 타임아웃: 기본값 사용
- 로그 레벨: INFO

## 🐛 문제 해결

### 일반적인 문제들

1. **WebSocket 연결 실패**
   - 네트워크 연결 확인
   - 포트 충돌 확인 (18000번 포트)
   - 방화벽 설정 확인

2. **인스턴스 인식 안됨**
   - `sample_data.json`에 해당 인스턴스 정보 있는지 확인
   - 설정 경로 일치 여부 확인

3. **분석 시작 실패**
   - 사용 가능한 스트림 슬롯 확인
   - 인스턴스 연결 상태 확인
   - 로그 파일에서 오류 메시지 확인

### 디버깅 팁

- `/deepstream/health` 엔드포인트로 전체 상태 확인
- `/deepstream/test/scenarios`로 사용 가능한 테스트 시나리오 확인
- 로그 파일에서 WebSocket 연결 및 메시지 교환 상태 확인

## 📚 참고 문서

- [FastAPI 공식 문서](https://fastapi.tiangolo.com/)
- [WebSocket 프로토콜](https://tools.ietf.org/html/rfc6455)
- [Pydantic 모델](https://pydantic-docs.helpmanual.io/)

## 🤝 기여하기

1. 이슈 생성
2. 기능 브랜치 생성
3. 변경사항 커밋
4. 풀 리퀘스트 생성

## 📄 라이센스

이 프로젝트는 MIT 라이센스 하에 배포됩니다.