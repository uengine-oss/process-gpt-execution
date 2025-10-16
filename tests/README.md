# Root tests

이 디렉터리는 루트 레벨의 테스트를 보관합니다. GitHub Actions `deploy.yaml`에서 이 폴더의 테스트가 모두 통과해야만 빌드/배포가 진행됩니다.

## 테스트 추가 가이드
- 파일명: `test_*.py` 또는 `*_test.py`
- 프레임워크: pytest (함수형 테스트와 `assert` 사용 권장)
- 데이터/픽스처: 테스트 전용 파일은 이 폴더에 두고 아래처럼 참조
  ```python
  from pathlib import Path
  DATA_PATH = Path(__file__).parent / "test.json"
  ```
- 임포트: 루트 기준 모듈은 `from process_definition import ...`처럼 임포트 가능

## 실행 방법
- 로컬 실행
  ```bash
  pytest -vv --tb=long -l -ra tests
  ```
- CI 연동
  - `.github/workflows/deploy.yaml`의 `tests` 잡이 이 폴더를 실행하며, 성공 시에만 `build-and-deploy`가 동작합니다.

## 권장 사항
- 외부 API/DB 의존 테스트는 mocking/fixture로 대체
- 느린 테스트는 마커를 활용해 선택적으로 실행 (`-m`)

## 테스트 코드 작성 가이드
- 최소 단위로 검증: 작은 입력으로 핵심 동작을 검증하세요.
- 독립성: 테스트 간 상태/순서 의존성을 두지 마세요.
- 명확한 어서션: 결과와 부수효과를 함께 검증하세요.
- 예외/에러 케이스: 경계값, 빈 입력 등 실패 시나리오 포함.
- 네이밍: `test_동작_조건_기대결과`로 의도를 드러내세요.
- 픽스처: 반복 준비 코드는 `@pytest.fixture`로 추출.
- 파라메터라이즈: 다수 조합은 `@pytest.mark.parametrize` 활용.
- 타임아웃/성능: 느린 항목은 원인 분리, 마커로 구분.

### 예시 1) 간단한 사칙연산 테스트
```python
def test_arithmetic_basic():
    a, b = 6, 3
    assert a + b == 9
    assert a - b == 3
    assert a * b == 18
    assert a / b == 2
```

### 예시 2) 픽스처와 파라메터라이즈(사칙연산)
```python
import pytest

@pytest.fixture
def numbers():
    return 6, 3

@pytest.mark.parametrize("op,expected", [
    ("add", 9),
    ("sub", 3),
    ("mul", 18),
    ("div", 2),
])
def test_arithmetic_param(numbers, op, expected):
    a, b = numbers
    result = {
        "add": a + b,
        "sub": a - b,
        "mul": a * b,
        "div": a // b,
    }[op]
    assert result == expected
```

## VS Code/Cursor 디버그 설정 (launch.json)
아래 설정을 `.vscode/launch.json`에 추가하면 현재 열려있는 "루트 tests" 파일을 pytest로 디버깅 실행할 수 있습니다.

```json
{
    "version": "0.2.0",
    "configurations": [
        {
            "name": "Debug current test file (pytest, root)",
            "type": "python",
            "request": "launch",
            "module": "pytest",
            "args": ["-vv", "--tb=long", "-l", "-ra", "${file}"],
            "cwd": "${workspaceFolder}",
            "justMyCode": true,
            "console": "integratedTerminal"
        }
    ]
}
```

주의
- 인터프리터는 워크스페이스 venv로 선택(.venv 등)
- 실패 시 자동 중단하려면 args에 `--pdb` 추가, 출력 확인은 `-s` 추가
