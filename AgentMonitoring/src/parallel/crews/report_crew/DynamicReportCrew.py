from crewai import Agent, Crew, Process, Task
from typing import Dict, Any, Optional
from ...safe_tool_loader import SafeToolLoader


class DynamicReportCrew:
    """
    AgentMatchingCrew 결과물에서 섹션별 {toc, agent, task} 정보를 받아서
    동적으로 Agent와 Task를 생성해서 Crew를 만드는 클래스 (도구 연결 버전)
    """
    
    def __init__(self, section_data: Dict[str, Any], topic: str, previous_context: Dict[str, Any] = None):
        """
        Args:
            section_data: 섹션별 {toc, agent, task} 데이터
            topic: 주제
            previous_context: 이전 작업 컨텍스트
        """
        self.topic = topic
        self.previous_context = previous_context or {}
        self.toc_info = section_data.get("toc", {})
        self.agent_config = section_data.get("agent", {})
        self.task_config = section_data.get("task", {})
        
        # 🔄 이전 컨텍스트 디버깅 출력
        print("="*60)
        print("🔄 [DynamicReportCrew] 전달받은 이전 컨텍스트:")
        print(f"   타입: {type(self.previous_context)}")
        if self.previous_context:
            print(f"   내용: (생략)")
        else:
            print("   내용: 비어있음")
        print("="*60)
        
        # SafeToolLoader 다시 생성 (실제 도구 로딩용)
        self.safe_tool_loader = SafeToolLoader()
        
        self.section_title = self.toc_info.get("title", "Unknown Section")
        
        print(f"🎯 DynamicReportCrew 초기화: {self.section_title}")
        print(f"   └─ 매칭된 에이전트: {self.agent_config.get('name', 'Unknown')} ({self.agent_config.get('role', 'Unknown')})")
        
        # 🔍 디버깅: agent_config에 있는 모든 키 출력
        print(f"   └─ agent_config 키들: {list(self.agent_config.keys())}")
        
        # tool_names에서 실제 도구 객체 생성
        self.tool_names = self.agent_config.get('tool_names', [])
        self.actual_tools = self.safe_tool_loader.create_tools_from_names(self.tool_names)
        
        print(f"   └─ 요청된 도구 이름들: {self.tool_names}")
        print(f"   └─ 실제 생성된 도구: {len(self.actual_tools)}개")
    
    def create_dynamic_agent(self) -> Agent:
        """동적으로 Agent 생성 (실제 도구 포함)"""
        
        # 기본 Agent 정보
        agent_role = self.agent_config.get("role", "Unknown Role")
        agent_goal = self.agent_config.get("goal", "Unknown Goal")
        agent_backstory = self.agent_config.get("persona", "Unknown Background")
        
        print(f"🔧 동적 Agent 생성: {agent_role}")
        print(f"   └─ 실제 할당된 도구: {len(self.actual_tools)}개")
        
        # Agent 생성 (실제 도구 할당)
        agent = Agent(
            role=agent_role,
            goal=agent_goal,
            backstory=agent_backstory,
            tools=self.actual_tools,  # 실제 Tool 객체들 할당
            verbose=True,
            cache=True
        )
        
        return agent
    
    def create_section_task(self, agent: Agent) -> Task:
        """동적으로 섹션 작성 Task 생성 (안전 지침 포함)"""
        
        base_description = self.task_config.get("description", "")
        expected_output = self.task_config.get("expected_output", "")

        # 🔄 이전 작업 컨텍스트를 description에 추가 (제한 없음)
        context_info = ""
        if self.previous_context:
            context_str = str(self.previous_context)
            context_info = f"\n\n[이전 작업 컨텍스트]\n{context_str}"

        # 🆕 안전한 작업 지침 추가
        safe_description = base_description + context_info + """
        
        🚨 작업 안전 지침:
        1. 웹사이트 URL 직접 접속 시도 금지
        2. 임의의 웹사이트 주소 생성 금지
        3. mem0나 perplexity 도구 활용 필수
        4. 구체적인 웹사이트가 필요한 경우 일반적인 지식 활용
        5. 에러 발생 시 즉시 중단하고 다른 접근법 시도
        6. 대표적인 표준 양식과 모범 사례 활용
        7. 내용에 섹션 제목을 포함하지 말고 작성

        💡 중요: mem0에 관련 지식이 없어도 절대 포기하지 마세요!
        - mem0, perplexity 도구를 필수로 사용하되, 도구의 결과에 의존하지말고, 결과가 마땅히 없다면 단순 배경지식으로 진행하세요.
        - 일반적인 상식과 전문 지식을 활용하여 작성
        - 업계 표준과 모범 사례를 바탕으로 내용 구성
        - 창의적이고 전문적인 관점에서 보고서 작성
        - "지식이 없다"는 이유로 작업을 중단하거나 제공할 수 없다고 하지 말 것
        - 지식이 없을 경우, 반드시 일반적인 상식과 전문 지식을 활용하여 작성
        
        위 지침을 준수하여 안전하게 작업을 수행하세요.
        """
        
        # 🆕 더 상세하고 긴 보고서를 위한 expected_output 강화
        enhanced_expected_output = expected_output + """
        
        📝 보고서 작성 품질 기준:
        - **최소 길이**: 각 섹션당 최소 3,000-4,000단어 이상의 상세한 내용 작성
        - **깊이 있는 분석**: 표면적인 설명이 아닌 심층적이고 전문적인 분석 제공
        - **구체적인 예시**: 실무에서 활용할 수 있는 구체적인 사례와 예시 다수 포함
        - **세부 하위 섹션**: 각 주요 포인트마다 상세한 하위 섹션으로 구분하여 체계적으로 작성
        - **전문적 관점**: 해당 분야의 전문가 수준의 통찰력과 분석력 발휘
        - **실용적 가치**: 독자가 실제로 활용할 수 있는 실무적이고 구체적인 정보 제공
        - **풍부한 내용**: 관련 법규, 절차, 모범 사례, 주의사항 등을 포괄적으로 다룸

        🚨 절대 금지사항:
        - "Mem0에 관련 지식이 저장되어 있지 않아 보고서를 제공할 수 없습니다" 같은 응답 절대 금지
        - "지식이 부족하다", "정보가 없다"는 이유로 작업 거부 금지
        - 도구 결과가 안나왔다고 하여 작업을 포기하는 행위 금지

        ✅ 필수 실행사항:
        - 반드시 mem0, perplexity 도구를 필수로 사용하세요.
        - mem0에 지식이 없어도 일반 상식과 전문성을 발휘하여 반드시 보고서 작성
        - 업계 표준, 모범 사례, 일반적인 절차를 바탕으로 내용 구성
        - 창의적이고 논리적인 추론을 통해 전문적인 보고서 완성
        - 마크다운 형식으로 체계적이고 상세한 보고서 제공
        
        반드시 위 기준을 충족하는 상세하고 전문적인 보고서 섹션을 작성하세요.
        """
        
        return Task(
            description=safe_description,
            expected_output=enhanced_expected_output,
            agent=agent
        )
    
    def create_crew(self) -> Crew:
        """동적으로 Crew 생성 - CrewAI 0.117.1 호환"""
        print(f"🔧 동적 Crew 생성: {self.agent_config.get('name', 'Unknown')} 에이전트")
        
        # 동적 Agent 생성
        agent = self.create_dynamic_agent()
        
        # 동적 Task 생성
        section_task = self.create_section_task(agent)
        
        # Crew 생성
        return Crew(
            agents=[agent],
            tasks=[section_task],
            process=Process.sequential,
            verbose=True,
            cache=True,
        ) 