FROM python:3.12.3-slim

ENV TZ=Asia/Seoul
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

WORKDIR /usr/src/app

RUN mkdir -p /data && chmod 777 /data

COPY . .

RUN apt-get update && apt-get install -y gcc g++ libffi-dev libssl-dev build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --upgrade pip
RUN pip install --no-cache-dir --prefer-binary -r requirements.txt

EXPOSE 80

# 스트리밍 안정성을 위한 설정 추가
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--timeout-keep-alive", "300", "--workers", "1", "--loop", "asyncio"]