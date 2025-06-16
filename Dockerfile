FROM python:3.12.3-slim

WORKDIR /usr/src/app

RUN mkdir -p /data && chmod 777 /data

COPY . .

RUN apt-get update && apt-get install -y gcc g++ libffi-dev libssl-dev build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --upgrade pip
RUN pip install --no-cache-dir --prefer-binary -r requirements.txt

EXPOSE 80

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]