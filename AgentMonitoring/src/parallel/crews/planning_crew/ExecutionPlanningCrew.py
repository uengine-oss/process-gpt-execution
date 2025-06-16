from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task


@CrewBase
class ExecutionPlanningCrew:
    """
    A specialized crew for creating comprehensive execution plans for multi-format content generation.
    
    This crew focuses solely on analyzing form type combinations and creating intelligent 
    execution plans with dependencies and parallel processing strategies.
    """
    agents_config = "execution_planning_config/agents.yaml"
    tasks_config = "execution_planning_config/tasks.yaml"

    @agent
    def dependency_analyzer(self) -> Agent:
        """AI Agent specialized in analyzing form dependencies and creating execution plans."""
        return Agent(
            config=self.agents_config['dependency_analyzer'],
            verbose=True,
            cache=True
        )

    @task
    def create_execution_plan(self) -> Task:
        """Task to create a comprehensive execution plan for all form types."""
        return Task(
            config=self.tasks_config['create_execution_plan'],
            agent=self.dependency_analyzer()
        )

    @crew
    def crew(self) -> Crew:
        """Creates the execution planning crew."""
        return Crew(
            agents=[
                self.dependency_analyzer()
            ],
            tasks=[
                self.create_execution_plan()
            ],
            process=Process.sequential,
            verbose=True,
            cache=True
        ) 