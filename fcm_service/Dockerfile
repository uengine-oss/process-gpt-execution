# 1단계: 빌드 스테이지
FROM python:3.12.3-slim as builder

# 빌드 도구 설치
RUN apt-get update && apt-get install -y gcc g++ libffi-dev libssl-dev build-essential \
    && rm -rf /var/lib/apt/lists/*

# 패키지 설치
RUN pip install --upgrade pip
COPY requirements.txt .
RUN pip install -r requirements.txt

# 2단계: 실행 스테이지
FROM python:3.12.3-slim

ENV TZ=Asia/Seoul
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

WORKDIR /usr/src/app
RUN mkdir -p /data && chmod 777 /data

# 빌드 스테이지에서 필요한 파일만 복사
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY . .

EXPOSE 8666

CMD ["python", "main.py", "--host", "0.0.0.0", "--port", "8666"]