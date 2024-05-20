from fastapi import HTTPException
from typing import List, Optional
import json
from langchain.prompts import PromptTemplate
from langchain.chat_models import ChatOpenAI
from langchain.output_parsers.json import SimpleJsonOutputParser
from langchain_core.runnables import RunnableLambda
from langserve import add_routes
from pydantic import BaseModel

from database import fetch_all_process_definitions



model = ChatOpenAI(model="gpt-4o")
vision_model = ChatOpenAI(model="gpt-4-vision-preview", max_tokens = 4096)

parser = SimpleJsonOutputParser()



prompt = PromptTemplate.from_template(
    """
    Now I'm going to create an interactive system that tells you the most similar process to run when you enter an image or message.

    - Process Definition List: {processDefinitionList}
    
    - Entered message: {message}
    
    - Entered image: {image}

    Based on the entered message or image information, return the most similar process definition.
    Return the result with the following description in markdown (three backticks):
    ```
    {{
        "processDefinitionList": [{{
            "id": "process definition id",
            "name": "process definition name",
            "description": "process definition description"
        }}]
    }}
    ```

                                      
    """)

import base64
from langchain.schema.messages import HumanMessage, AIMessage

def vision_model_chain(input):
    formatted_prompt = prompt.format(**input)
    
    msg = vision_model.invoke(
        [   AIMessage(
                content=formatted_prompt
            ),
            HumanMessage(
                content=[
                    {"type": "text", "text": input['answer']},
                    {
                        "type": "image_url",
                        "image_url": {
                           "url": input['image'],
                            'detail': 'high'
                        },
                    },
                ]
            )
        ]
    )
    return msg

class ProcessDefinition(BaseModel):
    id: str
    name: str
    description: Optional[str] = None

class ProcessResult(BaseModel):
    processDefinitionList: Optional[List[ProcessDefinition]] = None

def process_search(process_result_json: dict) -> str:
    try:
        process_result = ProcessResult(**process_result_json)
        # formatted_prompt = prompt.format(query=query, process_definitions=process_definitions)
        # response = model.invoke(formatted_prompt)
        # parsed_response = parser.parse(response)
        # return parsed_response
        
        return json.dumps(process_result_json)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def combine_input_with_process_definition(input):
    try:
        processDefinitionList = fetch_all_process_definitions()
        message = input.get("answer")
        image = input.get("image")
        
        return {
            "processDefinitionList": processDefinitionList,
            "message": message,
            "image": image
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

combine_input_with_process_definition_lambda = RunnableLambda(combine_input_with_process_definition)



def add_routes_to_app(app) :
    add_routes(
        app,
        combine_input_with_process_definition_lambda | prompt | model | parser | process_search,
        path="/process-search",
    )
    
    add_routes(
        app,
        combine_input_with_process_definition_lambda | vision_model_chain | parser | process_search,
        path="/vision-process-search",
    )



"""
http :8000/process-search/invoke input[answer]="휴가 신청하고 싶어."
"""
