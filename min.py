from fastapi import FastAPI
from langchain.chat_models import ChatOpenAI
from langchain.prompts import ChatPromptTemplate
from langchain.schema.output_parser import StrOutputParser
from langchain.output_parsers.json import SimpleJsonOutputParser
from langserve import add_routes

# Prompt Template 생성
prompt_template = ChatPromptTemplate.from_template(
    """
    다음주제에 대한 프로세스 정의를 생성해줘: {topic}
    다음 json format 으로 리턴해:

    {{
        activities: {{
            id: "액티비티 id",
            name: "액티비티 이름",
            description: "액티티비 설명",
            type: "ScriptActivity" | "HumanActivity",
            pythonCode: "python code to execute the script activity"
        }}
    }}  
    """
    )

# OpenAI 언어 모델 인스턴스 생성
model = ChatOpenAI(model="gpt-3.5-turbo")

# 출력 파서 생성
output_parser = SimpleJsonOutputParser()


from pydantic import BaseModel, Field

class Activity(BaseModel):
    id: str = Field(..., alias="id")
    name: str = Field(..., alias="name")
    description: str = Field(..., alias="description")
    type: str = Field(..., alias="type")
    pythonCode: str = Field(..., alias="pythonCode")

class ProcessDefinition(BaseModel):
    activities: Activity



def extract_script_activities(process_definition: ProcessDefinition) -> str:
    script_activities = [
        activity.pythonCode for activity in process_definition.activities if activity.type == "ScriptActivity"
    ]
    return "\n".join(script_activities)

# LCEL 체인에 함수 적용
chain = prompt_template | model | output_parser | extract_script_activities


# FastAPI 앱 정의
app = FastAPI()

# LCEL 체인을 REST API 경로에 연결
add_routes(app, chain, path="/generate_joke")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="localhost", port=8000)
        

