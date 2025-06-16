from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task
from typing import List, Dict, Any
from ...agents_repository import AgentsRepository


@CrewBase
class AgentMatchingCrew:
    """
    토픽 분석과 Supabase Agents 매칭을 담당하는 크루 (2단계로 간소화)
    
    1. 토픽 전문 분석
    2. TOC + 에이전트 매칭 + Task 할당 한번에 처리
    """
    agents_config = "config_agent_matching/agents.yaml"
    tasks_config = "config_agent_matching/tasks.yaml"

    def __init__(self):
        super().__init__()
        self.agents_repository = AgentsRepository()

    @agent
    def topic_specialist(self) -> Agent:
        """토픽을 전문적으로 분석하는 에이전트"""
        return Agent(
            config=self.agents_config['topic_specialist'],
            verbose=True,
            cache=True
        )

    @agent
    def agent_toc_matcher(self) -> Agent:
        """TOC 설계 + 에이전트 매칭 + Task 설계를 한번에 처리하는 전문가"""
        return Agent(
            config=self.agents_config['agent_toc_matcher'],
            verbose=True,
            cache=True
        )

    @task
    def analyze_topic_deeply(self) -> Task:
        """토픽을 심층 분석하여 필요한 전문분야와 섹션 구조 파악"""
        return Task(
            config=self.tasks_config['analyze_topic_deeply'],
            async_execution=True
        )

    @task
    def create_toc_and_match_agents(self) -> Task:
        """TOC 생성 + 에이전트 매칭 + Task 할당을 한번에 처리"""
        return Task(
            config=self.tasks_config['create_toc_and_match_agents'],
            context=[self.analyze_topic_deeply()]
        )

    @crew
    def crew(self) -> Crew:
        """Agent Matching Crew 구성 (2단계로 간소화)"""
        return Crew(
            agents=[
                self.topic_specialist(),
                self.agent_toc_matcher()
            ],
            tasks=[
                self.analyze_topic_deeply(),
                self.create_toc_and_match_agents()
            ],
            process=Process.sequential,
            verbose=True,
            cache=True
        )
    
    async def get_available_agents(self, tenant_id: str = "default") -> List[Dict[str, Any]]:
        """사용 가능한 에이전트 목록 조회"""
        return await self.agents_repository.get_all_agents(tenant_id) 