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


class DynamicReportState(BaseModel):
    """State for the dynamic report generation flow."""
    topic: str = ""
    user_info: Dict[str, Any] = Field(default_factory=dict)  # User information
    
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
        # In newer CrewAI versions, the inputs are stored in self.state
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
        """Plan the report structure and generate TOC with agent matching."""
        print(f"🎯 토픽 분석 및 에이전트 매칭 시작: {self.state.topic}")
        
        # 🚀 crew_started 이벤트 발행 - Agent Matching 시작
        self.crew_manager.event_logger.emit_crew_started(
            crew_name="AgentMatchingCrew",
            topic=self.state.topic,
            job_id="report_generation"
        )
        
        # 🆕 Agent Matching Crew 생성 및 Supabase agents 조회
        agent_matching_crew_instance = self.crew_manager.create_agent_matching_crew()
        agent_matching_crew = AgentMatchingCrew()
        
        # Supabase에서 agents 조회 (🆕 안전한 도구 처리 포함)
        available_agents = await agent_matching_crew.get_available_agents()
        print(f"✅ {len(available_agents)}개 에이전트 조회 완료 (안전한 도구 처리됨)")
        
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
        
        # Agent Matching Crew 실행
        planning_result = await agent_matching_crew_instance.kickoff_async(inputs={
            "topic": self.state.topic,
            "user_info": self.state.user_info,
            "available_agents": crewai_safe_agents  # 🆕 정리된 에이전트 정보 사용
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
            
            print(f"✅ 계획 완료: {len(self.state.sections_data)}개 섹션 매칭 완료")
            return self.state.toc
            
        except Exception as e:
            print(f"❌ 결과 파싱 실패: {e}")
            print(f"❌ 실패한 데이터: {result_data}")  # 디버깅용
            # 기본 TOC로 폴백
            self.state.toc = [
                {"title": "서론", "id": "intro"},
                {"title": f"{self.state.topic} 현황", "id": "current_state"},
                {"title": "핵심 기술", "id": "technologies"},
                {"title": "응용 분야", "id": "applications"},
                {"title": "향후 전망", "id": "future"},
                {"title": "결론", "id": "conclusion"}
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
                        tool_names = [t.strip() for t in value.split(",")]
                        sanitized_agent["tool_names"] = tool_names
                    else:
                        sanitized_agent["tool_names"] = []
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
        safe_tools = ["mem0", "perplexity(mcp)"]
        
        if tools_config:
            tool_names = [t.strip() for t in tools_config.split(",")]
            for tool_name in tool_names:
                if tool_name not in safe_tools:
                    print(f"🚫 안전하지 않은 도구 감지: {tool_name}")
                    return False
        
        print(f"✅ Agent 안전성 검증 통과: {agent.get('name', 'Unknown')}")
        return True

    @listen("plan_report")
    async def generate_report_sections(self):
        """Generate each section of the report in parallel using DynamicReportCrew."""
        print("🚀 안전한 동적 섹션 병렬 생성 시작...")
        
        # Create tasks for each section using sections_data
        section_tasks = []
        for section_data in self.state.sections_data:
            section_task = self.create_section_task(section_data)
            section_tasks.append(section_task)
        
        # Execute all section tasks in parallel
        section_results = await asyncio.gather(*section_tasks)
        
        # Store the results in the state
        for i, section_data in enumerate(self.state.sections_data):
            section_title = section_data.get("toc", {}).get("title", f"section_{i}")
            self.state.section_reports[section_title] = section_results[i]
        
        print(f"✅ {len(section_results)}개 안전한 동적 섹션 생성 완료")
        return self.state.section_reports

    async def create_section_task(self, section_data):
        """Create a task to generate a specific section using DynamicReportCrew."""
        section_title = section_data.get("toc", {}).get("title", "Unknown Section")
        print(f"🎯 안전한 동적 섹션 생성: {section_title}")
        
        # 🆕 섹션별 Agent 안전성 재검증 (설정 파일 기반)
        agent_data = section_data.get("agent", {})
        if not self._validate_section_agent_safety(agent_data):
            print(f"⚠️  섹션 Agent 안전성 문제 - 기본 모드로 실행: {section_title}")
            # 안전한 기본 Agent 설정으로 대체
            agent_data = self._get_safe_fallback_agent(agent_data)
            section_data["agent"] = agent_data
        
        # DynamicReportCrew 생성
        dynamic_crew_instance = DynamicReportCrew(section_data, self.state.topic)
        crew = dynamic_crew_instance.create_crew()
        
        # Execute the dynamic crew
        inputs = {
            "topic": self.state.topic,
            "user_info": self.state.user_info
        }
        
        try:
            report_result = await crew.kickoff_async(inputs=inputs)
            return report_result.raw if report_result else ""
        except Exception as e:
            print(f"❌ 섹션 생성 실패: {section_title} - {e}")
            return f"섹션 '{section_title}' 생성 중 오류가 발생했습니다. 안전한 기본 내용으로 대체합니다."

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

    @listen("generate_report_sections")
    def compile_final_report(self):
        """Compile all sections into the final report."""
        print("📋 안전한 최종 리포트 컴파일...")
        
        # 🎯 task_started 이벤트 발행
        self.crew_manager.event_logger.emit_task_started(
            role="Report Compiler",
            goal="Compile all sections into a comprehensive final report",
            job_id="final_report_compilation"
        )
        
        # Create the report header with user info if available
        report = f"# REPORT: {self.state.topic}\n\n"
        
        # Add author information if user_info is available
        if self.state.user_info and self.state.user_info.get('name'):
            report += f"**Author:** {self.state.user_info.get('name')}\n"
            if self.state.user_info.get('position') and self.state.user_info.get('department'):
                report += f"**Position:** {self.state.user_info.get('position')}, {self.state.user_info.get('department')}\n"
            if self.state.user_info.get('email'):
                report += f"**Contact:** {self.state.user_info.get('email')}\n"
            report += f"**Date:** [Report Draft - Date TBD]\n\n"
        
        # 🆕 안전성 공지 추가
        report += f"*이 리포트는 안전한 도구 시스템을 사용하여 생성되었습니다.*\n\n"
        
        report += f"## Table of Contents\n\n"
        
        # Add the table of contents
        for i, section_data in enumerate(self.state.sections_data):
            toc = section_data.get("toc", {})
            section_title = toc.get("title", "Unknown Section")
            report += f"{i+1}. {section_title}\n"
        
        report += "\n\n"
        
        # Add each section content using new structure
        for section_data in self.state.sections_data:
            toc = section_data.get("toc", {})
            section_title = toc.get("title", "Unknown Section")
            section_content = self.state.section_reports.get(section_title, "No content generated for this section.")
            
            report += f"{section_content}\n\n"
        
        # Store the final report in the state
        self.state.final_report = report
        
        # 🎯 task_completed 이벤트 발행
        self.crew_manager.event_logger.emit_task_completed(
            final_result=self.state.final_report,
            job_id="final_report_compilation"
        )
        
        # ✅ 전체 리포트 작업 완료 - crew_completed 이벤트 발행
        self.crew_manager.event_logger.emit_crew_completed(
            crew_name="DynamicReportFlow",
            topic=self.state.topic,
            job_id="report_generation"
        )
        
        print("✅ 안전한 최종 리포트 컴파일 완료")
        
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