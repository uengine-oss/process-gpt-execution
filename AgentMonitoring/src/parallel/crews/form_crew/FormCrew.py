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