# FCM Service

Firebase Cloud Messaging (FCM) 푸시 알림을 처리하는 마이크로서비스입니다.

## 기능

- FCM 푸시 알림 전송
- 디바이스 토큰 관리
- 미처리 알림 폴링 및 자동 전송
- REST API 제공

## API 엔드포인트

### POST /send-notification
FCM 푸시 알림을 전송합니다.

```json
{
  "user_id": "user@example.com",
  "title": "알림 제목",
  "body": "알림 내용",
  "type": "general",
  "url": "https://example.com",
  "from_user_id": "sender@example.com",
  "data": {}
}
```

### GET /device-token/{user_id}
사용자의 FCM 디바이스 토큰을 조회합니다.

### GET /health
서비스 상태를 확인합니다.

## 환경 변수

- `SUPABASE_URL`: Supabase URL
- `SUPABASE_KEY`: Supabase Service Role Key
- `SUPABASE_JWT_SECRET`: JWT Secret
- `DB_NAME`: PostgreSQL 데이터베이스 이름
- `DB_USER`: PostgreSQL 사용자
- `DB_PASSWORD`: PostgreSQL 비밀번호
- `DB_HOST`: PostgreSQL 호스트
- `DB_PORT`: PostgreSQL 포트
- `ENV`: 환경 (production/development)

## Firebase 설정

Firebase 서비스 계정 키 파일이 필요합니다:
- 개발 환경: `firebase-credentials.json`
- 프로덕션 환경: `/etc/secrets/firebase-credentials.json` (Kubernetes Secret)

## 로컬 실행

```bash
# 의존성 설치
pip install -r requirements.txt

# 환경 변수 설정 (.env 파일)
cp .env.example .env

# 서비스 실행
python main.py
```

## Docker 실행

```bash
# 이미지 빌드
docker build -t fcm-service .

# 컨테이너 실행
docker run -p 8666:8666 -e ENV=production fcm-service
```

## Kubernetes 배포

```bash
# 배포
kubectl apply -f deployment.yaml

# 서비스 확인
kubectl get pods -l app=fcm-service
kubectl get svc fcm-service
```

## 모니터링

서비스는 15초마다 미처리 알림을 체크하고 자동으로 FCM 푸시를 전송합니다.
로그는 표준 출력으로 출력되며 Kubernetes 환경에서 모니터링할 수 있습니다.