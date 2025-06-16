"""
크루 구성 및 콜백 연동 매니저
CrewAI 크루들에 이벤트 리스너와 콜백을 연결 (글로벌 이벤트 버스 사용)
"""

from typing import List, Optional, Dict, Any, Callable
from crewai import Crew

# 🚀 최적화된 이벤트 로거 (글로벌 이벤트 버스 연결)
from .event_logging import CrewAIEventLogger

from .crews.planning_crew.PlanningCrew import PlanningCrew
from .crews.planning_crew.ExecutionPlanningCrew import ExecutionPlanningCrew
from .crews.planning_crew.AgentMatchingCrew import AgentMatchingCrew
from .crews.report_crew.ReportCrew import ReportCrew
from .crews.form_crew.FormCrew import FormCrew
from .crews.slide_crew.SlideCrew import SlideCrew

# 🔒 글로벌 상태 관리 (Singleton 패턴)
_global_event_logger = None
_global_listeners_registered = False

# ==============================================
# CrewConfigManager: Initialization & Listener Registration
# ==============================================

class CrewConfigManager:
    """
    크루 구성 및 글로벌 이벤트 시스템 연동을 담당하는 매니저 클래스
    """
    
    # === Initialization ===
    def __init__(self, enable_supabase_logging: bool = True, enable_file_logging: bool = True) -> None:
        """
        크루 구성 매니저 초기화
        """
        # --- Global Logger (Singleton) ---
        global _global_event_logger, _global_listeners_registered
        
        # 🔒 글로벌 이벤트 로거 Singleton 패턴
        if _global_event_logger is None:
            _global_event_logger = CrewAIEventLogger(
                enable_supabase=enable_supabase_logging,
                enable_file_logging=enable_file_logging
            )
            print("🆕 새로운 글로벌 이벤트 로거 생성")
        else:
            print("♻️ 기존 글로벌 이벤트 로거 재사용")
        
        self.event_logger = _global_event_logger
        
        # --- Register Global Event Listeners (Singleton) ---
        # 🔒 글로벌 이벤트 버스 리스너 중복 등록 방지
        if not _global_listeners_registered:
            from crewai.utilities.events import CrewAIEventsBus
            self.event_bus = CrewAIEventsBus()
            self._setup_global_listeners()
            _global_listeners_registered = True
            print("✅ 글로벌 이벤트 리스너 등록 완료")
        else:
            print("♻️ 글로벌 이벤트 리스너 이미 등록됨 (재사용)")
        
        print("🎯 글로벌 이벤트 버스 연결 완료")
        print(f"   - Task/Agent 이벤트만 기록 (Crew 이벤트 제외)")
        print(f"   - 모든 크루가 자동으로 이벤트 로깅에 연결됨")
    
    # === Listener Setup ===
    def _setup_global_listeners(self) -> None:
        """CrewAI 글로벌 이벤트 버스에 리스너 등록"""
        # 필요한 이벤트 클래스 불러오기
        from crewai.utilities.events.task_events import TaskStartedEvent, TaskCompletedEvent
        from crewai.utilities.events.agent_events import AgentExecutionStartedEvent, AgentExecutionCompletedEvent

        # 🆕 Flow와 LLM 이벤트 추가
        try:
            from crewai.utilities.events import (
                FlowStartedEvent, FlowFinishedEvent,
                MethodExecutionStartedEvent, MethodExecutionFinishedEvent,
                LLMCallStartedEvent, LLMCallCompletedEvent, LLMStreamChunkEvent
            )
            flow_llm_events_available = True
        except ImportError:
            flow_llm_events_available = False

        # 성공 이벤트 목록
        events = [
            TaskStartedEvent,
            TaskCompletedEvent,
            AgentExecutionStartedEvent,
            AgentExecutionCompletedEvent
        ]
        
        # 🆕 Flow/LLM 이벤트 추가 (사용 가능한 경우)
        if flow_llm_events_available:
            events.extend([
                FlowStartedEvent, FlowFinishedEvent,
                MethodExecutionStartedEvent, MethodExecutionFinishedEvent,
                LLMCallStartedEvent, LLMCallCompletedEvent, LLMStreamChunkEvent
            ])
            print("🆕 Flow/LLM 이벤트 추가됨")
        
        # 실패 이벤트 추가 시도
        try:
            from crewai.utilities.events.task_events import TaskFailedEvent
            from crewai.utilities.events.agent_events import AgentExecutionFailedEvent
            events.extend([TaskFailedEvent, AgentExecutionFailedEvent])
        except ImportError:
            pass

        # 이벤트 버스에 핸들러 일괄 등록
        for evt in events:
            @self.event_bus.on(evt)
            def _handler(source, event, evt=evt):
                # 🎯 Manus 스타일 진행상황 표시 추가
                self._display_manus_style_progress(event)
                self.event_logger.on_event(event, source)

        print(f"✅ {len(events)}개의 이벤트 리스너 등록 완료")
    
    def _display_manus_style_progress(self, event):
        """🎯 Manus 스타일의 실시간 진행상황 표시"""
        event_type = event.type
        
        # Flow 이벤트 처리
        if event_type == "method_execution_started":
            step_messages = {
                "ai_analyze_and_plan": "🤖 AI가 실행 계획을 수립하고 있습니다...",
                "generate_reports": "📝 리포트를 생성하고 있습니다...",
                "generate_slides": "🎬 슬라이드를 생성하고 있습니다...",
                "generate_texts": "📋 텍스트 필드를 채우고 있습니다...",
                "finalize_results": "📊 최종 결과를 정리하고 있습니다..."
            }
            method_name = getattr(event, 'method_name', 'unknown')
            message = step_messages.get(method_name, f"⚙️ {method_name} 처리중...")
            print(f"💭 {message}")
            
        elif event_type == "method_execution_finished":
            method_name = getattr(event, 'method_name', 'unknown')
            duration = getattr(event, 'execution_time', 0)
            print(f"✅ {method_name} 완료! ({duration:.1f}초)")
            
        # LLM 이벤트 처리
        elif event_type == "llm_call_started":
            print("🧠 AI 사고중...")
            
        elif event_type == "llm_stream_chunk":
            # Manus처럼 실시간 텍스트 스트리밍
            chunk = getattr(event, 'chunk', '.')
            print(f"💭{chunk}", end="", flush=True)
            
        elif event_type == "llm_call_completed":
            print(f"\n✅ AI 응답 완료!")
            
        # Agent 이벤트에 더 친근한 메시지 추가
        elif event_type == "agent_execution_started":
            agent_role = getattr(event.agent, 'role', 'Unknown') if hasattr(event, 'agent') else 'Unknown'
            if "researcher" in agent_role.lower():
                print("🔍 정보를 수집하고 있습니다...")
            elif "writer" in agent_role.lower():
                print("✍️ 콘텐츠를 작성하고 있습니다...")
            elif "analyzer" in agent_role.lower():
                print("📊 분석을 진행하고 있습니다...")
            else:
                print(f"🤖 {agent_role}가 작업을 시작했습니다...")
    
    # === Crew Factory Methods ===
    def create_planning_crew(self, **kwargs) -> Crew:
        """Planning Crew 생성 (글로벌 이벤트 자동 연결)"""
        planning_crew_instance = PlanningCrew()
        crew = planning_crew_instance.crew()
        print("📋 Planning Crew가 생성되었습니다. (글로벌 이벤트 로깅)")
        return crew
    
    def create_execution_planning_crew(self, **kwargs) -> Crew:
        """Execution Planning Crew 생성 (글로벌 이벤트 자동 연결)"""
        execution_planning_crew_instance = ExecutionPlanningCrew()
        crew = execution_planning_crew_instance.crew()
        print("🤖 Execution Planning Crew가 생성되었습니다. (글로벌 이벤트 로깅)")
        return crew
    
    def create_agent_matching_crew(self, **kwargs) -> Crew:
        """Agent Matching Crew 생성 (글로벌 이벤트 자동 연결)"""
        agent_matching_crew_instance = AgentMatchingCrew()
        crew = agent_matching_crew_instance.crew()
        print("🎯 Agent Matching Crew가 생성되었습니다. (글로벌 이벤트 로깅)")
        return crew
    
    def create_report_crew(self, section_id: str, section_title: str, topic: str, **kwargs) -> Crew:
        """Report Crew 생성 (글로벌 이벤트 자동 연결)"""
        report_crew_instance = ReportCrew()
        crew = report_crew_instance.section_crew(
            section_id=section_id,
            section_title=section_title,
            topic=topic
        )
        print(f"📝 Report Crew ({section_title})가 생성되었습니다. (글로벌 이벤트 로깅)")
        return crew
    
    def create_form_crew(self, **kwargs) -> Crew:
        """Form Crew 생성 (글로벌 이벤트 자동 연결)"""
        form_crew_instance = FormCrew()
        crew = form_crew_instance.crew()
        print("📋 Form Crew가 생성되었습니다. (글로벌 이벤트 로깅)")
        return crew
    
    def create_slide_crew(self, **kwargs) -> Crew:
        """Slide Crew 생성 (글로벌 이벤트 자동 연결)"""
        slide_crew_instance = SlideCrew()
        crew = slide_crew_instance.crew()
        print("🎨 Slide Crew가 생성되었습니다. (글로벌 이벤트 로깅)")
        return crew
    
    # === Callback Helpers ===
    def get_agent_callback(self, agent_name: str, task_id: Optional[str] = None) -> Callable[[Any], None]:
        """에이전트용 콜백 함수 반환"""
        return lambda step: print(f"🤖 Agent {agent_name}: {step.get('type', 'unknown')}")
    
    # === Summary Helpers ===
    def get_callback_summary(self) -> Dict[str, Any]:
        """콜백 시스템 상태 요약"""
        stats = self.event_logger.get_stats()
        
        summary = {
            "supabase_logging": stats.get("supabase_enabled", False),
            "file_logging": stats.get("file_logging_enabled", False),
            "run_id": stats.get("run_id"),
            "log_file": stats.get("log_file"),
            "supabase_enabled": stats.get("supabase_enabled", False),
            "unified_logging_enabled": True,
            "global_event_bus": True,
            "status": "글로벌 이벤트 버스 연결"
        }
        
        return summary
    
 