from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task


@CrewBase
class SlideCrew:
    """
    A crew responsible for converting report content to reveal.js markdown format slides.
    
    This crew takes a markdown report and transforms it into presentation slides
    suitable for reveal.js format.
    """
    agents_config = "config/agents.yaml"
    tasks_config = "config/tasks.yaml"

    @agent
    def slide_analyzer(self) -> Agent:
        """Agent responsible for analyzing the report and planning slide structure."""
        return Agent(
            config=self.agents_config['slide_analyzer'],
            verbose=True,
            cache=True
        )

    @agent
    def slide_creator(self) -> Agent:
        """Agent responsible for creating reveal.js markdown slides."""
        return Agent(
            config=self.agents_config['slide_creator'],
            verbose=True,
            cache=True
        )

    @task
    def analyze_report_structure(self) -> Task:
        """Task to analyze the report and create slide outline."""
        return Task(
            config=self.tasks_config['analyze_report_structure'],
            agent=self.slide_analyzer()
        )

    @task
    def create_reveal_slides(self) -> Task:
        """Task to create reveal.js markdown slides from the report."""
        return Task(
            config=self.tasks_config['create_reveal_slides'],
            agent=self.slide_creator(),
            context=[self.analyze_report_structure()]
        )

    @crew
    def crew(self) -> Crew:
        """Creates the slide generation crew."""
        return Crew(
            agents=[
                self.slide_analyzer(),
                self.slide_creator()
            ],
            tasks=[
                self.analyze_report_structure(),
                self.create_reveal_slides()
            ],
            process=Process.sequential,
            verbose=True,
            cache=True
        ) 