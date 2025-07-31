# Process GPT Polling Service

이 서비스는 Process GPT 시스템의 워크아이템을 주기적으로 폴링하고 처리하는 독립적인 서비스입니다.

## 기능

- 데이터베이스에서 SUBMITTED 상태의 워크아이템 폴링 및 처리
- A2A 에이전트 모드 워크아이템 처리

## 설치 및 실행

### 로컬 실행

1. 의존성 설치:
```bash
# 가상환경 생성 및 활성화
uv venv .venv

# Windows PowerShell에서 가상환경 활성화
.venv\Scripts\activate

# Linux/Mac에서 가상환경 활성화
source .venv/bin/activate

# 의존성 설치
uv pip install -r requirements.txt

# 또는 pyproject.toml을 사용하는 경우
uv sync
```

2. 환경 변수 설정:
```bash
# .env.example 파일을 복사하여 .env 파일 생성
cp .env.example .env

# .env 파일을 편집하여 실제 값들을 설정하세요
# Windows의 경우:
notepad .env

# Linux/Mac의 경우:
nano .env
# 또는
vim .env
```

3. 서비스 실행:
```bash
# uv를 사용하여 직접 실행 (가상환경 자동 관리)
uv run main.py

# 또는 가상환경을 활성화한 후 실행
# Windows PowerShell:
.venv\Scripts\activate
python main.py

# Linux/Mac:
source .venv/bin/activate
python main.py
```

## 환경 변수
- `ENV`: 실행 모드
- `OPENAI_API_KEY`: OpenAI API 키
- `SUPABASE_URL`: Supabase 프로젝트 URL
- `SUPABASE_KEY`: Supabase API 키
- `SUPABASE_JWT_SECRET`: JWT 시크릿 키
- `SMTP_SERVER`: SMTP 서버 주소
- `SMTP_PORT`: SMTP 포트 번호
- `SMTP_USERNAME`: SMTP 사용자명
- `SMTP_PASSWORD`: SMTP 비밀번호
- `MEMENTO_SERVICE_URL`: Memento 서비스 URL (기본값: http://localhost:8005)
- `EXECUTION_SERVICE_URL`: 실행 서비스 URL (기본값: http://localhost:8000)
- `LANGSMITH_API_KEY`: LangSmith API 키
- `LANGSMITH_PROJECT`: LangSmith 프로젝트명


