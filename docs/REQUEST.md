# ds analysis 정리본

<br>

# <br>

# DeepStream-Yolo Custom App 7.1 구조 및 WebSocket 통합 방안

<br>

# 1\. 현재 코드 상황

## 1.1. DeepStream 앱 주요 구조와 스트림 분석 요청 처리 방식

DeepStream-Yolo의 커스텀 앱(버전 7.1)은 NVIDIA DeepStream의 `deepstream-app` 예제를 C 코드로 확장한 것으로, **GStreamer 파이프라인**과 **GLib 메인 루프**를 기반으로 동작합니다. 애플리케이션 컨텍스트(`AppCtx`)에 파이프라인과 설정을 보관하고, `deepstream_app_main.c`에서 설정 파일을 파싱한 후 파이프라인을 생성 및 실행합니다. 이 앱의 특징 중 하나는 **디렉토리 기반 입력**을 처리하기 위한 **멀티 파일 큐 시스템**(multi-file queue system)을 도입한 점입니다.

- 설정 파일에서 `queue-mode-enabled=1`로 지정하면 **큐 모드**가 활성화됩니다. 이 경우 각 입력 소스에 대해 `queue-watch-directory` (모니터링할 디렉토리 경로)와 `queue-file-pattern` (파일 패턴)을 설정할 수 있습니다[GitHub](https://github.com/zzy50/deepstream-yolo/blob/6c7ea3b67b187d405fd2453f05d201f13abcbe70/DeepStream-Yolo/deepstream_app_config_queue.txt#L12-L20). 예를 들어, `uri=file:///dev/null`로 초기 URI를 비워두고 대신 디렉토리 경로와 파일 패턴(`*.mp4` 등)을 제공하면, 해당 디렉토리의 파일들이 스트림 소스로 사용됩니다[GitHub](https://github.com/zzy50/deepstream-yolo/blob/6c7ea3b67b187d405fd2453f05d201f13abcbe70/DeepStream-Yolo/deepstream_app_config_queue.txt#L18-L26).
- **파이프라인 생성 전 단계:** `queue_mode_enabled` 설정이 참이면 애플리케이션은 멀티 파일 큐 시스템을 초기화합니다. `init_multi_file_queue_system()` 함수를 통해 `AppCtx` 내 각 활성 소스에 대한 큐 구조(`NvDsFileQueue`)를 할당하고, GLib의 `GQueue`와 뮤텍스/조건변수로 구성된 큐를 준비합니다[GitHub](https://github.com/zzy50/deepstream-yolo/blob/6c7ea3b67b187d405fd2453f05d201f13abcbe70/DeepStream-Yolo/custom_app_7.1/deepstream_app_file_queue.c#L60-L68)[GitHub](https://github.com/zzy50/deepstream-yolo/blob/6c7ea3b67b187d405fd2453f05d201f13abcbe70/DeepStream-Yolo/custom_app_7.1/deepstream_app_file_queue.c#L70-L78). 이때 설정된 watch 디렉토리와 파일 패턴을 `NvDsFileQueue`에 저장하고, 큐 모드가 활성인 소스의 개수를 집계합니다 (큐마다 `file_queue`라는 GQueue와 `queue_mutex`, `queue_cond`로 동기화 기능을 갖춤). 초기화가 완료되면 `"Multi file queue system initialization completed"` 로그를 출력합니다[GitHub](https://github.com/zzy50/deepstream-yolo/blob/6c7ea3b67b187d405fd2453f05d201f13abcbe70/DeepStream-Yolo/custom_app_7.1/deepstream_app_main.c#L697-L705).
- **분석 요청(디렉토리)의 처리:** 프로그램 시작 시 `auto_detect_initial_files()`를 호출하여 각 소스 디렉토리의 파일을 모두 검색합니다. 첫 번째 파일을 **초기 스트림 소스**로 선택하여 해당 소스의 URI를 그 파일로 업데이트하고[GitHub](https://github.com/zzy50/deepstream-yolo/blob/6c7ea3b67b187d405fd2453f05d201f13abcbe70/DeepStream-Yolo/custom_app_7.1/deepstream_app_file_queue.c#L500-L508), 나머지 파일들은 `add_file_to_source_queue()`를 통해 해당 소스의 큐에 등록합니다[GitHub](https://github.com/zzy50/deepstream-yolo/blob/6c7ea3b67b187d405fd2453f05d201f13abcbe70/DeepStream-Yolo/custom_app_7.1/deepstream_app_file_queue.c#L515-L523). 이렇게 함으로써 \*“디렉토리 기반 분석 요청”\*에 해당하는 다수의 파일을 한 번에 파이프라인에 연결해둘 수 있습니다.

> 예를 들어, source0에 대해 디렉토리 내 mp4 파일들을 찾아 첫 파일을 `file:///...` URI로 설정하고, 나머지 파일 경로들은 GQueue에 쌓습니다. 위 코드에서는 파일 리스트를 이름순으로 정렬한 뒤 첫 파일을 선택하고 `appCtx->config.multi_source_config[i].uri`에 설정하며, 나머지 파일 경로에 대해서는 `add_file_to_source_queue`로 큐에 추가하고 있습니다[GitHub](https://github.com/zzy50/deepstream-yolo/blob/6c7ea3b67b187d405fd2453f05d201f13abcbe70/DeepStream-Yolo/custom_app_7.1/deepstream_app_file_queue.c#L500-L508)[GitHub](https://github.com/zzy50/deepstream-yolo/blob/6c7ea3b67b187d405fd2453f05d201f13abcbe70/DeepStream-Yolo/custom_app_7.1/deepstream_app_file_queue.c#L515-L523). 이렇게 초기화되면 각 소스(bin)는 자신의 입력 큐를 갖춘 상태로 파이프라인이 시작됩니다.

## 1.2. 디렉토리 입력 파일을 스트림에 투입하는 큐 처리 방식

**큐 모드**에서는 지정된 디렉토리의 파일들을 순차 스트림으로 처리하여 하나의 분석 요청을 수행합니다. 처리 흐름은 다음과 같습니다:

- **큐 생성 및 초기 설정:** 앞서 언급한 대로 `init_multi_file_queue_system`에서 소스마다 `NvDsFileQueue`를 생성합니다. 이 구조체에는 `GQueue *file_queue`와 이를 보호하는 `GMutex` 및 `GCond`가 포함되어 있어 다중 쓰레드 환경에서도 안전하게 파일 경로를 넣고 뺄 수 있게 설계되어 있습니다[GitHub](https://github.com/zzy50/deepstream-yolo/blob/6c7ea3b67b187d405fd2453f05d201f13abcbe70/DeepStream-Yolo/custom_app_7.1/deepstream_app_file_queue.c#L60-L68). 각 큐에는 `watch_directory` (입력 디렉토리 경로)와 `file_pattern`도 함께 저장되며, 소스 ID와 `AppCtx` 포인터도 보관합니다[GitHub](https://github.com/zzy50/deepstream-yolo/blob/6c7ea3b67b187d405fd2453f05d201f13abcbe70/DeepStream-Yolo/custom_app_7.1/deepstream_app_file_queue.c#L70-L78). 큐 모드가 활성화된 경우, 프로그램 초기화 단계에서 이러한 큐가 준비되고 `"File queue initialized (Source X)"` 로그가 출력됩니다.
- **디렉토리 내 파일 스캔 및 큐 적재:** `auto_detect_initial_files()` 함수가 실행되면, 설정된 `watch_directory`를 열어서 해당 디렉토리의 파일 목록을 읽습니다. 지정한 패턴에 맞는 모든 파일 경로를 수집한 후 **알파벳 순으로 정렬**하여 첫 번째 파일을 선정합니다. 이 첫 파일은 해당 소스의 URI로 설정되어 파이프라인이 **초기에 이 파일을 재생**하도록 만듭니다[GitHub](https://github.com/zzy50/deepstream-yolo/blob/6c7ea3b67b187d405fd2453f05d201f13abcbe70/DeepStream-Yolo/custom_app_7.1/deepstream_app_file_queue.c#L500-L508). 그 다음, 첫 파일을 제외한 나머지 파일들은 반복문을 통해 차례로 `add_file_to_source_queue()`에 전달되어 GQueue에 쌓입니다[GitHub](https://github.com/zzy50/deepstream-yolo/blob/6c7ea3b67b187d405fd2453f05d201f13abcbe70/DeepStream-Yolo/custom_app_7.1/deepstream_app_file_queue.c#L515-L523). 이렇게 하면 파이프라인 시작 시 첫 영상/파일을 처리하고, 나머지 파일들은 대기열에 들어간 상태가 됩니다. (설정 예시로, config에서 source0~2 모두 `uri=file:///dev/null`로 시작하지만, 실행 시 자동으로 각 디렉토리의 첫 MP4 파일로 교체되는 것을 볼 수 있습니다[GitHub](https://github.com/zzy50/deepstream-yolo/blob/6c7ea3b67b187d405fd2453f05d201f13abcbe70/DeepStream-Yolo/custom_app_7.1/deepstream_app_file_queue.c#L500-L508).)
- **파이프라인 실행 및 EOS 이벤트 처리:** 파이프라인이 시작되어 각 소스의 첫 파일을 **재생/분석**합니다. 파일 하나를 모두 처리하고 \*\*EOS (End of Stream)\*\*에 도달하면, 일반적으로 GStreamer 파이프라인은 종료 신호를 받지만, 여기서는 **EOS 패드 프로브**를 활용하여 특별 처리합니다. `source_eos_probe` 함수가 각 소스의 EOS 이벤트를 감지하면, 해당 이벤트를 **메인 쓰레드로 위임**하도록 `g_idle_add()`를 사용합니다[GitHub](https://github.com/zzy50/deepstream-yolo/blob/6c7ea3b67b187d405fd2453f05d201f13abcbe70/DeepStream-Yolo/custom_app_7.1/deepstream_app_file_queue.c#L600-L609). 이 호출은 `handle_eos_in_main_thread` 함수를 메인 루프 컨텍스트에서 실행하도록 예약하며, 동시에 EOS 이벤트를 `GST_PAD_PROBE_DROP`으로 **가로채서 파이프라인이 자체 종료되지 않도록 차단**합니다[GitHub](https://github.com/zzy50/deepstream-yolo/blob/6c7ea3b67b187d405fd2453f05d201f13abcbe70/DeepStream-Yolo/custom_app_7.1/deepstream_app_file_queue.c#L611-L615). 이렇게 함으로써 파이프라인은 멈추지 않고 다음 입력을 기다리는 상태가 됩니다.
- **다음 파일로 전환:** 메인 루프에서 `handle_eos_in_main_thread`가 실행되면, 해당 소스의 큐에서 다음 파일 경로 노드를 pop하여 꺼냅니다. 다음 파일이 존재하는 경우, 로그를 출력하고(`"Loading next file for source X: <path>..."` 등) `create_next_file_source()`를 호출하여 **파이프라인 소스 요소의 URI를 새로운 파일로 교체**합니다[GitHub](https://github.com/zzy50/deepstream-yolo/blob/6c7ea3b67b187d405fd2453f05d201f13abcbe70/DeepStream-Yolo/custom_app_7.1/deepstream_app_file_queue.c#L561-L569). 이 함수 내부에서는 기존 파일 소스 bin을 `GST_STATE_NULL`로 정지시킨 후 URI를 새 파일로 설정하고, 다시 READY/PAUSED/PLAYING 상태로 올려 파이프라인에 연결합니다[GitHub](https://github.com/zzy50/deepstream-yolo/blob/6c7ea3b67b187d405fd2453f05d201f13abcbe70/DeepStream-Yolo/custom_app_7.1/deepstream_app_file_queue.c#L388-L397)[GitHub](https://github.com/zzy50/deepstream-yolo/blob/6c7ea3b67b187d405fd2453f05d201f13abcbe70/DeepStream-Yolo/custom_app_7.1/deepstream_app_file_queue.c#L419-L428). 그런 다음 소스 bin을 PLAYING으로 전환하여 새 파일 스트림이 즉시 처리되도록 합니다. 이 과정이 성공하면 `handle_eos_in_main_thread`는 약간의 지연(`g_usleep`)을 둬서 파이프라인 안정화를 기다린 뒤 리턴합니다[GitHub](https://github.com/zzy50/deepstream-yolo/blob/6c7ea3b67b187d405fd2453f05d201f13abcbe70/DeepStream-Yolo/custom_app_7.1/deepstream_app_file_queue.c#L563-L571). 결과적으로 **추가적인 분석 요청 없이도** 디렉토리 내 다음 파일이 자동으로 스트림에 투입되어 연속 처리가 이루어집니다.
- **모든 파일 처리 완료 및 종료:** 만약 해당 소스 큐에 더 이상 파일이 없을 경우(`g_queue_pop_head` 결과 없음), 코드에서는 해당 소스를 `is_finished = TRUE`로 표시하고 `"No more files in queue for source X - marking as finished"` 로그를 남깁니다[GitHub](https://github.com/zzy50/deepstream-yolo/blob/6c7ea3b67b187d405fd2453f05d201f13abcbe70/DeepStream-Yolo/custom_app_7.1/deepstream_app_file_queue.c#L280-L288)[GitHub](https://github.com/zzy50/deepstream-yolo/blob/6c7ea3b67b187d405fd2453f05d201f13abcbe70/DeepStream-Yolo/custom_app_7.1/deepstream_app_file_queue.c#L298-L305). 이어서 `NvDsMultiFileQueue->finished_sources` 값을 증가시키고, **모든 소스의 처리가 완료되었는지** 확인합니다. `finished_sources`가 `num_queues`와 같아지면 (즉 모든 큐가 비었으면), `"All sources processing completed! Terminating application."` 메시지와 함께 `appCtx->quit = TRUE`로 설정합니다[GitHub](https://github.com/zzy50/deepstream-yolo/blob/6c7ea3b67b187d405fd2453f05d201f13abcbe70/DeepStream-Yolo/custom_app_7.1/deepstream_app_file_queue.c#L303-L311). 이 플래그는 메인 루프의 모니터링 로직에서 확인되며, 모든 인스턴스의 `appCtx->quit`가 TRUE이면 `g_main_loop_quit()`를 호출하여 메인 루프를 종료시킵니다[GitHub](https://github.com/zzy50/deepstream-yolo/blob/6c7ea3b67b187d405fd2453f05d201f13abcbe70/DeepStream-Yolo/custom_app_7.1/deepstream_app_main.c#L273-L281). 이렇게 해서 디렉토리의 모든 파일(즉 하나의 분석 요청 단위)이 끝나면 애플리케이션이 종료되거나, 후속 처리를 위해 루프를 빠져나가도록 되어 있습니다. (일반 deepstream-app에서는 종료 대신 루프를 유지할 수도 있지만, 현재 구현은 기본적으로 한 배치의 파일 처리가 끝나면 프로그램을 끝내는 동작을 합니다.)

요약하면, **DeepStream-Yolo 커스텀 앱은 디렉토리 단위를 하나의 스트림 분석 요청으로 간주하여**, 해당 디렉토리의 파일들을 초기화 단계에서 큐잉하고, GStreamer 파이프라인을 통해 **순차적으로 처리**합니다. GQueue 기반의 내부 큐와 EOS 이벤트 핸들링을 이용해 **파일 경계를 넘어서 끊김 없이** 다음 입력을 이어서 처리하며, 모든 큐가 소진되면 메인 루프를 종료하는 방식입니다.

<br>

# 2\. 수정 요구사항

<br>

## 2.1. 요구사항 요약.

웹소켓 라이브러리: libwebsockets

웹소켓 서버: FastAPI (호스트 환경에서 실행)

웹소켓 클라이언트: deepstream-app (Deepstream 컨테이너는 1개만 생성되고, 그 컨테이너 안에서 deepstream-app 프로세스가 3~5개 정도 실행될 예정.)

FastAPI 및 Deepstream 컨테이너는 하나의 시스템 내에서 동작함.

<br>

- 다음의 동작이 수정되어야 함.
    - 현재 동작 방식: 모든 stream slot의 처리가 마무리되면 deepstream-app이 스스로 종료됨
    - 다음과 같이 수정 필요: 
        - 모든 stream slot의 처리가 마무리되어도 glib 메인루프 및 웹소켓 클라이언트 루프 모두 살아있는 상태로, 언제든 다음 분석 요청을 받을 수 있는 상태를 계속 유지해야함. 
        - 웹소켓 연결 실패 감지 및 연결 재시도 또한 정교하고 robust하게 동작할 수 있도록 세심한 구현 필요.
    - 기타 참고사항:
        - Deepstream 컨테이너의 제어 및 해당 컨테이너 내에서 deepstream-app 프로세스를 시작하는 역할은 FastAPI에서 수행 예정.  
        - deepstream-app은 컨테이너 내부에서 장시간 실행될 예정.

    - 통신은 단방향이 아닌 **양방향**이어야 함

- 외부 FastAPI 서버는 다음을 수행:
    - 분석 대상 디렉토리 경로 전달
    - 분석 상태 및 로그 요청
    - 종료 명령 전송

- `deepstream-app`은 다음을 수행:
    - deepstream-app 은 웹소켓 연결 상태를 가능한한 상시 유지하여야 함.
    - 웹소켓 연결이 끊어졌을 때의 연결 재시도의 책임은 deepstream-app 에 있음.
    - 디렉토리 기반 분석 요청을 수신하여 처리 시작
    - 분석 중 발생한 이벤트 및 로그를 FastAPI에 **실시간으로 전송**
    - logging관련
        - log 파일은 1개당 2MB 제한을 가지며, rotation은 최대 10개까지.
        - deepstream-app 인스턴스는 각자만의 log가 담길 폴더를 가지며, 그 경로는 다음과 같음.

```
/opt/nvidia/deepstream/deepstream/cityeyelab/vmnt/DeepStream-Yolo/logs/instid_<instance_id>-pid_<process-id>-date_<현재시각(%y%m%d_%H%M%S)>/instid_<instance_id>-pid_<process-id>-date_<프로세스 실행 시각(%y%m%d_%H%M%S)>.log (or .log.1, .log.2, ...etc)
```

<br>

## 2.2. FastAPI가 deepstream-app 프로세스를 실행하는 방법

목표 구조는 **FastAPI가 DeepStream 컨테이너 내부의 여러 `deepstream-app` 인스턴스를 실행**시키되, 실행 이후에는 **각 프로세스가 FastAPI로부터 완전히 독립적**이어야 하며, 동시에 **식별 및 제어 가능성**을 확보하는 것입니다. 아래는 이 요구 사항을 만족하는 아키텍처 설계와 실행 전략입니다.

이에 대한 주요 구현은 FastAPI에서 이뤄질 예정이므로, deepstream-app에서 구현이 필요한 일부 내용 외에, FastAPI에서 구현되어야 하는 대부분의 내용은 그냥 참고만 해주세요.

* * *

### ✅ 핵심 설계 원칙

1. **프로세스 독립성 확보** – FastAPI가 실행은 담당하되, 실행된 `deepstream-app`은 별도 세션, PID, 로그 등에서 완전한 독립성을 유지합니다.
2. **명확한 식별 체계** – FastAPI에서 지정한 식별자가 deepstream-app 전반에 반영되어야 하며, 이를 통해 추적/제어/로그 매칭이 가능합니다.
3. **제어 경로 이중화** – 기본은 websocket을 통한 graceful 제어지만, 예외 상황에선 FastAPI가 직접 `PID` 또는 `Unix domain socket` 등을 통해 강제 제어 가능합니다.

* * *

### 🧩 1. 프로세스 실행 전략 (FastAPI → deepstream-app)

FastAPI는 다음 형식으로 프로세스를 실행해야 합니다:

```
import subprocess

def launch_deepstream_app(app_id: str, config_path: str):
    log_file = f"/app/logs/{app_id}.log"
    process = subprocess.Popen(
        [
            "docker", "exec", "-d", "deepstream_container",
            "bash", "-c",
            f"APP_ID={app_id} deepstream-app -c {config_path} > {log_file} 2>&1"
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True  # 프로세스 그룹 독립
    )
    return {"app_id": app_id, "status": "launched"}
```

> `APP_ID` 환경변수를 넘기고, 이를 통해 deepstream-app 내부 로직에서 다양한 identifier로 활용합니다.

* * *

### 🧩 2. deepstream-app 내부에서 식별자 활용 전략

**main 함수 초입에서 `APP_ID` 를 가져와 다음에 활용:**

```
const char* app_id = getenv("APP_ID");

// 로그 파일 이름
char log_path[256];
sprintf(log_path, "/app/logs/%s.log", app_id);
freopen(log_path, "a+", stdout);
freopen(log_path, "a+", stderr);

// 프로세스명 변경 (리눅스에서 가능)
prctl(PR_SET_NAME, app_id, 0, 0, 0);
```

**이 식별자는 다음에도 활용합니다:**

- 상태 웹소켓 handshake 시 payload에 포함
- 로그파일, IPC 핸들, 쉐어드 메모리 등 key 네이밍
- 내부 상태 JSON 스냅샷 저장 시 파일명

* * *

### 🧩 3. deepstream-app 프로세스 다중화 대응

단일 컨테이너에서 여러 `deepstream-app` 인스턴스를 실행해도 충돌이 없도록 하기 위해:

- 모든 설정파일은 `--config <config_path>`로 외부 지정
- 각각 다른 `log`, `websocket`, `shared memory` 등 리소스를 `app_id` 기반으로 네임스페이스 분리
- `deepstream-app`은 내부적으로 별도 서브디렉토리(ex. `/tmp/ds/<app_id>/`) 내에만 파일 생성

* * *

### 🧩 4. FastAPI 측 상태 관리 스키마

FastAPI는 메모리 혹은 DB에서 다음 구조로 각 인스턴스를 추적:

```
{
  "app_id": "stream_alpha",
  "status": "running",
  "pid": 12125,
  "ws_status": "connected",
  "launched_at": "2025-07-25T08:12:00",
  "log_path": "/app/logs/stream_alpha.log"
}
```

식별자는 `app_id`이며, PID는 `docker exec` 내에서 `pgrep -f` 등으로 추적 가능.

* * *

### 🧩 5. FastAPI의 비정상 제어 경로 (watchdog)

**WebSocket 미연결**, 혹은 **app crash** 등을 FastAPI가 감지하는 경우:

- `docker exec`로 내부 PID 조회:

```
docker exec deepstream_container pgrep -f "APP_ID=stream_alpha"
```
- 강제 종료 (SIGTERM or SIGKILL):

```
docker exec deepstream_container pkill -f "APP_ID=stream_alpha"
```

또는, 컨테이너 내부에서 `supervisord`를 써서 app\_id 기준으로 등록한 각 프로세스를 FastAPI가 `supervisorctl` RPC로 제어 가능.

* * *

### ✅ 결론

이 구조를 도입하면:

- FastAPI는 오직 실행 및 상태 관리만 담당하며, deepstream-app의 실행 이후 상태는 완전히 독립적으로 유지
- app\_id를 기반으로 모든 자원 식별 및 추적 가능
- 컨테이너와 deepstream-app의 생명주기는 FastAPI와 무관하게 유지되며, 필요시 FastAPI에서 제어 가능

### <br>

## 2.3. 웹소켓을 통해 구현해야할 상세 기능

### 2.3.1. execute app:

- **설명:** FastAPI가 DeepStream 애플리케이션 프로세스를 처음 실행할 때의 상호작용입니다. DeepStream이 시작되면 곧바로 FastAPI의 WebSocket 서버에 접속하여 **초기 준비 상태**를 알립니다. 이 단계에서는 DeepStream 측에서 **사전에 설정된 스트림 파이프라인을 모두 열고** (예: `stream_id` 0부터 N-1까지 파이프라인 생성) 모델 로딩 등 초기화를 완료한 후, FastAPI에게 선제 handshake 요청을 보냅니다.  FastAPI도 그에 대한 응답으로, deepstream-app 실행시에 전달한 옵션 (config\_path, max\_streams 등)이 일치하는지 확인하는 메세지를 보냅니다.FastAPI가 Websocket 서버, deepstream-app이 Websocket 클라이언트이므로, 선제 handshake는 deepstream-app이 먼저 보냅니다.
- (0) **TCP 3-way Handshake:  
**– 이 부분은 운영체제의 TCP/IP 스택이 담당하며, libwebsockets 에서 별도 구현 없이 소켓 생성(connect)만으로 이루어집니다.
- (1) **DeepStream -> FastAPI (http handshake 요청.):  
– `lws_client_connect_via_info()` 호출 시 내부적으로 HTTP `GET` 헤더(Upgrade: websocket, Connection: Upgrade 등)를 자동 생성·전송합니다.  
**
- (2) **FastAPI -> DeepStream (http를 websocket으로 승격):  
– libwebsockets 의 이벤트 콜백(`LWS_CALLBACK_CLIENT_ESTABLISHED`)에서 HTTP → WebSocket 승격 완료를 감지하고, 내부 상태를 전환합니다.  
**
- **(3) DeepStream -> FastAPI (사전에 설정된 스트림 파이프라인을 모두 열고 모델 로딩 등 초기화를 완료한 후 보내는 메세지) :  
– `lws_write()` 혹은 `lws_write_text()` 함수를 호출해 JSON 페이로드(`app_ready`)를 프레임 단위로 전송합니다.  
**

```
{
  "type": "app_ready",
  "request_id": "<UUID>",
  "instance_id" "<instance id>": 
  "config_path": "<config path>"
  "process_id": <PID>,
  "streams_count": 3,
  "status": "ok",
  "version": "DeepStream-Yolo v7.1",
  "gpu_allocated": [0,1,2],
  "start_time": "2025-07-28T12:00:03+09:00"
}
```
    - `instance_id`: deepstream-app 실행 시 ‘’’APP\_ID’’’ 환경변수로 전달한 instance\_id가  deepstream-app 이 인식하고 있는 instance\_id와 일치하는지 확인용.
    - `config_path`: deepstream-app 실행 시 ‘’’deepstream-app -c \*.txt’’’ 으로 전달한 config\_path가 deepstream-app 이 인식하고 있는 config\_path가 일치하는지 확인용.

    - `streams_count`: deepstream-app 실행 시 -c 옵션으로 전달한 \*.txt 파일에 명시된 설정에 의해 결정된 값

- **(4) FastAPI -> DeepStream (검증 통과 및 실패 응답):**   
**–** `LWS_CALLBACK_CLIENT_RECEIVE` 콜백에서 서버가 보낸 `execute_ack` 메시지를 수신·파싱 후, 옵션 검증 결과를 처리할 수 있습니다.  
**검증 통과 시:**

```
{
  "type": "execute_ack",
  "request_id": "<UUID>",
  "instance_id": "<instance id>",
  "config_verified": true,
  "streams_count_verified": true,
  "status": "confirmed",
  "timestamp": "2025-07-28T12:00:04+09:00"
}
```

**검증 실패 시 (ex. config\_path 검증 실패 시):**  

```
{
  "type": "execute_ack",
  "request_id": "<UUID>",
  "status": "error",
  "config_verified": false,
  "expected_config": "/app/config/deepstream_config.txt",
  "received_config": "/wrong/path.txt",
  "error_code": "CONFIG_MISMATCH",
  "error_message": "Config path does not match the running instance",
  "timestamp": "2025-07-28T12:00:04+09:00"
}
```

<br>

<br>

### 2.3.2. start analysis: 

- **설명:** FastAPI가 **특정 영상 분석을 시작**하도록 DeepStream에 지시하는 단계입니다. 예를 들어 외부 웹 서버로부터 _camera\_id=A인 폴더 영상들을 분석하라_는 요청이 들어오면, FastAPI는 어느 DeepStream 인스턴스의 \*어느 스트림(slot)\*을 사용할지 결정하고 해당 명령을 전송합니다. DeepStream 측에서는 해당 `stream_id`에 대해 **이전에 진행 중인 분석이 없는지**, **모든 상태가 초기화되어 있는지** 확인합니다. (deepstream-app 내부적으로 임의 camera\_id에 대한 분석이 끝난 시점에 **추적기 상태 초기화가** 진행되어야 하고, 새 camera\_id에 대한 분석을 시작할때는 추적기 상태가 초기화되었는지 확인 및 출력 디렉토리 생성 등의 만반의 준비를 해야합니다.**)**  

> if 이전에 진행중인 분석이 없고 바로 사용 가능하다면:  
>    FastAPI에 바로 **분석 시작** 승인이 되었고, 바로 실행 예정이라고 알려줍니다.  
> elif 만약 해당 스트림이 아직 이전 작업을 완료하지 않은 상태라면:  
>    새로 요청받은 camera\_id 를 camera\_id 단위를 관리하는 큐에 추가합니다. (현재 코드는 camera\_id에 속하는 일련의 파일들의 시퀀스에 대한 큐잉(일명, file queue)만 구현되어있는데, 이보다 한 단계 위의 camera\_id 단위의 큐잉(일명, camera queue)도 추가로 구현되어야 합니다. 즉, 하나의 stream\_id에 여러 camera\_id들이 할당될 수 있어야 하고, 이 camera\_id들은 요청받은 순서대로 처리됩니다. )  
> else:  
>   만약 해당하는 stream\_id가 존재하지 않거나, 이슈가 있을 경우 **에러 응답**을 보내 요청을 무시합니다. 

<br>

- **FastAPI -> DeepStream 보낼 메시지 필드:**

```
{
  "type": "start_analysis",
  "request_id": "<UUID>",
  "stream_id": <정수>,
  "camera_id": <정수>,
  "camera_type": <"videostream", "fileset", "file">,
  "camera_path": "<분석 대상 폴더/파일 경로>",
  "camera_name": "<대상 이름>",
  "output_dir": "<결과 출력 폴더 경로>",
  "init_file": {
      "file_type": <"videostream", "file">,
      "file_id": <정수>,
      "file_path": "<파일 경로>",
      "file_name": "<파일 이름>",
      "output_path": "이 영상 파일에 대한 track output 파일의 경로"
  },
}
```

주요 필드 설명: `stream_id`는 사용하려는 스트림 슬롯, `camera_id`는 해당 작업의 고유 ID, `camera_type`은 폴더 vs 파일 단위(추후 rtsp, http 등 video stream도 추가 예정), `camera_path`와 `camera_name`은 분석 대상 위치 정보, `output_dir`는 DeepStream이 결과를 저장할 경로입니다. 이 메시지를 받으면 DeepStream은 해당 정보를 토대로 **새로운 파이프라인 실행 준비**를 하고, 
- **DeepStream -> FastAPI 보내는 메시지 필드:**  
DeepStream은 `start_analysis` 메시지에 대해 **아래와 같은 응답**을 FastAPI로 전송합니다.
    - 성공 시:

```
{
  "type": "analysis_started",
  "request_id": "<UUID>",
  "stream_id": X,
  "camera_id": Y,
  "status": "ok",
  "message": "Stream X for camera Y analysis started"
}
```

이 응답은 **해당 스트림에서 분석을 받을 준비 완료**를 의미합니다. DeepStream은 내부적으로 `camera_id=Y`에 대한 트래커 등의 상태를 초기화하고, 이제 **파일을 받아 처리할 준비**를 마칩니다.
    - 실패 시:

```
{
  "type": "analysis_started",
  "request_id": "<UUID>",
  "stream_id": X,
  "camera_id": Y,
  "status": "error",
  "error_reason": "<사유 설명>"
}
```

예를 들어 `error_reason`에는 구체적 사유를 담습니다. FastAPI는 이 오류를 받아서 **외부 요청자에게 오류 응답**을 주거나, 필요하면 다른 스트림/인스턴스로 재시도할 수 있습니다.

### 2.3.3. push file:

**설명:** `start_analysis` 단계에서 DeepStream이 준비 완료되었다고 응답하면, FastAPI는 실제 **분석할 영상 파일들 경로 목록**을 DeepStream에 전달합니다. 폴더 단위 분석의 경우 해당 폴더 내 다수의 파일 경로를 순차 재생해야 하므로, FastAPI는 일정 단위로 파일 경로 묶음을 보내거나 한 번에 모두 보낼 수 있습니다. 이때 **특별한 EOS(End Of Stream) 표시**를 사용하여 해당 카메라 시리즈의 끝을 알립니다. DeepStream은 수신한 파일 경로들을 **내부 큐**에 저장해 두고 차례로 영상을 처리하며, EOS 표시를 만나면 **해당 camera\_id에 대한 모든 파일 처리가 끝났음**을 인지하여 객체 추적 등 상태를 모두 초기화합니다. 처리 도중에도 DeepStream은 필요한 경우 진행 상황이나 에러를 FastAPI에 보낼 수 있지만, 여기서는 주요 흐름 위주로 설명합니다.

- **FastAPI -> DeepStream 보낼 메시지 필드:**

```
{
  "type": "push_file",
  "request_id": "<UUID>",
  "stream_id": X,
  "camera_id": Y,
  "files_count": <files에 포함된 파일의 개수. eos 객체는 개수에서 제외됨.>,
  "files": [
    {
      "file_type": "file",
      "file_id": <정수>,
      "file_path": "<파일1 경로>",
      "file_name": "<파일1 이름>",
      "output_path": "이 영상 파일에 대한 track output 파일의 경로"
    },
    {
      "file_type": "file",
      "file_id": <정수>,
      "file_path": "<파일2 경로>",
      "file_name": "<파일2 이름>",
      "output_path": "이 영상 파일에 대한 track output 파일의 경로"
    },
    ...,
    {
      "file_type": "eos"
    }
  ],
}
```

설명: `files` 배열에 한 번에 여러 파일을 보낼 수 있으며, 각 항목에 `file_type`을 넣어 구분합니다. `file_type: "file"`에는 실제 파일 경로와 이름을 주고, `file_type: "eos"`는 **해당 시퀀스의 끝**임을 나타내는 특수 아이템입니다. `files_count`는 보내는 파일 개수(N)를 명시적으로 적어 줄 수도 있습니다 (혹은 배열 길이로 판단 가능하므로 선택사항). `output_path`은 향후 필요 시 각 파일별 결과를 식별하기 위한 이름인데, 현재는 **예약 필드**로서 일단 전달만 하고 DeepStream 측에서는 사용하지 않을 수 있습니다. FastAPI는 이 메시지를 여러 번에 걸쳐 보낼 수도 있고, 작은 폴더의 경우 한 번에 파일 리스트 전체를 보낼 수도 있습니다.
- **DeepStream -> FastAPI 보내는 메시지 필드:**  
DeepStream은 파일 경로들을 수신하면 즉시 응답을 보내기보다는, **처리 진행 중 또는 완료 후**에 상황에 따라 메시지를 보냅니다:
    - 만약 `push_file` 메시지의 `stream_id`나 `camera_id`가 현재 DeepStream이 인지하고 있는 **진행 중 세션과 불일치**할 경우 (예: FastAPI 쪽 버그로 잘못된 ID를 보냈거나, 이미 해당 스트림에 다른 camera 작업이 진행 중인데 잘못된 `camera_id`로 보낸 경우 등), DeepStream은 즉각 에러 응답을 보냅니다. 예:

```
{
  "type": "push_ack",
  "request_id": "<UUID>",
  "stream_id": X,
  "camera_id": Y,
  "status": "error",
  "error_reason": "Invalid stream_id or camera_id for current session"
}
```

FastAPI는 이를 받아 잘못된 요청을 로그로 남기거나 오류 처리합니다. 
    - 요청이 정상 수락되었다면, DeepStream은 **영상을 처리**하기 시작합니다. 파일의 처리의 시작과 끝 시점에 FastAPI에 알려야 합니다. 예를 들어 파일을 읽기 시작할 때

```
{ 
  "type": "processing_started", 
  "request_id": "<UUID>",
  "stream_id": X,
  "camera_id": Y,
  "file_id": Z,
  "current_file": "<파일명>" 
}
```

같은 메시지로 진행 상황을 알릴 수 있고, 특정 파일 처리 완료 후에는

```
{ 
  "type": "file_done",
  "request_id": "<UUID>",
  "stream_id": X,
  "camera_id": Y,
  "file_id": Z,
  "processed_file": "<파일명>" 
}
```

식으로 보낼 수도 있습니다. (이 부분은 시스템 요구사항에 따라 추가 설계 가능합니다.)
    - 모든 파일을 처리하고 `file_type: "eos"`에 도달하면, DeepStream은 해당 스트림의 작업을 **완전히 마무리**합니다. 이때 **객체 추적 상태 등 내부 상태를 리셋**하여 다음 작업을 받을 준비를 하고, FastAPI에 최종 완료 메시지를 전송합니다: 

```
{
  "type": "analysis_complete",
  "request_id": "<UUID>",
  "stream_id": X,
  "camera_id": Y,
  "status": "done",
  "processed_count: <처리한 파일의 총 개수. eos 객체는 개수에서 제외됨.>,
  "message": "Analysis for camera Y complete. Stream X is free."
}
```

FastAPI는 이 메시지를 받으면 결과 파일들을 `output_dir`에서 수집하거나 후처리하고, 외부 요청자에게 **완료 응답**을 보낼 수 있습니다. 또한 Stream X가 다시 사용 가능해졌음을 알고 새로운 대기 작업을 할당할 수 있습니다.

<br>

### 2.3.4. interrupt analysis:

**설명:** 특정 카메라(`camera_id`)에 대한 분석을 도중에 **중단**해야 할 때 사용하는 메시지입니다. 이는 사용자의 취소 요청이 들어오거나, 시스템상 해당 작업을 강제 종료해야 할 경우에 발생합니다. FastAPI는 대상이 되는 `stream_id`와 `camera_id`를 지정하여 DeepStream에 **중단 명령**을 보냅니다. DeepStream은 최대한 신속하게 해당 스트림에서 진행 중이던 파일 처리들을 중지하고, 이미 큐에 쌓인 파일들도 **버립니다.** 그리고 해당 스트림과 camera에 대한 \*\*모든 상태(예: multi object tracker 메모리 등)\*\*를 초기화합니다. 이후 FastAPI에 중단 완료를 알리고, 새로운 요청을 받을 수 있는 상태로 돌아갑니다.

- **FastAPI -> DeepStream 보낼 메시지 필드:**

```
{
  "type": "interrupt_analysis",
  "request_id": "<UUID>",
  "stream_id": X,
  "camera_id": Y,
  "reason": "user_cancelled"
}
```

어떤 이유로 중단하는지 등의 부가 정보는 `reason` 필드에 명시됩니다. (예: `"reason": "user_cancelled"` 등).
- **DeepStream -> FastAPI 보내는 메시지 필드:**  
DeepStream은 `interrupt` 요청을 받으면 상황에 따라 두 가지 응답을 합니다.
    - 정상 중단 수행:

```
{
  "type": "analysis_interrupted",
  "request_id": "<UUID>",
  "stream_id": X,
  "camera_id": Y,
  "status": "ok",
  "message": "Analysis on stream X (camera Y) interrupted and reset."
}
```

이때 DeepStream은 해당 스트림에 대한 작업을 즉시 중지했고 리소스 정리가 완료되었음을 의미합니다. FastAPI는 이 응답을 받으면 해당 작업이 취소되었음을 외부에 알리고(필요시) 스트림 X를 다른 작업에 할당 가능하도록 표시합니다.
    - 에러 응답:

```
{
  "type": "analysis_interrupted",
  "request_id": "<UUID>",
  "stream_id": X,
  "camera_id": Y,
  "status": "error",
  "error_reason": "<사유>"
}
```

예를 들어 잘못된 ID로 중단 요청을 보낸 경우 (_"stream X has no active analysis"_ 또는 _"camera Y not found on any stream"_ 등). 이 경우 FastAPI측 로직에 문제가 있는 것이므로, 로그를 남기고 무시하거나 재동기화가 필요합니다.

중단 명령 처리가 완료되면 DeepStream은 내부적으로 해당 스트림을 **깨끗한 초기 상태로 리셋**하므로, 이후 곧바로 **다른 camera\_id의 분석을 시작**할 수 있습니다 (FastAPI가 추가 명령을 보내줄 수 있음).

<br>

### 2.3.5. terminate app:

**설명:** FastAPI가 DeepStream 애플리케이션 자체를 종료시켜야 할 때 사용합니다. 시스템 종료나 업데이트, 혹은 더 이상 DeepStream이 필요 없을 때 프로세스를 내리는 용도입니다. FastAPI는 termination 명령을 보내고, DeepStream은 **모든 작업을 안전하게 중지 및 리소스 해제** 한 뒤 프로세스를 종료합니다.

- **FastAPI -> DeepStream 보낼 메시지 필드:**

```
{ 
  "type": "terminate_app"
  "request_id": "<UUID>",
}
```

추가로 특정 인스턴스나 컨테이너에 지시하는 것이라면 식별자가 필요할 수 있으나, WebSocket 연결 자체가 이미 해당 DeepStream 인스턴스와의 채널이므로 별도 정보는 없거나, 혹시 여러 종료 모드가 있다면 `mode: "graceful"` 같은 옵션을 붙일 수 있습니다.
- **DeepStream -> FastAPI 보내는 메시지 필드:**  
DeepStream은 **종료 절차 완료 직전**에 다음과 같은 메시지를 보낼 수 있습니다:

```
{
  "type": "app_terminated",
  "request_id": "<UUID>",
  "status": "ok",
  "message": "DeepStream process exiting."
}
```

이 메시지를 보낸 후 WebSocket 연결이 끊기면, FastAPI는 해당 프로세스가 종료되었음을 알고 필요 시 **프로세스 객체 정리**를 합니다. (또는 `ps` 확인으로 이미 종료 파악 가능하지만, 이벤트를 주면 더욱 명확)

<br>

### 2.3.6. metrics:

예를 들어 메시지가 `"query_metrics"` 등의 형태라면, **DeepStream 프로세스의 상태 정보**를 수집하여 응답합니다. 주요 지표는 다음을 포함합니다:

- **CPU 사용률:** 현재 DeepStream 프로세스의 CPU 사용량(%)을 계산합니다. 리눅스에서는 `/proc/[pid]/stat`에서 utime, stime 등을 읽거나 `getrusage(RUSAGE_SELF, ...)`로 사용자/커널 모드 사용 시간을 구한 뒤, 일정 간격 동안의 변화를 계산하여 CPU 사용률을 산출할 수 있습니다. 간단한 구현으로는, WebSocket 요청을 받을 때 이전에 기록해둔 총 CPU 시간과 현재 시점의 총 CPU 시간을 비교하여 퍼센트를 계산하거나, 또는 `/proc/stat`의 전체 CPU 시간 대비 프로세스 시간을 비교하는 방법이 있습니다. (수백 밀리초 슬립 후 두 시점의 차이를 계산하는 방식 등)
- **메모리 사용량 (RAM):** `/proc/[pid]/status` 파일을 파싱하여 **VmRSS** (Resident Set Size) 값을 얻으면 현재 프로세스가 소비하는 실제 물리 메모리량을 알 수 있습니다. 또는 `sysconf(_SC_PAGESIZE)`와 `getrss()` 등을 이용하는 방법도 있습니다. 여기서는 `/proc/self/status`에서 문자열 검색으로 “VmRSS” 값을 추출하는 방법이 비교적 간단합니다. 결과는 KB 단위이므로 MB로 변환해 제공합니다.
- **GPU 사용률:** NVIDIA GPU 사용률과 메모리 사용량을 얻기 위해 \*\*NVML (NVIDIA Management Library)\*\*을 활용합니다. NVML은 NVIDIA 드라이버에 포함된 C API로, GPU 상태를 프로그램matically 조회할 수 있습니다.
    - NVML 사용을 위해서는 먼저 `nvmlInit()`으로 라이브러리를 초기화하고, `nvmlDeviceGetHandleByIndex(0, &device)` 등을 호출하여 GPU 장치 핸들을 얻습니다 (여기서는 GPU 0번 사용 가정).
    - `nvmlDeviceGetUtilizationRates(device, &utilization)` 함수를 호출하면 `utilization.gpu` 필드에 GPU 코어 사용률(%)이, `utilization.memory` 필드에 메모리 컨트롤러 사용률(%)이 채워집니다.
    - GPU 메모리 사용량은 `nvmlDeviceGetMemoryInfo(device, &memoryInfo)`를 통해 얻을 수 있습니다. `memoryInfo.used`와 `memoryInfo.total`을 받아 사용 중 메모리(MB)와 전체 메모리 대비 퍼센트를 계산합니다.
    - NVML 호출을 마친 뒤 `nvmlShutdown()`으로 정리합니다.
    - **주의:** NVML 사용 시, 프로젝트 빌드 설정에 `-lnvidia-ml`을 추가해야 하며 NVIDIA 드라이버가 설치되어 있어야 합니다. 만약 NVML을 사용할 수 없는 환경이라면, `nvidia-smi` 명령을 파이프 실행하여 출력 파싱하는 방법도 있지만, 이는 비용이 크고 권장되지 않습니다. 이번 구현에서는 NVML을 사용하는 것으로 가정합니다.

- **기타 지표:** 필요에 따라 프로세스 시작 시간, 현재 처리 중인 프레임 수, 누적 처리된 프레임 등도 포함할 수 있지만, 요구된 바는 CPU/메모리/GPU 자원 사용량입니다.
- **응답 생성:** 위에서 수집한 값을 토대로 JSON 문자열 또는 key-value 형태의 문자열을 생성합니다. 예를 들어:

```
{
  "cpu_percent": 23.5,
  "ram_mb": 512.3,
  "gpu_percent": 40.1,
  "vram_mb": 1024.0
}
```

와 같이 만들거나, 단순 콜론 구분 문자열 `"CPU:23.5%, RAM:512MB, GPU:40%, VRAM:1024MB"` 형태도 가능합니다. **JSON 형식**을 권장하며, FastAPI 쪽 클라이언트에서 parsing하기 쉽게 키 이름을 명시합니다.
- **메시지 전송:** 준비된 메트릭 정보를 FastAPI에게 전송합니다. libwebsockets에서는 `lws_write(wsi, buf, len, LWS_WRITE_TEXT)`로 텍스트 프레임을 전송할 수 있는데, 콜백 함수의 컨텍스트 내에서 바로 보내는 대신 `lws_callback_on_writable(wsi)`를 호출하여 안전한 시점에 쓰기가 이루어지도록 하는 것을 권장합니다. 응답이 준비되면 곧바로 전송하여 FastAPI 측이 실시간으로 데이터를 수신하도록 합니다.

<br>

### 2.3.7. analysis status:

- 설명: FastAPI가 deepstream-app 에게 모든 stream\_id 에 대한 분석 진행 상황을 질의하는 통신. 예를 들어 다음과 같은 시나리오가 있을 수 있습니다.
    - 각 stream\_id 별 status:
        - 각 stream\_id 에는 어떤 camera\_id가 분석 진행중이며, 어떤 camera\_id들이 camera queue에서 대기중인지 등등…
    - 각 camera\_id 별 status:
        - camera\_id 단위별 상태: 해당 camera\_id 가 분석중인지, 대기중인지
        - camera\_id 에 속한 file\_id들의 상태:
            - 어떤 file\_id가 분석 중이고, 어떤 몇 개의 file\_id들이 분석 완료되었고, 어떤 몇 개 file\_id들이  file queue에서 대기중인지 등등…

- 전체 조회
    - Request(FastAPI → deepstream-app)  
**모든** stream 및 camera에 대한 상태를 한 번에 요청  

```
{
  "type": "query_analysis_status",  // 모든 stream·camera 상태 조회
  "request_id": "<UUID>"              // 응답 매칭용 고유 ID
}
```
    - Response(deepstream-app → FastAPI)  
`streams` 배열 내에 각 `stream_id`별 요약 · 카메라·파일 상태 포함  

```
{ 
  "type": "analysis_status",        // 상태 응답임을 명시
  "request_id": "<UUID>",            // 요청 시전된 ID와 동일
  "timestamp": "<ISO8601>",          // 응답 생성 시각
  "streams": [
    {
      "stream_id": <int>,
      "status": "<running|idle|error>",
      "cameras": [
        {
          "camera_id": <int>,
          "status": "<running|queued>",
          "files": {
            "processing": [
              { "file_id": <int>, "file_name": "<string>", "progress_pct": <float> }
            ],
            "completed_count": <int>,
            "queued_count": <int>,
            "queued": [
              { "file_id": <int>, "file_name": "<string>" }, …
            ]
          }
        }, …
      ]
    }, …
  ]
}
```

  

- stream\_id 별 조회
    - Request(FastAPI → deepstream-app)  
`stream_id` 지정 시 해당 슬롯만 응답. 나머지 필드는 전체 조회와 동일.  

```
{
  "type": "query_analysis_status",  
  "request_id": "<UUID>",
  "stream_id": <int>                  // 특정 스트림 슬롯만 조회
}
```

  
    - Response(deepstream-app → FastAPI)  
`stream` 단일 오브젝트로 반환. `cameras` 및 그 안의 `files` 정보 포함.  

```
{
  "type": "analysis_status",
  "request_id": "<UUID>",
  "timestamp": "<ISO8601>",
  "stream": {
    "stream_id": <int>,
    "status": "<running|idle|error>",
    "cameras": [
      {
        "camera_id": <int>,
        "status": "<running|queued>",
        "files": {
          "processing": [ … ],
          "completed_count": <int>,
          "queued_count": <int>,
          "queued": [ … ]
        }
      }, …
    ]
  }
}
```

<br>

- camera\_id별 조회
    - Request(FastAPI → deepstream-app)  
`stream_id`와 `camera_id` 모두 지정. (stream\_id와 camera\_id가 일치하지 않을 경우 에러 반환 필요)

```
{
  "type": "query_analysis_status",
  "request_id": "<UUID>",
  "stream_id": <int>,                 // 해당 카메라가 속한 스트림
  "camera_id": <int>                  // 특정 카메라만 조회
}
```

<br>
    - Response(deepstream-app → FastAPI)  
최종적으로 **단일 카메라**의 상태·파일 큐 정보를 반환. `stream_id`는 바깥 레벨에 두어 어떤 스트림 소속인지 명확화.

```
{
  "type": "analysis_status",
  "request_id": "<UUID>",
  "timestamp": "<ISO8601>",
  "stream_id": <int>,
  "camera": {
    "camera_id": <int>,
    "status": "<running|queued>",
    "files": {
      "processing": [ { "file_id": <int>, "file_name": "<string>", "progress_pct": <float> } ],
      "completed_count": <int>,
      "queued_count": <int>,
      "queued": [ { "file_id": <int>, "file_name": "<string>" }, … ]
    }
  }
}
```

<br>

<br>

### 2.3.8. 여러 웹소켓 소통 주제에서, 공통적으로 사용되는 핵심 속성에 대한 상세 설명

- **`path`** 및 **`name`**: 분석 대상 \*\*폴더 또는 파일의 경로(`path`)\*\*와 이름(`name`)입니다. FastAPI는 DeepStream 컨테이너 내부에서 바로 접근 가능한 경로로 변환하여 전달합니다. 예를 들어 호스트 경로를 컨테이너 마운트 경로로 바꿔서 `path`를 보내며, `name`은 주로 **로그 기록이나 디버깅 편의**를 위해 사용합니다. (`path`만으로도 처리는 가능하지만, 사람이 읽기 쉬운 이름을 함께 전달)
- **`type`**: 분석 단위를 나타내는 플래그로, 폴더 단위 연속 분석인지 개별 파일 분석인지를 구분합니다. 예를 들어 `type: folder` 또는 `file` (혹은 0/1 등 코드)로 구분하여, DeepStream이 폴더 단위일 경우 해당 폴더 내 **여러 파일의 연속 스트림**으로 처리하고 추적 연속성을 유지하도록 하고, 파일 단위일 경우 **싱글 비디오 처리를 즉시 완료**하도록 로직을 달리할 수 있습니다.
- **`stream_id`**:deepstream-app **스트림 슬롯 ID**입니다. 0부터 시작하는 정수로, 하나의 deepstream-app 프로세스 내 **개별 입력 파이프라인을 식별**합니다. FastAPI는 분석 요청 시 가용한 `stream_id`를 선택하여 해당 deepstream-app으로 보내며, deepstream-app은 이 ID별로 독립된 분석 상태(예: 객체 추적 상태 등)를 관리합니다.
- **`camera_id`**: **분석 대상 고유 ID**로, 보통 하나의 카메라 또는 파일 시퀀스를 대표합니다. FastAPI는 이 값을 **파일시스템 inode** 값으로 설정하며, **폴더(카메라) 경로와 1:1 대응**되도록 관리합니다. DeepStream 측에서는 이 값을 그대로 카메라/비디오 식별자로 사용하여, 동일 `camera_id`로 들어오는 연속된 영상들이 **같은 대상**임을 인지합니다. (파일 단위 분석인 경우 해당 파일의 inode를 `camera_id`로 사용합니다.) 이 접근 방식 덕분에, 만약 분석 중 폴더나 파일 이름이 바뀌어도 inode(`camera_id`)가 다르면 **다른 대상으로 인식**되어 혼동이 없고, FastAPI는 필요한 경우 해당 분석을 중단/재시작할 수 있습니다. 이 `camera_id`는 추후에 rtsp 등 네트워크 스트리밍 영상의 identifier가 되기도 할 것입니다.
- **`file_id`** 비디오 파일의 id.
    - file\_id 또한 inode값을 그대로 사용함.
    - 폴더 단위 분석일 경우 하나의 camera\_id에 여러 file\_id가 포함됨. (일반적으로는 해당 폴더 내의 자식 파일들인데, 이는 전적으로 FastAPI에서 결정하므로 deepstream-app에서는 신경쓸 필요 없음)
    - 파일 단위 분석일 경우 camera\_id와 file\_id가 동일한 값임.

<br>