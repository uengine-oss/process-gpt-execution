from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task


@CrewBase
class ReportCrew:
    """
    A crew responsible for writing sections of the report as configured by the planning crew.
    
    This crew is dynamically instantiated for each section of the report and
    is responsible for researching and writing content for that section.
    """
    agents_config = "config/agents.yaml"
    tasks_config = "config/tasks.yaml"

    @agent
    def section_researcher(self, section_id="", section_title="", topic="") -> Agent:
        """Agent responsible for researching content for a specific section."""
        # We're using the generic section researcher from the config but customizing
        # it for the specific section at hand
        base_config = self.agents_config['section_researcher']
        
        # Customize the agent for this specific section
        customized_config = {
            "role": "Section Researcher",
            "goal": f"Research and gather factual information for the '{section_title}' section of the report on {topic}.",
            "backstory": f"You are an expert researcher specialized in {topic}, with deep knowledge of {section_title}. Your expertise allows you to gather comprehensive, accurate, and up-to-date information on this subject."
        }
        
        # Create a new config with base values updated by custom values
        config = {**base_config, **customized_config}
        
        return Agent(
            config=config,
            verbose=True,
            cache=True
        )

    @agent
    def section_writer(self, section_id="", section_title="", topic="") -> Agent:
        """Agent responsible for writing content for a specific section."""
        # Similar to researcher, we customize the writer for this section
        base_config = self.agents_config['section_writer']
        
        customized_config = {
            "role": "Section Writer",
            "goal": f"Write a comprehensive, engaging, and informative '{section_title}' section for the report on {topic}.",
            "backstory": f"You are an expert writer with significant experience in creating content about {topic}. You excel at explaining {section_title} in a clear, concise, and engaging manner, making complex concepts accessible to the intended audience."
        }
        
        config = {**base_config, **customized_config}
        
        return Agent(
            config=config,
            verbose=True,
            cache=True
        )

    @task
    def research_section(self, section_id="", section_title="", topic="") -> Task:
        """Task to research content for a specific section."""
        base_config = self.tasks_config['research_section']
        
        customized_config = {
            "description": f"Research and gather comprehensive information for the '{section_title}' section of the report on {topic}. Find relevant facts, statistics, examples, and expert opinions that will provide a solid foundation for this section.",
            "expected_output": f"A detailed research brief containing key information, data points, quotes, and insights for the '{section_title}' section. This brief should be well-structured and comprehensive enough to serve as the basis for writing the section."
        }
        
        config = {**base_config, **customized_config}
        
        return Task(
            config=config,
            agent=self.section_researcher(section_id, section_title, topic),
            async_execution=True
        )

    @task
    def write_section(self, section_id="", section_title="", topic="") -> Task:
        """Task to write content for a specific section."""
        base_config = self.tasks_config['write_section']
        
        customized_config = {
            "description": f"Write the '{section_title}' section of the report on {topic}. Use the research brief provided to create a comprehensive, informative, and engaging section that flows well and fits into the overall report structure.",
            "expected_output": f"A well-written, polished section on '{section_title}' for the report on {topic}. The section should be approximately 500-1000 words, properly structured with subheadings if appropriate, and contain all the key information from the research brief presented in an engaging and readable manner."
        }
        
        config = {**base_config, **customized_config}
        
        return Task(
            config=config,
            agent=self.section_writer(section_id, section_title, topic),
            context=[self.research_section(section_id, section_title, topic)]
        )

    @crew
    def section_crew(self, section_id="", section_title="", topic="") -> Crew:
        """Dynamically creates a crew for writing a specific section of the report."""
        return Crew(
            agents=[
                self.section_researcher(section_id, section_title, topic),
                self.section_writer(section_id, section_title, topic)
            ],
            tasks=[
                self.research_section(section_id, section_title, topic),
                self.write_section(section_id, section_title, topic)
            ],
            process=Process.sequential,
            verbose=True,
            cache=True
        ) 