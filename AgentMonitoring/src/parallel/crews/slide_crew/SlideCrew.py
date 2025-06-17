from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task


@CrewBase
class SlideCrew:
    """
    리포트 내용을 reveal.js 마크다운 형식 슬라이드로 변환하는 크루
    
    이 크루는 마크다운 리포트를 분석하여 reveal.js 형식에 적합한 
    프레젠테이션 슬라이드로 변환합니다.
    """
    agents_config = "config/agents.yaml"
    tasks_config = "config/tasks.yaml"

    @agent
    def slide_generator(self) -> Agent:
        """리포트 분석과 reveal.js 슬라이드 생성을 담당하는 에이전트"""
        return Agent(
            config=self.agents_config['slide_generator'],
            verbose=True,
            cache=True
        )

    @task
    def generate_reveal_slides(self) -> Task:
        """리포트 분석부터 reveal.js 슬라이드 생성까지 통합 수행하는 태스크"""
        return Task(
            config=self.tasks_config['generate_reveal_slides'],
            agent=self.slide_generator()
        )

    @crew
    def crew(self) -> Crew:
        """슬라이드 생성 크루를 생성합니다."""
        return Crew(
            agents=[
                self.slide_generator()
            ],
            tasks=[
                self.generate_reveal_slides()
            ],
            process=Process.sequential,
            verbose=True,
            cache=True
        )
    
    def kickoff_async(self, inputs=None):
        """Override kickoff_async to show inputs for debugging."""
        print("="*60)
        print("🎬 [SlideCrew] 슬라이드 생성 시작")
        print(f"   리포트 내용 길이: {len(inputs.get('report_content', '')) if inputs else 0}자")
        print(f"   사용자 정보: {inputs.get('user_info', {}).get('name', 'Unknown') if inputs else 'None'}")
        print("   🎯 리포트 내용을 기반으로 슬라이드 생성합니다.")
        print("="*60)
        
        return super().crew().kickoff_async(inputs=inputs) 