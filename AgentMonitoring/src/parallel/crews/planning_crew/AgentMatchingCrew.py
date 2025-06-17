from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task
from typing import List, Dict, Any
from ...agents_repository import AgentsRepository


@CrewBase
class AgentMatchingCrew:
    """
    이전 컨텍스트 분석과 현재 액티비티 기반 TOC 생성 및 에이전트 매칭을 담당하는 크루
    
    1. 이전 단계들의 작업 흐름과 컨텍스트를 심층 분석
    2. 현재 액티비티에 최적화된 보고서 목차(TOC) 생성
    3. 각 섹션별 최적 에이전트 매칭 + 맞춤형 Task 할당
    """
    agents_config = "config_agent_matching/agents.yaml"
    tasks_config = "config_agent_matching/tasks.yaml"

    def __init__(self):
        super().__init__()
        self.agents_repository = AgentsRepository()

    @agent
    def toc_generator_and_agent_matcher(self) -> Agent:
        """보고서 TOC 생성 및 에이전트 매칭을 담당하는 전문가"""
        return Agent(
            config=self.agents_config['toc_generator_and_agent_matcher'],
            verbose=True,
            cache=True
        )

    @task
    def design_activity_tasks(self) -> Task:
        """컨텍스트 분석과 액티비티별 작업 설계 + 에이전트 매칭을 통합하여 수행"""
        return Task(
            config=self.tasks_config['design_activity_tasks'],
        )

    @crew
    def crew(self) -> Crew:
        """Agent Matching Crew 구성 (컨텍스트 기반으로 재설계)"""
        return Crew(
            agents=[
                self.toc_generator_and_agent_matcher()
            ],
            tasks=[
                self.design_activity_tasks()
            ],
            process=Process.sequential,
            verbose=True,
            cache=True
        )
    
    async def get_available_agents(self, tenant_id: str = "default") -> List[Dict[str, Any]]:
        """사용 가능한 에이전트 목록 조회"""
        return await self.agents_repository.get_all_agents(tenant_id)
    
    def kickoff_async(self, inputs=None):
        """Override kickoff_async to print previous_context before execution."""
        if inputs and 'previous_context' in inputs:
            print("="*60)
            print("🔄 [AgentMatchingCrew] 전달받은 이전 컨텍스트:")
            print(f"   타입: {type(inputs['previous_context'])}")
            if inputs['previous_context']:
                print(f"   내용: {inputs['previous_context']}")
            else:
                print("   내용: 비어있음")
            print("="*60)
        else:
            print(f"⚠️ [AgentMatchingCrew] previous_context가 inputs에 없음. inputs 키들: {list(inputs.keys()) if inputs else 'None'}")
        
        return super().crew().kickoff_async(inputs=inputs) 