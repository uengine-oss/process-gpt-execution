# AgentMonitoring 🤖

> CrewAI 기반 Agent 모니터링 및 병렬 패턴 데모 시스템

## 📋 프로젝트 개요

AgentMonitoring은 CrewAI를 활용하여 AI 에이전트들의 작업을 모니터링하고, 동적 리포트 생성 및 멀티 포맷 콘텐츠 생성을 지원하는 병렬 처리 시스템입니다.

### 🎯 주요 특징

- **🔄 병렬 처리**: 여러 AI 에이전트가 동시에 작업을 수행
- **📊 실시간 모니터링**: 에이전트 작업 상태를 실시간으로 추적
- **📝 동적 리포트 생성**: 주제에 따라 자동으로 구조화된 리포트 생성
- **🎬 멀티 포맷 지원**: 리포트, 슬라이드, 텍스트 등 다양한 형태의 콘텐츠 생성
- **🛡️ 안전한 도구 관리**: 보안 정책 기반의 도구 로딩 시스템
- **📈 이벤트 로깅**: Supabase와 파일 기반 이벤트 로깅
- **🔗 MCP 지원**: Model Context Protocol을 통한 외부 도구 연동

## 🏗️ 아키텍처

```
AgentMonitoring/
├── main.py                    # FastAPI 서버 메인 진입점
├── src/parallel/             # 핵심 모듈들
│   ├── flows/               # Flow 구현체들
│   │   ├── dynamic_report_flow.py    # 동적 리포트 생성 플로우
│   │   └── multi_format_flow.py      # 멀티 포맷 생성 플로우
│   ├── crews/               # CrewAI Crew 구현체들
│   ├── event_logging/       # 이벤트 로깅 시스템
│   ├── todolist_poller.py   # 작업 목록 폴링 시스템
│   ├── safe_tool_loader.py  # 안전한 도구 로더
│   └── crew_config_manager.py # Crew 설정 관리자
├── config/                  # 설정 파일들
│   ├── tool_security.json   # 도구 보안 정책
│   └── mcp.json            # MCP 서버 설정
└── database_schema.sql     # 데이터베이스 스키마
```

## 🚀 설치 및 실행

### 필요 조건

- Python 3.10+ (< 3.13)
- Supabase 계정 (선택사항)
- OpenAI API 키 또는 호환 가능한 LLM API

### 설치

1. **저장소 클론**
   ```bash
   git clone <repository-url>
   cd AgentMonitoring
   ```

2. **가상 환경 생성**
   ```bash
   cd AgentMonitoring
   uv venv --python 3.11.9
   파이썬 인터프리터 변경 (필요시 경로 직접 넣기 예: AgentMonitoring\.venv\Scripts\python.exe)
   uv run main.py
   ```

### 환경 설정

1. **환경 변수 설정**
   ```bash
   # .env 파일 생성
   OPENAI_API_KEY=your_openai_api_key
   SUPABASE_URL=your_supabase_url  # 선택사항
   SUPABASE_KEY=your_supabase_key  # 선택사항
   ```

2. **데이터베이스 설정** (Supabase 사용 시)
   ```sql
   events 테이블에 RLS 보완 설정 해제(Anno 키로 접근하기 위함) + RealTime 모드 ON해야 실시간 구독 가능
   -- database_schema.sql 파일의 내용을 Supabase에서 실행
   ```

### 실행

```bash
uv run main.py
```

서버가 `http://localhost:8001`에서 실행됩니다.

## 📚 주요 기능

### 1. 동적 리포트 생성 (DynamicReportFlow)

지정된 주제에 대해 자동으로 구조화된 리포트를 생성합니다.

**특징:**
- AI 기반 목차 자동 생성
- 에이전트 매칭을 통한 최적 전문가 선택
- 안전한 도구 시스템 활용
- 병렬 섹션 생성

**사용 예시:**
```python
from src.parallel.flows.dynamic_report_flow import DynamicReportFlow

flow = DynamicReportFlow()
flow.state.topic = "AI 기술의 의료 분야 활용"
flow.state.user_info = {
    "name": "홍길동",
    "email": "hong@example.com"
}

result = await flow.kickoff_async()
```

### 2. 멀티 포맷 콘텐츠 생성 (MultiFormatFlow)

하나의 주제로부터 리포트, 슬라이드, 텍스트 등 다양한 형태의 콘텐츠를 동시에 생성합니다.

**특징:**
- 병렬 포맷 생성
- 콘텐츠 재활용을 통한 성능 최적화
- 메모리 관리 및 정리
- 파일 자동 저장

### 3. 이벤트 로깅 시스템

모든 에이전트 작업을 실시간으로 추적하고 기록합니다.

**로깅 대상:**
- Task 시작/완료/실패
- Agent 실행 시작/완료/실패
- Flow 메서드 실행
- LLM 호출

**저장소:**
- Supabase 데이터베이스 (선택사항)
- 로컬 JSONL 파일

### 4. 안전한 도구 관리

보안 정책에 따라 도구의 사용을 제어합니다.

**보안 기능:**
- 허용 목록 기반 도구 필터링
- 도구 연결 상태 모니터링
- 안전하지 않은 도구 자동 차단

## 🛠️ 설정

### 도구 보안 정책 (`config/tool_security.json`)

```json
{
  "security_policy": "allowlist",
  "allowed_tools": ["mem0", "perplexity(mcp)"],
  "description": "안전한 도구만 허용하는 정책"
}
```

### MCP 서버 설정 (`config/mcp.json`)

```json
{
  "mcpServers": {
    "perplexity": {
      "command": "uvx",
      "args": ["perplexity-mcp"],
      "transport": "stdio"
    }
  }
}
```

## 📊 데이터베이스 스키마

### events 테이블
- 모든 에이전트 이벤트 저장
- run_id, job_id로 작업 그룹화
- JSONB 형태의 이벤트 데이터

### todolist 테이블
- 작업 목록 관리
- 상태 추적 (PENDING, PROCESSING, COMPLETED)
- 프로세스 인스턴스 연결

## 🔧 개발

### 새로운 Flow 추가

1. `src/parallel/flows/` 디렉토리에 새로운 Flow 클래스 생성
2. `Flow[StateType]`을 상속받아 구현
3. `@start()`, `@listen()` 데코레이터를 사용하여 단계 정의

### 새로운 Crew 추가

1. `src/parallel/crews/` 디렉토리에 새로운 Crew 생성
2. `CrewConfigManager`를 통해 등록
3. 필요한 Agent와 Task 정의

## 📈 모니터링

### 로그 확인

- **파일 로그**: `logs/` 디렉토리의 JSONL 파일
- **Supabase**: events 테이블에서 실시간 조회
- **콘솔**: 실시간 진행 상황 표시

### 성능 최적화

- 병렬 처리를 통한 속도 향상
- 콘텐츠 캐싱으로 중복 작업 방지
- 메모리 자동 정리

## 🤝 기여

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add some amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📄 라이선스

이 프로젝트는 MIT 라이선스 하에 배포됩니다.

## 👥 개발자

- **Rick Jang** - jyjang@uengine.org

## 🔗 관련 링크

- [CrewAI Documentation](https://docs.crewai.com/)
- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [Supabase Documentation](https://supabase.com/docs)

---

**참고**: 이 프로젝트는 AI 에이전트의 병렬 처리 패턴을 실험하고 데모하기 위한 목적으로 개발되었습니다. 