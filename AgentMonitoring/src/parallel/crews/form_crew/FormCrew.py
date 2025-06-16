from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task


@CrewBase
class FormCrew:
    """
    A crew responsible for generating contextual form field values in JSON format.
    
    This crew creates realistic values for specific form fields based on the provided
    content and field names.
    """
    agents_config = "config/agents.yaml"
    tasks_config = "config/tasks.yaml"

    @agent
    def field_value_generator(self) -> Agent:
        """Agent responsible for generating contextual values for specific form fields."""
        return Agent(
            config=self.agents_config['field_value_generator'],
            verbose=True,
            cache=True
        )

    @task
    def generate_field_value(self) -> Task:
        """Task to generate contextual values for multiple form fields."""
        return Task(
            config=self.tasks_config['generate_field_value'],
            agent=self.field_value_generator()
        )

    @crew
    def crew(self) -> Crew:
        """Creates a crew for generating individual field values."""
        return Crew(
            agents=[
                self.field_value_generator()
            ],
            tasks=[
                self.generate_field_value()
            ],
            process=Process.sequential,
            verbose=True,
            cache=True
        )
    
    def kickoff_async(self, inputs=None):
        """Override kickoff_async to show inputs for debugging."""
        print("="*60)
        print("📝 [FormCrew] 폼 필드 값 생성 시작")
        print(f"   워크플로우 단계: {inputs.get('topic', 'Unknown') if inputs else 'None'}")
        print(f"   필드 개수: {len(inputs.get('field_info', [])) if inputs else 0}개")
        print(f"   리포트 내용 길이: {len(inputs.get('report_content', '')) if inputs else 0}자")
        print(f"   사용자 정보: {inputs.get('user_info', {}).get('name', 'Unknown') if inputs else 'None'}")
        print("   🎯 리포트 내용을 기반으로 폼 값을 생성합니다.")
        print("="*60)
        
        return super().crew().kickoff_async(inputs=inputs) 