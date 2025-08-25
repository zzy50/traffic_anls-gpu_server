## 📋 클라이언트 개발자를 위한 변경사항 대응 가이드

---

### 🚨 **중요 변경사항: WebSocket Graceful Shutdown 지원**

서버에 WebSocket graceful shutdown 기능이 추가되어, 클라이언트에서 다음 사항들을 반드시 구현해야 합니다.

---

### 1. **WebSocket Close Code 처리**

**새로 처리해야 할 Close Codes:**
```javascript
websocket.onclose = function(event) {
    switch(event.code) {
        case 1001: // Going Away
            console.log("서버가 정상적으로 종료되고 있습니다:", event.reason);
            // 즉시 재연결 시도하지 말고, 서버 재시작을 기다림
            scheduleReconnect(5000); // 5초 후 재연결 시도
            break;
            
        case 1013: // Try Again Later  
            console.log("서버가 종료 중입니다. 잠시 후 재시도:", event.reason);
            // 백오프 전략으로 재연결 (예: 10초 후)
            scheduleReconnect(10000);
            break;
            
        default:
            // 기존 로직 유지
            handleNormalDisconnection(event);
    }
};
```

---

### 2. **DeepStream 클라이언트: TerminateAppMessage 처리**

**새로운 메시지 타입 처리 (DeepStream 앱만 해당):**
```python
def handle_message(self, message_data):
    message_type = message_data.get("type")
    
    if message_type == "terminate_app":
        # 서버가 종료를 요청함
        self.logger.info("서버로부터 종료 요청 수신")
        
        # 1. 현재 작업 정리
        await self.cleanup_current_tasks()
        
        # 2. 종료 확인 응답 전송
        response = {
            "type": "app_terminated",
            "request_id": message_data["request_id"],
            "status": "OK",
            "message": "Application terminated gracefully"
        }
        await self.send_message(response)
        
        # 3. 애플리케이션 종료
        await self.graceful_shutdown()
        return True  # 메시지 처리 완료 및 종료 신호
```

---

### 3. **Health Check API 변경 대응**

**새로운 응답 형식:**
```javascript
// 기존
{
    "status": "ok",
    "connected_instances": [...],
    // ...
}

// 변경된 형식
{
    "status": "ok" | "shutting_down",  // 새로운 상태 추가
    "connected_instances": [...],
    "websocket": {                     // 새로운 섹션
        "total_connections": 5,
        "authenticated_connections": 3,
        "unauthenticated_connections": 2,
        "is_shutting_down": false
    },
    // ...
}
```

**처리 예시:**
```javascript
async function checkServerHealth() {
    const response = await fetch('/deepstream/health');
    const health = await response.json();
    
    if (health.status === "shutting_down") {
        console.warn("서버가 종료 중입니다. 새로운 작업을 시작하지 마세요.");
        // UI에 경고 표시, 새로운 요청 차단 등
        showServerShuttingDownWarning();
        return false;
    }
    
    return health.status === "ok";
}
```

---

### 4. **재연결 로직 개선**

**권장 재연결 전략:**
```javascript
class SmartReconnector {
    constructor() {
        this.maxRetries = 10;
        this.baseDelay = 1000; // 1초
        this.maxDelay = 30000;  // 30초
        this.retryCount = 0;
    }
    
    scheduleReconnect(reason = "unknown") {
        if (this.retryCount >= this.maxRetries) {
            console.error("최대 재연결 시도 횟수 초과");
            return;
        }
        
        let delay;
        if (reason === "server_shutting_down") {
            // 서버 종료 시에는 더 긴 대기 시간
            delay = Math.min(10000 + (this.retryCount * 5000), this.maxDelay);
        } else {
            // 일반적인 지수 백오프
            delay = Math.min(this.baseDelay * Math.pow(2, this.retryCount), this.maxDelay);
        }
        
        console.log(`${delay}ms 후 재연결 시도 (${this.retryCount + 1}/${this.maxRetries})`);
        
        setTimeout(() => {
            this.attemptReconnect();
        }, delay);
    }
    
    async attemptReconnect() {
        // 먼저 서버 상태 확인
        const isHealthy = await this.checkServerHealth();
        if (!isHealthy) {
            this.retryCount++;
            this.scheduleReconnect("server_not_ready");
            return;
        }
        
        // WebSocket 재연결 시도
        try {
            await this.connectWebSocket();
            this.retryCount = 0; // 성공 시 카운터 리셋
            console.log("재연결 성공");
        } catch (error) {
            this.retryCount++;
            this.scheduleReconnect("connection_failed");
        }
    }
}
```

---

### 5. **테스트 체크리스트**

다음 시나리오를 테스트하여 클라이언트가 올바르게 동작하는지 확인하세요:

- [ ] **서버 정상 종료 시**: Close code 1001을 받고 적절히 대기 후 재연결
- [ ] **서버 종료 중 연결 시도**: Close code 1013을 받고 백오프 후 재시도  
- [ ] **DeepStream 클라이언트**: `terminate_app` 메시지 수신 시 graceful shutdown
- [ ] **Health Check**: `shutting_down` 상태 감지 및 적절한 대응
- [ ] **재연결 로직**: 다양한 종료 사유별 적절한 재연결 간격

---

### 🔧 **DeepStream C 클라이언트 특별 고려사항**

**1. 메모리 관리 주의사항:**
```c
// WebSocket 클라이언트 정리 시 반드시 모든 리소스 해제
void cleanup_websocket_client() {
  // 1. Health check 타이머 정리
  if (client->health_check_timer_id > 0) {
    g_source_remove(client->health_check_timer_id);
    client->health_check_timer_id = 0;
  }
  
  // 2. Close reason 메모리 해제
  g_free(client->last_close_reason);
  client->last_close_reason = NULL;
  
  // 3. Health status 정리
  server_health_status_free(&client->last_health_status);
}
```

**2. GStreamer 파이프라인과의 연동:**
```c
// terminate_app 수신 시 파이프라인 안전 종료
gboolean handle_terminate_app_gracefully(AppCtx *appCtx) {
  DS_LOG_INFO("Starting graceful pipeline shutdown...");
  
  // 1. 모든 스트림을 PAUSED 상태로 전환
  for (guint i = 0; i < appCtx->config.num_source_sub_bins; i++) {
    if (appCtx->pipeline.instance_bins[i].bin) {
      GstStateChangeReturn ret = gst_element_set_state(
        appCtx->pipeline.instance_bins[i].bin, GST_STATE_PAUSED);
      
      if (ret == GST_STATE_CHANGE_FAILURE) {
        DS_LOG_WARN("Failed to pause stream %d", i);
      }
    }
  }
  
  // 2. 메인 파이프라인을 NULL 상태로 전환
  if (appCtx->pipeline.pipeline) {
    gst_element_set_state(appCtx->pipeline.pipeline, GST_STATE_NULL);
  }
  
  // 3. 모든 pending 메시지 처리 완료 대기
  gst_bus_timed_pop_filtered(appCtx->pipeline.bus, 
    GST_CLOCK_TIME_NONE, GST_MESSAGE_STATE_CHANGED);
  
  return TRUE;
}
```

**3. Configuration 파일 설정 예시:**
```ini
# websocket_config.txt에 추가할 설정
[websocket]
# ... 기존 설정 ...

# Health check 관련 설정
health_check_interval_sec=30
health_check_timeout_sec=5
health_check_enabled=true

# Graceful shutdown 설정  
graceful_shutdown_timeout_sec=10
pipeline_stop_timeout_sec=5

# 재연결 전략 설정
exponential_backoff_enabled=true
max_reconnect_delay_sec=60
server_shutdown_retry_delay_sec=10
```

**4. 스레드 안전성 고려사항:**
```c
// WebSocket 메시지 전송 시 스레드 안전성 보장
gboolean thread_safe_send_message(WebSocketClient *client, JsonObject *json_obj) {
  g_mutex_lock(&client->send_mutex);
  
  // 서버 상태 확인
  if (should_block_new_requests(client)) {
    g_mutex_unlock(&client->send_mutex);
    DS_LOG_WARN("Message send blocked - server not ready");
    return FALSE;
  }
  
  gboolean success = websocket_client_send_json(client, json_obj);
  g_mutex_unlock(&client->send_mutex);
  
  return success;
}
```

**5. 로깅 및 디버깅:**
```c
// 개발 중 디버깅을 위한 상세 로깅
void log_websocket_state(WebSocketClient *client) {
  DS_LOG_INFO("=== WebSocket State ===");
  DS_LOG_INFO("State: %d", client->state);
  DS_LOG_INFO("Reconnect attempts: %d", client->reconnect_attempts);
  DS_LOG_INFO("Last close code: %d (%s)", 
              client->last_close_code, 
              websocket_close_code_to_string(client->last_close_code));
  DS_LOG_INFO("Server shutting down: %s", 
              client->server_shutting_down ? "true" : "false");
  DS_LOG_INFO("Last health status: %s", 
              client->last_health_status.status);
  DS_LOG_INFO("======================");
}
```

---

### 💡 **구현 우선순위**

1. **즉시 구현 필요**: WebSocket close code 처리 (1001, 1013)
2. **DeepStream 앱**: `terminate_app` 메시지 핸들러 추가  
3. **선택적 개선**: Health check 모니터링, 재연결 로직 개선
4. **추가 권장**: GStreamer 파이프라인 안전 종료, 메모리 관리 강화

이 변경사항들을 구현하면 서버의 graceful shutdown과 완벽하게 연동되어 안정적인 서비스를 제공할 수 있습니다.

---

## 🛠️ **서버 개발자를 위한 필수 구현 가이드**

> **중요**: 클라이언트 개선에 따라 서버에서 반드시 구현해야 할 기능들입니다.

---

### 1. **Health Check API 엔드포인트 구현**

**필수 구현**: `GET /deepstream/health`

```python
@app.get("/deepstream/health")
async def get_health_status():
    """DeepStream 클라이언트가 재연결 전 호출하는 Health Check API"""
    
    # 서버 종료 상태 확인
    is_shutting_down = check_shutdown_status()
    
    health_data = {
        "status": "shutting_down" if is_shutting_down else "ok",
        "timestamp": datetime.utcnow().isoformat(),
        "connected_instances": get_connected_instances(),
        "websocket": {
            "total_connections": websocket_manager.get_total_connections(),
            "authenticated_connections": websocket_manager.get_authenticated_count(),
            "unauthenticated_connections": websocket_manager.get_unauthenticated_count(),
            "is_shutting_down": is_shutting_down
        },
        "system": {
            "cpu_usage": get_cpu_usage(),
            "memory_usage": get_memory_usage(),
            "uptime": get_uptime()
        }
    }
    
    # 종료 중일 때는 503 상태 코드 반환 (선택사항)
    status_code = 503 if is_shutting_down else 200
    
    return JSONResponse(content=health_data, status_code=status_code)
```

**응답 형식 (필수):**
```json
{
  "status": "ok",  // 또는 "shutting_down"
  "websocket": {
    "total_connections": 5,
    "authenticated_connections": 3,
    "unauthenticated_connections": 2,
    "is_shutting_down": false  // 필수 필드
  }
}
```

---

### 2. **WebSocket Close Code 전송**

**Graceful Shutdown 시 적절한 Close Code 전송:**

```python
async def graceful_shutdown_websockets():
    """서버 종료 시 WebSocket 연결들을 gracefully 종료"""
    
    # 1. 모든 클라이언트에게 종료 알림
    for websocket in active_connections:
        try:
            # Close code 1001 (Going Away) 전송
            await websocket.close(code=1001, reason="Server shutting down gracefully")
        except Exception as e:
            logger.warning(f"Failed to close websocket gracefully: {e}")
    
    # 2. 잠시 대기 (클라이언트 처리 시간 확보)
    await asyncio.sleep(2)

async def temporary_unavailable_close():
    """일시적 서버 불가 시 (유지보수, 재시작 등)"""
    
    for websocket in active_connections:
        try:
            # Close code 1013 (Try Again Later) 전송
            await websocket.close(code=1013, reason="Server temporarily unavailable")
        except Exception as e:
            logger.warning(f"Failed to close websocket: {e}")
```

---

### 3. **TerminateApp 메시지 응답 처리**

**클라이언트 응답 형식 확인:**

```python
async def handle_app_terminated_response(websocket, message_data):
    """클라이언트로부터 받은 app_terminated 응답 처리"""
    
    # 클라이언트가 전송하는 정확한 형식:
    # {
    #   "type": "app_terminated",
    #   "request_id": "original_request_id", 
    #   "status": "OK",  // 대문자 주의!
    #   "message": "Application terminated gracefully"
    # }
    
    if message_data.get("type") == "app_terminated":
        request_id = message_data.get("request_id")
        status = message_data.get("status")
        
        if status == "OK":  # 대문자 확인
            logger.info(f"DeepStream client {websocket.client_id} terminated gracefully")
            # 클라이언트 정리 작업
            await cleanup_client_resources(websocket.client_id)
            # 연결 해제
            await websocket.close(code=1000, reason="Client terminated")
        else:
            logger.warning(f"Client termination failed: {message_data}")
    
    return True
```

---

### 4. **종료 시퀀스 개선**

**권장 서버 종료 순서:**

```python
async def improved_graceful_shutdown():
    """개선된 graceful shutdown 시퀀스"""
    
    logger.info("Starting graceful shutdown sequence...")
    
    # 1. Health Check 상태를 "shutting_down"으로 변경
    set_shutdown_status(True)
    
    # 2. 새로운 WebSocket 연결 차단
    block_new_connections(True)
    
    # 3. 기존 클라이언트들에게 terminate_app 메시지 전송
    active_clients = list(websocket_manager.get_active_clients())
    
    for client in active_clients:
        try:
            terminate_message = {
                "type": "terminate_app",
                "request_id": generate_uuid(),
                "reason": "Server shutting down"
            }
            await client.send_json(terminate_message)
        except Exception as e:
            logger.warning(f"Failed to send terminate message to {client.client_id}: {e}")
    
    # 4. 클라이언트 응답 대기 (최대 10초)
    await wait_for_client_terminations(timeout=10)
    
    # 5. 남은 연결들 강제 종료 (Close code 1001)
    remaining_clients = websocket_manager.get_active_clients()
    for client in remaining_clients:
        try:
            await client.close(code=1001, reason="Server shutdown timeout")
        except:
            pass
    
    # 6. 서버 리소스 정리
    await cleanup_server_resources()
    
    logger.info("Graceful shutdown completed")
```

---

### 5. **클라이언트 재연결 지원**

**재연결 시 클라이언트 검증:**

```python
async def handle_client_reconnection(websocket, client_data):
    """재연결 클라이언트 처리"""
    
    # 클라이언트가 보내는 app_ready 메시지 형식:
    # {
    #   "type": "app_ready",
    #   "instance_id": "unique_client_id",
    #   "reconnection": true,  // 재연결 플래그
    #   "last_close_code": 1001,  // 마지막 종료 코드
    #   "config": {...}
    # }
    
    if client_data.get("reconnection"):
        instance_id = client_data.get("instance_id")
        last_close_code = client_data.get("last_close_code", 0)
        
        logger.info(f"Client {instance_id} reconnecting (last close: {last_close_code})")
        
        # 이전 세션 정보 복구 (필요한 경우)
        if last_close_code in [1001, 1013]:  # 서버 종료로 인한 재연결
            await restore_client_session(instance_id, websocket)
        
        # 재연결 성공 응답
        response = {
            "type": "reconnection_ack",
            "status": "ok",
            "session_restored": True,
            "server_status": "running"
        }
        await websocket.send_json(response)
```

---

### 6. **모니터링 및 로깅 강화**

**클라이언트 상태 추적:**

```python
class WebSocketManager:
    def __init__(self):
        self.connections = {}
        self.shutdown_status = False
    
    async def track_client_state(self, client_id, state_change):
        """클라이언트 상태 변화 추적"""
        
        logger.info(f"Client {client_id} state change: {state_change}")
        
        # 상태별 처리
        if state_change == "connected":
            self.connections[client_id]["last_seen"] = datetime.utcnow()
        elif state_change == "disconnected":
            await self.cleanup_client(client_id)
        elif state_change == "terminating":
            self.connections[client_id]["terminating"] = True
    
    def get_health_summary(self):
        """Health Check용 상태 요약"""
        return {
            "total_connections": len(self.connections),
            "authenticated_connections": sum(1 for c in self.connections.values() if c.get("authenticated")),
            "unauthenticated_connections": sum(1 for c in self.connections.values() if not c.get("authenticated")),
            "is_shutting_down": self.shutdown_status
        }
```

---

### 💡 **구현 체크리스트**

- [ ] **Health Check API**: `GET /deepstream/health` 엔드포인트 구현
- [ ] **Close Code 전송**: 1001 (Going Away), 1013 (Try Again Later) 적절히 사용
- [ ] **응답 처리**: `app_terminated` 메시지 형식 검증 (`status: "OK"`)
- [ ] **종료 시퀀스**: Health Check → terminate_app → 응답 대기 → 강제 종료
- [ ] **재연결 지원**: 클라이언트 재연결 시 세션 복구
- [ ] **모니터링**: 연결 상태 및 종료 과정 로깅

이러한 서버 측 구현이 완료되면 클라이언트와 서버 간의 graceful shutdown이 완벽하게 연동됩니다.