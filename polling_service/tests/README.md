# Polling service tests

이 디렉터리는 `polling_service` 서브패키지의 테스트를 보관합니다. GitHub Actions `polling-service.yaml`에서 이 폴더의 테스트가 모두 통과해야만 이미지 빌드/배포가 진행됩니다.

## 테스트 추가 가이드
- 파일명: `test_*.py` 또는 `*_test.py`
- 프레임워크: pytest (함수형 테스트와 `assert` 사용 권장)
- 임포트: 패키지 내부 모듈은 로컬 모듈 기준으로 임포트 (패키지 풀네임 지양)
  - 예) `from block_finder import BlockFinder`
  - 주의: 동일 디렉터리의 `polling_service.py`가 패키지명과 충돌할 수 있으므로, 로컬 모듈 임포트를 사용하세요.
- 데이터/픽스처: 이 폴더에 두고 아래처럼 참조
  ```python
  from pathlib import Path
  DATA_PATH = Path(__file__).parent / "test.json"
  ```

## 실행 방법
- 로컬 실행
  ```bash
  cd polling_service
  pytest -vv --tb=long -l -ra tests
  ```
- 루트에서 실행
  ```bash
  pytest -vv --tb=long -l -ra polling_service/tests
  ```
- CI 연동
  - `.github/workflows/polling-service.yaml`의 `tests` 잡이 이 폴더를 실행하며, 성공 시에만 `build-and-deploy`가 동작합니다.

## 권장 사항
- 외부 API/DB 의존 테스트는 mocking/fixture로 대체
- 느린 테스트는 마커를 활용해 선택적으로 실행 (`-m`)

## 테스트 코드 작성 가이드
- 최소 단위로 검증: 작은 그래프/입력으로 핵심 동작을 검증하세요.
- 독립성: 각 테스트는 다른 테스트에 의존하지 않도록 만드세요.
- 명확한 어서션: 결과뿐 아니라 부수효과(예: inferred feedback 수, 멤버 목록)도 검증하세요.
- 예외/에러 케이스: 경계 값, 빈 입력, 루프/사이클 등 실패 시나리오도 포함하세요.
- 네이밍: `test_동작_조건_기대결과` 형태로 의도를 드러내세요.
- 픽스처: 반복되는 준비 코드는 함수/모듈 레벨 픽스처로 추출하세요(`@pytest.fixture`).
- 파라메터라이즈: 입력 조합이 많으면 `@pytest.mark.parametrize`로 간결하게 표현하세요.
- 타임아웃/성능: 오래 걸리는 경우 원인 분리, 마커(`slow`)로 구분해 선택 실행 가능하게 하세요.

### 예시 1) 간단한 함수형 테스트
```python
def test_arithmetic_basic():
    a, b = 6, 3
    assert a + b == 9
    assert a - b == 3
    assert a * b == 18
    assert a / b == 2
```

### 예시 2) 픽스처와 파라메터라이즈
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
아래 설정을 `.vscode/launch.json`에 추가하면 현재 열려있는 "polling_service/tests" 파일을 pytest로 디버깅 실행할 수 있습니다.

```json
{
    "version": "0.2.0",
    "configurations": [
        {
            "name": "Debug current test file (pytest, polling_service)",
            "type": "python",
            "request": "launch",
            "module": "pytest",
            "args": ["-vv", "--tb=long", "-l", "-ra", "${file}"],
            "cwd": "${workspaceFolder}/polling_service",
            "justMyCode": true,
            "console": "integratedTerminal"
        }
    ]
}
```

주의
- 인터프리터는 워크스페이스 venv로 선택(.venv 등)
- 실패 시 자동 중단하려면 args에 `--pdb` 추가, 출력 확인은 `-s` 추가
