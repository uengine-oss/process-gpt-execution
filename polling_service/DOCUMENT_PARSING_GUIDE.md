# 문서 파일 파싱 및 요약 기능 가이드

## 개요

이 기능은 프로세스 실행 중 제출된 문서 파일(PDF, XLSX, HWP 등)을 자동으로 파싱하고 요약하여 다음 액티비티의 입력 데이터로 제공합니다.

## 지원 파일 형식

- **PDF** (.pdf)
- **Excel** (.xlsx, .xls)
- **Word** (.docx, .doc)
- **HWP** (.hwp)
- **PowerPoint** (.pptx, .ppt)

## 환경 설정

### 1. 필수 패키지 설치

```bash
cd polling_service
pip install -r requirements.txt
```

### 2. 환경 변수 설정

`.env` 파일에 Upstage API 키를 추가하세요:

```env
# Upstage AI Document Parser API Key
UPSTAGE_API_KEY=your_upstage_api_key_here
```

**Upstage API 키 발급 방법:**
1. [Upstage Console](https://console.upstage.ai/)에 접속
2. 회원가입 및 로그인
3. API Keys 메뉴에서 새 API 키 생성
4. Document AI API 권한 활성화

## 작동 방식

### 1. 자동 파일 감지

프로세스 정의에서 `inputData` 필드에 파일 타입 필드가 포함되어 있으면 자동으로 감지됩니다.

```json
{
  "activities": [
    {
      "id": "activity_1",
      "name": "서류 제출",
      "tool": "submission_form"
    },
    {
      "id": "activity_2",
      "name": "서류 검토",
      "inputData": ["submission_form.attached_file"],
      "tool": "review_form"
    }
  ]
}
```

### 2. 파일 파싱

제출된 파일이 다음 형식 중 하나로 전달됩니다:

**형식 1: 객체 형태**
```json
{
  "name": "document.pdf",
  "url": "https://storage.example.com/files/document.pdf"
}
```

**형식 2: URL 문자열**
```json
"https://storage.example.com/files/document.pdf"
```

### 3. 자동 요약

파싱된 텍스트가 5000자를 초과하면 LangChain의 summarization을 사용하여 자동으로 요약됩니다:

- **첫 번째 단계**: Map-Reduce 방식으로 청크별 요약
- **두 번째 단계**: 여전히 길면 추가 압축 요약
- **목표 길이**: 약 2000자 이내

### 4. 입력 데이터 구조

파싱된 문서는 다음과 같은 형태로 `[InputData]` 섹션에 추가됩니다:

```json
{
  "submission_form": {
    "attached_file": {
      "name": "document.pdf",
      "url": "https://..."
    }
  },
  "_parsed_documents": {
    "submission_form.attached_file": {
      "file_name": "document.pdf",
      "parsed_content": "요약된 문서 내용..."
    }
  }
}
```

### 5. CrewAI 에이전트에게 전달

`upsert_next_workitems` 함수에서 자동으로 처리되어 워크아이템의 `query` 필드에 추가됩니다:

```
[Description]
서류 내용을 검토하고 승인 여부를 결정하세요.

[Instruction]
첨부된 문서의 내용을 확인하여 기준에 부합하는지 검토하세요.

[InputData]
{
  "submission_form": {...},
  "_parsed_documents": {
    "submission_form.attached_file": {
      "file_name": "resume.pdf",
      "parsed_content": "이력서 요약 내용..."
    }
  }
}
```

## 예제: 이력서 검토 프로세스

### 프로세스 정의

```json
{
  "processDefinitionId": "resume_review",
  "name": "이력서 검토",
  "activities": [
    {
      "id": "submit_resume",
      "name": "이력서 제출",
      "tool": "resume_form",
      "type": "userTask"
    },
    {
      "id": "review_resume",
      "name": "이력서 검토",
      "inputData": ["resume_form.resume_file"],
      "description": "제출된 이력서를 검토하여 적격성을 평가하세요.",
      "type": "serviceTask",
      "assignee": "review-agent@agent.com"
    }
  ]
}
```

### 실행 흐름

1. **사용자 제출**: `submit_resume` 액티비티에서 PDF 이력서 파일 업로드
2. **자동 파싱**: Upstage AI가 PDF 내용 추출
3. **자동 요약**: 긴 이력서는 LangChain으로 요약
4. **에이전트 실행**: `review_resume` 액티비티의 에이전트가 요약된 내용을 받아 검토

## 기술 스택

- **Upstage Document AI**: 문서 파싱 (OCR 포함)
- **LangChain Summarization**: Map-Reduce 방식 텍스트 요약
- **OpenAI GPT-4o-mini**: 요약 생성 LLM
- **httpx**: 비동기 HTTP 클라이언트

## 에러 처리

### 파싱 실패시
- 로그에 경고 메시지 출력
- 원본 파일 정보만 전달
- 프로세스는 계속 진행

### API 키 미설정시
- 경고 메시지 출력
- 파일 파싱 스킵
- 기본 입력 데이터만 사용

### 요약 실패시
- 원본 텍스트의 처음 2000자만 사용
- "... (요약 실패)" 표시 추가

## 로그 예시

```
[INFO] 문서 파일 처리 시작: resume.pdf
[INFO] 문서 파싱 성공: 15234 문자
[INFO] 텍스트 요약 시작: 15234 문자
[INFO] 텍스트 요약 완료: 15234 -> 1876 문자
[INFO] 파일 파싱 완료: resume.pdf
```

## 성능 고려사항

- **파싱 시간**: 파일 크기에 따라 5-30초
- **요약 시간**: 텍스트 길이에 따라 10-60초
- **병렬 처리**: 여러 파일이 있을 경우 순차 처리
- **타임아웃**: Upstage API는 5분 타임아웃 설정

## 비용

- **Upstage AI**: 문서당 API 요금 발생
- **OpenAI**: 요약시 토큰 사용량에 따라 과금
- **무료 티어**: Upstage는 월 1000건까지 무료

## 문제 해결

### 파일이 파싱되지 않음
1. UPSTAGE_API_KEY 환경 변수 확인
2. 파일 확장자가 지원 형식인지 확인
3. 파일 URL이 접근 가능한지 확인

### 요약이 너무 짧거나 길음
`document_parser.py`의 상수 조정:
```python
SUMMARIZATION_THRESHOLD = 5000  # 요약 시작 기준
```

### 비동기 에러 발생
nest-asyncio가 자동으로 처리하지만, 문제 발생시:
```python
import nest_asyncio
nest_asyncio.apply()
```

## 커스터마이징

### 지원 파일 형식 추가

`document_parser.py`에서:
```python
SUPPORTED_EXTENSIONS = {'.pdf', '.xlsx', '.xls', '.docx', '.doc', '.hwp', '.pptx', '.ppt', '.txt', '.csv'}
```

### 요약 방식 변경

`summarize_text` 함수의 `chain_type` 파라미터 수정:
- `map_reduce`: 긴 문서, 여러 청크
- `stuff`: 짧은 문서, 한 번에 처리
- `refine`: 반복적 개선

## 참고 자료

- [Upstage Document AI](https://developers.upstage.ai/docs/apis/document-parse)
- [LangChain Summarization](https://python.langchain.com/docs/use_cases/summarization)
- [Process GPT Documentation](../README.md)

