"""
CrewAI 이벤트 로깅 시스템 (최적화)
- 공식 문서 스타일의 이벤트 로깅
- 호환성을 위한 기존 인터페이스 유지
"""

# 🚀 최적화된 이벤트 로거 (내부적으로만 사용)
from .crew_event_logger import CrewAIEventLogger

# 호환성을 위한 별칭 제공 (기존 코드가 계속 작동하도록)
SupabaseGlobalListener = CrewAIEventLogger  # 별칭
CallbackHandler = CrewAIEventLogger          # 별칭

__all__ = ["SupabaseGlobalListener", "CallbackHandler", "CrewAIEventLogger"]
__version__ = "2.0.0"  # 최적화된 버전 