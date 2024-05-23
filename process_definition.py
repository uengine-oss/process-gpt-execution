import json
from pathlib import Path
from typing import Any, Dict, List, Union, Optional
from pydantic import BaseModel, Field

class DataSource(BaseModel):
    type: str
    sql: Optional[str] = None

class Variable(BaseModel):
    name: str
    description: str
    type: str
    dataSource: Optional[DataSource] = None

class ProcessData(BaseModel):
    name: str
    description: str
    type: str
    dataSource: Optional[DataSource] = None

class ProcessRole(BaseModel):
    name: str
    resolutionRule: str

class DataField(BaseModel):
    mandatory: Optional[bool] = None
    type: Optional[str] = None
    value: Optional[Union[str, bool]] = None

class ProcessActivity(BaseModel):
    name: str
    id: str
    type: str
    description: str
    instruction: Optional[str] = None
    role: str
    inputData: Optional[List[str]] = Field(default_factory=list)
    outputData: Optional[List[str]] = Field(default_factory=list)
    checkpoints: Optional[List[str]] = Field(default_factory=list)
    pythonCode: Optional[str] = None
    tool: Optional[str] = None

class ProcessSequence(BaseModel):
    source: str
    target: str
    condition: Optional[str] = None

class ProcessDefinition(BaseModel):
    processDefinitionName: str
    processDefinitionId: str
    description: str
    data: List[ProcessData] = []
    roles: List[ProcessRole] = []
    activities: List[ProcessActivity] = []
    sequences: List[ProcessSequence] = []

    def is_starting_activity(self, activity_id: str) -> bool:
        """
        Check if the given activity is the starting activity by verifying there's no previous activity.

        Args:
            activity_id (str): The ID of the activity to check.

        Returns:
            bool: True if it's the starting activity, False otherwise.
        """
        for sequence in self.sequences:
            if sequence.target == activity_id:
                return False
        return True

    def find_initial_activity(self) -> Optional[ProcessActivity]:
        """
        Finds and returns the initial activity of the process, which is the one with no incoming sequences.

        Returns:
            Optional[Activity]: The initial activity if found, None otherwise.
        """
        # Collect all target activity IDs from sequences
        target_activity_ids = {sequence.target for sequence in self.sequences}

        # Find an activity that is not a target of any sequence, implying it's the start
        for activity in self.activities:
            if activity.id not in target_activity_ids:
                return activity

        # If no such activity is found, return None
        return None

    def find_next_activities(self, current_activity_id: str) -> List[ProcessActivity]:
        """
        Finds and returns the next activities in the process based on the current activity ID.

        Args:
            current_activity_id (str): The ID of the current activity.

        Returns:
            List[ProcessActivity]: A list of the next activities if found, empty list otherwise.
        """
        next_activities_ids = [sequence.target for sequence in self.sequences if sequence.source == current_activity_id]
        return [activity for activity in self.activities if activity.id in next_activities_ids]

    def find_activity_by_id(self, activity_id: str) -> Optional[ProcessActivity]:
        for activity in self.activities:
            if activity.id == activity_id:
                return activity
        return None

def load_process_definition(definition_json: dict) -> ProcessDefinition:
    # definition_json = json.loads(definition_json)
    return ProcessDefinition(**definition_json)
# Example usage
if __name__ == "__main__":
    json_str = '{"processDefinitionName": "Example Process", "processDefinitionId": "example_process", "description": "제 프로세스 설명", "data": [{"name": "example data", "description": "example data description", "type": "Text"}], "roles": [{"name": "example role", "resolutionRule": "example rule"}], "activities": [{"name": "example activity", "id": "example_activity", "type": "ScriptActivity", "description": "activity description", "instruction": "activity instruction", "role": "example role", "inputData": [{"name": "example input data"}], "outputData": [{"name": "example output data"}], "checkpoints":["checkpoint 1"], "pythonCode": "import smtplib\\nfrom email.mime.multipart import MIMEMultipart\\nfrom email.mime.text import MIMEText\\n\\nsmtp = smtplib.SMTP(\'smtp.gmail.com\', 587)\\nsmtp.starttls()\\nsmtp.login(\'jinyoungj@gmail.com\', \'raqw nmmn xuuc bsyi\')\\n\\nmsg = MIMEMultipart()\\nmsg[\'Subject\'] = \'Test mail\'\\nmsg.attach(MIMEText(\'This is a test mail.\'))\\n\\nsmtp.sendmail(\'jinyoungj@gmail.com\', \'ohsy818@gmail.com\', msg.as_string())\\nsmtp.quit()"}], "sequences": [{"source": "activity_id_1", "target": "activity_id_2"}]}'
    process_definition = load_process_definition(json_str)
    print(process_definition.processDefinitionName)

    current_dir = Path(__file__).parent

    from code_executor import execute_python_code

    for activity in process_definition.activities:
        if activity.type == "ScriptActivity":
            print(activity)
            execute_python_code(activity.pythonCode, current_dir)
            output = execute_python_code(activity.pythonCode, current_dir)
            print(output)
    # End Generation Here
