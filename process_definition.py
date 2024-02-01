import json
from pathlib import Path
from typing import Any, Dict, List, Union



class ProcessData:
    def __init__(self, data: Dict[str, str]):
        self.name = data.get("name")
        self.description = data.get("description")
        self.type = data.get("type")

class ProcessRole:
    def __init__(self, role: Dict[str, str]):
        self.name = role.get("name")
        self.resolutionRule = role.get("resolutionRule")

class ProcessActivity:
    def __init__(self, activity: Dict[str, Union[str, List[str]]]):
        self.name = activity.get("name")
        self.id = activity.get("id")
        self.type = activity.get("type")
        self.description = activity.get("description")
        self.instruction = activity.get("instruction")
        self.role = activity.get("role")
        self.inputData = activity.get("inputData", [])
        self.outputData = activity.get("outputData", [])
        self.checkpoints = activity.get("checkpoints", [])
        self.py_code = activity.get("pythonCode", [])

class ProcessSequence:
    def __init__(self, sequence: Dict[str, str]):
        self.source = sequence.get("source")
        self.target = sequence.get("target")
        
class ProcessDefinition:
    def __init__(self, definition: Dict[str, Any]):
        self.name = definition.get("processDefinitionName")
        self.id = definition.get("processDefinitionId")
        self.description = definition.get("description")
        self.data = [ProcessData(data) for data in definition.get("data", [])]
        self.roles = [ProcessRole(role) for role in definition.get("roles", [])]
        self.activities = [ProcessActivity(activity) for activity in definition.get("activities", [])]
        self.sequences = [ProcessSequence(sequence) for sequence in definition.get("sequences", [])]


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

    from typing import Optional
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

def load_process_definition(json_str: str) -> ProcessDefinition:
    definition = json.loads(json_str)
    return ProcessDefinition(definition)

# Example usage
if __name__ == "__main__":
    json_str = '{"processDefinitionName": "Example Process", "processDefinitionId": "example_process", "description": "예제 프로세스 설명", "data": [{"name": "example data", "description": "example data description", "type": "Text"}], "roles": [{"name": "example role", "resolutionRule": "example rule"}], "activities": [{"name": "example activity", "id": "example_activity", "type": "ScriptActivity", "description": "activity description", "instruction": "activity instruction", "role": "example role", "inputData": [{"name": "example input data"}], "outputData": [{"name": "example output data"}], "checkpoints":["checkpoint 1"], "pythonCode": "import smtplib\\nfrom email.mime.multipart import MIMEMultipart\\nfrom email.mime.text import MIMEText\\n\\nsmtp = smtplib.SMTP(\'smtp.gmail.com\', 587)\\nsmtp.starttls()\\nsmtp.login(\'jinyoungj@gmail.com\', \'raqw nmmn xuuc bsyi\')\\n\\nmsg = MIMEMultipart()\\nmsg[\'Subject\'] = \'Test mail\'\\nmsg.attach(MIMEText(\'This is a test mail.\'))\\n\\nsmtp.sendmail(\'jinyoungj@gmail.com\', \'jyjang@uengine.org\', msg.as_string())\\nsmtp.quit()"}], "sequences": [{"source": "activity_id_1", "target": "activity_id_2"}]}'
    process_definition = load_process_definition(json_str)
    print(process_definition.name)

    current_dir = Path(__file__).parent

    from code_executor import execute_python_code

    for activity in process_definition.activities:
        if activity.type == "ScriptActivity":
            print(activity)
            execute_python_code(activity.py_code, current_dir)
            output = execute_python_code(activity.py_code, current_dir)
            print(output)
    # End Generation Here
