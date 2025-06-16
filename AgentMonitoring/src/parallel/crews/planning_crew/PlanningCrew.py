from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task


@CrewBase
class PlanningCrew:
    """
    A crew responsible for planning the report structure and configuring agents and tasks.
    
    This crew:
    1. Analyzes the input topic
    2. Generates a table of contents
    3. Configures the necessary agents for writing each section
    4. Configures tasks for writing each section
    """
    agents_config = "config/agents.yaml"
    tasks_config = "config/tasks.yaml"

    @agent
    def topic_analyzer(self) -> Agent:
        """Agent responsible for analyzing the input topic."""
        return Agent(
            config=self.agents_config['topic_analyzer'],
            verbose=True,
            cache=True
        )

    @agent
    def outline_builder(self) -> Agent:
        """Agent responsible for building the report outline and TOC."""
        return Agent(
            config=self.agents_config['outline_builder'],
            verbose=True,
            cache=True
        )

    @agent
    def agent_configurator(self) -> Agent:
        """Agent responsible for configuring agents for each section."""
        return Agent(
            config=self.agents_config['agent_configurator'],
            verbose=True,
            cache=True
        )

    @agent
    def task_configurator(self) -> Agent:
        """Agent responsible for configuring tasks for each section."""
        return Agent(
            config=self.agents_config['task_configurator'],
            verbose=True,
            cache=True
        )



    @task
    def analyze_topic(self) -> Task:
        """Task to analyze the input topic and identify key aspects to cover."""
        return Task(
            config=self.tasks_config['analyze_topic'],
            async_execution=True
        )

    @task
    def create_outline(self) -> Task:
        """Task to create a structured outline and TOC based on topic analysis."""
        return Task(
            config=self.tasks_config['create_outline'],
            context=[self.analyze_topic()]
        )

    @task
    def configure_agents(self) -> Task:
        """Task to configure agents for each section of the report."""
        return Task(
            config=self.tasks_config['configure_agents'],
            context=[self.create_outline()]
        )

    @task
    def configure_tasks(self) -> Task:
        """Task to configure tasks for each section of the report."""
        return Task(
            config=self.tasks_config['configure_tasks'],
            context=[self.create_outline(), self.configure_agents()]
        )

    @task
    def compile_planning_output(self) -> Task:
        """Task to compile all planning outputs into a structured format."""
        return Task(
            config=self.tasks_config['compile_planning_output'],
            context=[self.create_outline(), self.configure_agents(), self.configure_tasks()]
        )



    @crew
    def crew(self) -> Crew:
        """The planning crew that orchestrates the planning process."""
        return Crew(
            agents=[
                self.topic_analyzer(), 
                self.outline_builder(), 
                self.agent_configurator(), 
                self.task_configurator()
            ],
            tasks=[
                self.analyze_topic(), 
                self.create_outline(), 
                self.configure_agents(), 
                self.configure_tasks(),
                self.compile_planning_output()
            ],
            process=Process.sequential,
            verbose=True,
            cache=True
        )

 