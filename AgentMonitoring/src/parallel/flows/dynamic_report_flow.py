import asyncio
from typing import Dict, List, Any
import json
import os
from datetime import datetime

from crewai.crew import Crew
from crewai.flow.flow import Flow, and_, listen, router, start
from pydantic import BaseModel, Field

from ..crews.planning_crew.PlanningCrew import PlanningCrew
from ..crews.report_crew.ReportCrew import ReportCrew
from ..crew_config_manager import CrewConfigManager
from ..safe_tool_loader import SafeToolLoader  # 🆕 안전한 도구 로더 추가
from ..agents_repository import AgentsRepository
from ..crews.report_crew.DynamicReportCrew import DynamicReportCrew
from ..crews.planning_crew.AgentMatchingCrew import AgentMatchingCrew
from ..context_manager import context_manager


class DynamicReportState(BaseModel):
    """State for the dynamic report generation flow."""
    topic: str = ""
    user_info: Dict[str, Any] = Field(default_factory=dict)  # User information
    previous_context: Dict[str, Any] = Field(default_factory=dict)  # 이전 작업 컨텍스트
    
    # 🆕 새로운 구조: 섹션별 데이터 배열
    sections_data: List[Dict[str, Any]] = Field(default_factory=list)
    
    # 기존 호환성
    toc: List[Dict[str, Any]] = Field(default_factory=list)
    agent_configs: List[Dict[str, Any]] = Field(default_factory=list)
    task_configs: List[Dict[str, Any]] = Field(default_factory=list)
    section_reports: Dict[str, str] = Field(default_factory=dict)
    final_report: str = ""


class DynamicReportFlow(Flow[DynamicReportState]):
    """
    A flow that dynamically plans and generates a report on a given topic.
    
    This flow consists of two main phases:
    1. Planning: Generates a table of contents and configures agents and tasks
    2. Execution: Dynamically creates and executes agents and tasks to write each section
    """

    def __init__(self, enable_supabase_logging: bool = True, enable_file_logging: bool = True):
        super().__init__(
            description="Flow for dynamic report generation based on a given topic",
            state_type=DynamicReportState
        )
        
        # 크루 구성 매니저 초기화 - 이벤트 로깅 시스템 설정
        self.crew_manager = CrewConfigManager(
            enable_supabase_logging=enable_supabase_logging,
            enable_file_logging=enable_file_logging
        )
        
        # 🆕 안전한 도구 로더 초기화
        print("🔧 SafeToolLoader 초기화 중...")
        try:
            self.safe_tool_loader = SafeToolLoader()
            
            # 도구 연결 상태 확인
            tool_status = self.safe_tool_loader.get_tool_connection_status()
            print("📊 도구 연결 상태:")
            for tool_name, status in tool_status.items():
                print(f"   └─ {tool_name}: {status}")
                
        except Exception as e:
            print(f"❌ SafeToolLoader 초기화 실패: {e}")
            print("   └─ 기본 설정으로 진행하지만 도구 기능이 제한될 수 있습니다")
            self.safe_tool_loader = None
        
        # AgentsRepository 초기화
        print("📚 AgentsRepository 초기화 중...")
        try:
            self.agents_repo = AgentsRepository()
            print("✅ AgentsRepository 초기화 완료")
        except Exception as e:
            print(f"❌ AgentsRepository 초기화 실패: {e}")
            raise e
        
        print("🚀 DynamicReportFlow 초기화 완료")

    @start()
    async def initialize_flow(self):
        """Initialize the flow with the input topic."""
        # === 이전 컨텍스트 3줄로 불러오기 ===
        proc_inst_id = getattr(self.state, 'proc_inst_id', None)
        if proc_inst_id:
            self.state.previous_context = context_manager.get_context(proc_inst_id)
        # === 기존 코드 계속 ===
        if hasattr(self, 'inputs') and "topic" in self.inputs:
            self.state.topic = self.inputs["topic"]
            print(f"Initialized flow with topic: {self.state.topic}")
            return self.state.topic
        elif hasattr(self, 'state') and hasattr(self.state, 'topic') and self.state.topic:
            print(f"Using topic from state: {self.state.topic}")
            if self.state.user_info:
                print(f"User: {self.state.user_info.get('name', 'Unknown')} ({self.state.user_info.get('email', 'No email')})")
            return self.state.topic
        else:
            # Fallback to a default topic for testing
            default_topic = "Artificial Intelligence in Healthcare"
            print(f"No topic provided, using default: {default_topic}")
            self.state.topic = default_topic
            return default_topic

    @listen("initialize_flow")
    async def plan_report(self):
        """Analyze previous context and design activity-based tasks with agent matching."""
        print(f"🎯 이전 컨텍스트 분석 및 액티비티 기반 작업 설계 시작: {self.state.topic}")
        
        # 🚀 crew_started 이벤트 발행 - Agent Matching 시작
        self.crew_manager.event_logger.emit_crew_started(
            crew_name="AgentMatchingCrew",
            topic=self.state.topic,
            job_id=f"activity_execution_{self.state.topic}"
        )
        
        # 🆕 Agent Matching Crew 생성 및 Supabase agents 조회
        agent_matching_crew_instance = self.crew_manager.create_agent_matching_crew()
        agent_matching_crew = AgentMatchingCrew()
        
        print("🔍 이전 컨텍스트 상태 확인:")
        if self.state.previous_context:
            print(f"   └─ 컨텍스트 있음: {type(self.state.previous_context)}")
            print(f"   └─ 컨텍스트 키들: {list(self.state.previous_context.keys()) if isinstance(self.state.previous_context, dict) else 'Not dict'}")
        else:
            print("   └─ 이전 컨텍스트 없음 - 첫 번째 단계로 가정")
        
        # Supabase에서 agents 조회 (🆕 안전한 도구 처리 포함)
        available_agents = await agent_matching_crew.get_available_agents()
        print(f"✅ {len(available_agents)}개 에이전트 조회 완료 (안전한 도구 처리됨)")
        
        # role -> profile 매핑 설정
        from ..event_logging.crew_event_logger import GlobalContextManager
        role_profile_mapping = {agent.get('role'): agent.get('profile', '') for agent in available_agents if agent.get('role')}
        GlobalContextManager.set_role_profile_mapping(role_profile_mapping)
        
        # 🆕 Agent 도구 안전성 검증
        safe_agents = []
        for agent in available_agents:
            if self._validate_agent_safety(agent):
                safe_agents.append(agent)
            else:
                print(f"⚠️  안전하지 않은 Agent 제외: {agent.get('name', 'Unknown')}")
        
        print(f"🛡️  {len(safe_agents)}개 안전한 에이전트 선별 완료")
        
        # 🔧 CrewAI inputs용 에이전트 정보 정리 (간소화된 버전)
        crewai_safe_agents = self._sanitize_agents_for_crewai(safe_agents)
        
        # Agent Matching Crew 실행 (previous_context 중심으로 전달)
        planning_result = await agent_matching_crew_instance.kickoff_async(inputs={
            "topic": self.state.topic,  # 액티비티 이름
            "user_info": self.state.user_info,
            "available_agents": crewai_safe_agents,  # 🆕 정리된 에이전트 정보 사용
            "previous_context": self.state.previous_context or {"info": "첫 번째 단계로 이전 컨텍스트가 없습니다."}  # 이전 작업 컨텍스트가 핵심!
        })
        
        # JSON 결과 파싱
        try:
            import json
            result_data = planning_result.raw
            print(f"🔍 파싱할 원본 데이터: {result_data[:200]}...")  # 디버깅용
            
            # JSON 파싱 시도
            if isinstance(result_data, str):
                # 1. ```json ... ``` 형태 처리
                import re
                json_code_block = re.search(r'```(?:json)?\s*(\[.*?\])\s*```', result_data, re.DOTALL)
                if json_code_block:
                    result_data = json.loads(json_code_block.group(1))
                    print("✅ 마크다운 코드블록에서 JSON 추출 성공")
                else:
                    # 2. 순수 JSON 배열 찾기
                    json_array = re.search(r'\[.*\]', result_data, re.DOTALL)
                    if json_array:
                        result_data = json.loads(json_array.group())
                        print("✅ 순수 JSON 배열 추출 성공")
                    else:
                        # 3. 전체를 JSON으로 파싱 시도
                        result_data = json.loads(result_data)
                        print("✅ 전체 문자열 JSON 파싱 성공")
            
            # 🆕 새로운 구조: 섹션별 데이터 배열 저장
            self.state.sections_data = result_data
            
            # 기존 호환성을 위해 toc 정보도 추출
            self.state.toc = [section.get("toc", {}) for section in result_data]
            
            print(f"✅ 액티비티 기반 작업 설계 완료: {len(self.state.sections_data)}개 작업 구성")
            return self.state.toc
            
        except Exception as e:
            print(f"❌ 결과 파싱 실패: {e}")
            print(f"❌ 실패한 데이터: {result_data}")  # 디버깅용
            # 기본 액티비티 작업 구조로 폴백
            self.state.toc = [
                {"title": "요구사항 분석", "id": "requirements"},
                {"title": "기본 구조 설계", "id": "structure"},
                {"title": "핵심 내용 작성", "id": "content"},
                {"title": "세부 사항 보완", "id": "details"},
                {"title": "검토 및 완성", "id": "review"},
                {"title": "최종 정리", "id": "finalization"}
            ]
            return self.state.toc

    def _sanitize_agents_for_crewai(self, agents: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """CrewAI inputs용 에이전트 정보 정리 (간소화된 버전)"""
        sanitized_agents = []
        
        for agent in agents:
            sanitized_agent = {}
            
            # 기본 타입만 포함 (str, int, float, bool, dict, list)
            for key, value in agent.items():
                if key == "processed_tools":
                    # processed_tools는 무시 (tool_names만 사용)
                    continue
                elif key == "tools" and isinstance(value, str):
                    # tools 문자열을 tool_names 배열로 변환
                    if value.strip():
                        tool_names = [t.strip() for t in value.split(",") if t.strip()]
                        new_tool_names = []
                        for t in tool_names:
                            t_lower = t.lower()
                            if t_lower == "mem0":
                                new_tool_names.append("mem0")
                            elif t_lower == "perplexity":
                                new_tool_names.append("perplexity(mcp)")
                            # Playwrite 등 기타 도구는 무시
                        # mem0이 없으면 추가
                        if "mem0" not in new_tool_names:
                            new_tool_names.insert(0, "mem0")
                        # 중복 제거
                        new_tool_names = list(dict.fromkeys(new_tool_names))
                        sanitized_agent["tool_names"] = new_tool_names
                    else:
                        sanitized_agent["tool_names"] = ["mem0"]
                elif isinstance(value, (str, int, float, bool, list, dict)) or value is None:
                    # 기본 타입만 포함
                    sanitized_agent[key] = value
                else:
                    # 복잡한 객체는 문자열로 변환
                    sanitized_agent[key] = str(value)
            
            sanitized_agents.append(sanitized_agent)
        
        print(f"🔧 CrewAI용 에이전트 정보 정리 완료: {len(sanitized_agents)}개")
        return sanitized_agents

    def _validate_agent_safety(self, agent: Dict[str, Any]) -> bool:
        """에이전트 안전성 검증 (간소화된 버전)"""
        agent_role = agent.get("role", "")
        tools_config = agent.get("tools", "")
        
        print(f"🔍 Agent 안전성 검증: {agent.get('name', 'Unknown')} ({agent_role})")
        
        # 기본적으로 안전한 도구들
        safe_tools = ["mem0", "perplexity(mcp)", "perplexity", "playwright"]
        
        if tools_config:
            tool_names = [t.strip() for t in tools_config.split(",")]
            for tool_name in tool_names:
                if tool_name not in safe_tools:
                    print(f"🚫 안전하지 않은 도구 감지: {tool_name}")
                    return False
        
        print(f"✅ Agent 안전성 검증 통과: {agent.get('name', 'Unknown')}")
        return True

    @listen("plan_report")
    async def generate_activity_tasks(self):
        """Execute each task of the current activity in parallel using DynamicReportCrew."""
        print(f"🚀 액티비티 '{self.state.topic}' 기반 작업 병렬 실행 시작...")
        
        # Create tasks for each work item using sections_data
        activity_tasks = []
        for task_data in self.state.sections_data:
            activity_task = self.create_activity_task(task_data)
            activity_tasks.append(activity_task)
        
        # Execute all activity tasks in parallel
        task_results = await asyncio.gather(*activity_tasks)
        
        # Store the results in the state
        for i, task_data in enumerate(self.state.sections_data):
            task_title = task_data.get("toc", {}).get("title", f"task_{i}")
            self.state.section_reports[task_title] = task_results[i]
        
        print(f"✅ 액티비티 '{self.state.topic}' - {len(task_results)}개 작업 실행 완료")
        return self.state.section_reports

    async def create_activity_task(self, task_data):
        """Create a task to execute a specific work item using DynamicReportCrew."""
        task_title = task_data.get("toc", {}).get("title", "Unknown Task")
        print(f"🎯 액티비티 작업 실행: {task_title}")
        
        # 🆕 작업별 Agent 안전성 재검증 (설정 파일 기반)
        agent_data = task_data.get("agent", {})
        if not self._validate_section_agent_safety(agent_data):
            print(f"⚠️  작업 Agent 안전성 문제 - 기본 모드로 실행: {task_title}")
            # 안전한 기본 Agent 설정으로 대체
            agent_data = self._get_safe_fallback_agent(agent_data)
            task_data["agent"] = agent_data
        
        # DynamicReportCrew 생성 (previous_context가 핵심!)
        dynamic_crew_instance = DynamicReportCrew(task_data, self.state.topic, self.state.previous_context or {})
        crew = dynamic_crew_instance.create_crew()
        
        # Execute the dynamic crew with context-aware inputs
        inputs = {
            "topic": self.state.topic,  # 액티비티 이름
            "user_info": self.state.user_info,
            "previous_context": self.state.previous_context or {"info": "첫 번째 단계입니다."},  # 핵심!
            "current_task": task_title  # 현재 수행 중인 작업명
        }
        
        try:
            task_result = await crew.kickoff_async(inputs=inputs)
            return task_result.raw if task_result else ""
        except Exception as e:
            print(f"❌ 작업 실행 실패: {task_title} - {e}")
            return f"작업 '{task_title}' 실행 중 오류가 발생했습니다. 이전 컨텍스트를 기반으로 기본 결과를 제공합니다."

    def _validate_section_agent_safety(self, agent_data: Dict[str, Any]) -> bool:
        """섹션별 Agent 추가 안전성 검증 (간소화된 버전)"""
        tool_names = agent_data.get("tool_names", [])
        agent_role = agent_data.get("role", "")
        
        print(f"🔍 섹션 Agent 안전성 검증: {agent_role}, 도구들: {tool_names}")
        
        # 기본적으로 안전한 도구들
        safe_tools = ["mem0", "perplexity(mcp)"]
        
        for tool_name in tool_names:
            if tool_name not in safe_tools:
                print(f"🚫 섹션 Agent 안전성 실패: {tool_name}")
                return False
        
        print(f"✅ 섹션 Agent 안전성 검증 통과")
        return True

    def _get_safe_fallback_agent(self, original_agent: Dict[str, Any]) -> Dict[str, Any]:
        """안전한 폴백 Agent 설정 생성 (간소화된 버전)"""
        safe_agent = original_agent.copy()
        
        # 기본 안전한 도구 이름들
        safe_tool_names = ["mem0"]  # 가장 안전한 기본 도구
        
        safe_agent["tool_names"] = safe_tool_names
        safe_agent["safety_instructions"] = "mem0에서 지식을 검색하고, 없으면 명확히 부족함을 알리세요."
        
        print(f"🛡️  안전한 폴백 Agent 생성: {safe_agent.get('name', 'Unknown')}")
        return safe_agent

    @listen("generate_activity_tasks")
    def compile_final_result(self):
        """Compile all task results into the final activity output."""
        print(f"📋 액티비티 '{self.state.topic}' 최종 결과 컴파일...")
        
        # 🎯 task_started 이벤트 발행
        self.crew_manager.event_logger.emit_task_started(
            role="Activity Result Compiler",
            goal=f"Compile all task results for activity '{self.state.topic}' based on previous context",
            job_id=f"activity_compilation_{self.state.topic}"
        )
        
        # Create the activity result header
        result = ""
        
        # Add author information if user_info is available
        if self.state.user_info and self.state.user_info.get('name'):
            result += f"**담당자:** {self.state.user_info.get('name')}\n"
            if self.state.user_info.get('position') and self.state.user_info.get('department'):
                result += f"**부서/직급:** {self.state.user_info.get('position')}, {self.state.user_info.get('department')}\n"
            if self.state.user_info.get('email'):
                result += f"**연락처:** {self.state.user_info.get('email')}\n"
            result += f"**작업 일시:** [작업 완료 - 날짜 TBD]\n\n"
        
        # Add each task result using new structure
        for task_data in self.state.sections_data:
            toc = task_data.get("toc", {})
            task_title = toc.get("title", "Unknown Task")
            task_content = self.state.section_reports.get(task_title, "이 작업에 대한 결과가 생성되지 않았습니다.")
            
            result += f"{task_content}\n\n"
        
        # Store the final result in the state
        self.state.final_report = result
        
        # 🎯 task_completed 이벤트 발행
        self.crew_manager.event_logger.emit_task_completed(
            final_result=self.state.final_report,
            job_id=f"activity_compilation_{self.state.topic}"
        )
        
        # ✅ 전체 액티비티 작업 완료 - crew_completed 이벤트 발행
        self.crew_manager.event_logger.emit_crew_completed(
            crew_name="DynamicReportFlow",
            topic=self.state.topic,
            job_id=f"activity_execution_{self.state.topic}"
        )
        
        print(f"✅ 액티비티 '{self.state.topic}' 최종 결과 컴파일 완료")
        
        return self.state.final_report
    
    def get_flow_status(self) -> Dict[str, Any]:
        """플로우 상태 정보 반환"""
        return {
            "flow_name": "DynamicReportFlow",
            "safe_tool_loader_status": "연결됨" if self.safe_tool_loader else "연결 안됨",
            "agents_repo_status": "연결됨" if self.agents_repo else "연결 안됨",
            "tool_status": self.safe_tool_loader.get_tool_connection_status() if self.safe_tool_loader else {},
        }


def plot():
    flow = DynamicReportFlow()
    flow.plot() 