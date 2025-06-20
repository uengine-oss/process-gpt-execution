# Process GPT Polling Service

이 서비스는 Process GPT 시스템의 워크아이템을 주기적으로 폴링하고 처리하는 독립적인 서비스입니다.

## 기능

- 데이터베이스에서 SUBMITTED 상태의 워크아이템 폴링
- A2A 에이전트 모드 워크아이템 처리
- 워크아이템 상태 업데이트 및 다음 단계 생성
- 채팅 메시지 로깅

## 설치 및 실행

### Docker를 사용한 실행

1. 환경 변수 설정:
```bash
export SUPABASE_URL=your_supabase_url
export SUPABASE_KEY=your_supabase_key
export SUPABASE_JWT_SECRET=your_jwt_secret
export DB_NAME=your_db_name
export DB_USER=your_db_user
export DB_PASSWORD=your_db_password
export DB_HOST=your_db_host
export DB_PORT=your_db_port
```

2. Docker Compose로 실행:
```bash
docker-compose up -d
```

### 로컬 실행

1. 의존성 설치:
```bash
pip install -r requirements.txt
```

2. 환경 변수 설정 후 실행:
```bash
python main.py
```

## 서비스 구조

```
polling_service/
├── polling_service.py      # 메인 폴링 로직
├── workitem_processor.py   # 워크아이템 처리 로직
├── agent_processor.py      # 에이전트 처리 로직
├── database.py                 # 데이터베이스 함수들
├── main.py                     # 서비스 진입점
├── Dockerfile                  # Docker 이미지 설정
├── docker-compose.yml          # Docker Compose 설정
├── requirements.txt            # Python 의존성
└── README.md                   # 이 파일
```

## 환경 변수

- `SUPABASE_URL`: Supabase 프로젝트 URL
- `SUPABASE_KEY`: Supabase API 키
- `SUPABASE_JWT_SECRET`: JWT 시크릿 키
- `DB_NAME`: PostgreSQL 데이터베이스 이름
- `DB_USER`: PostgreSQL 사용자명
- `DB_PASSWORD`: PostgreSQL 비밀번호
- `DB_HOST`: PostgreSQL 호스트
- `DB_PORT`: PostgreSQL 포트

## 로그

서비스는 다음과 같은 로그를 출력합니다:
- `[INFO]`: 일반 정보
- `[DEBUG]`: 디버그 정보
- `[ERROR]`: 오류 정보

## 중지

Docker Compose를 사용하는 경우:
```bash
docker-compose down
```

로컬 실행의 경우 Ctrl+C로 중지할 수 있습니다. 