from fastapi import FastAPI, HTTPException
from langchain.prompts import PromptTemplate
from langchain.chat_models import ChatOpenAI
from langserve import add_routes
from fastapi.staticfiles import StaticFiles
from langchain_core.runnables import RunnableLambda
from database import fetch_process_definition, execute_sql, generate_create_statement_for_table
import re

import psycopg2
from psycopg2.extras import RealDictCursor


app = FastAPI(
    title="LangChain Server",
    version="1.0",
    description="A simple api server using Langchain's Runnable interfaces",
)

app.mount("/static", StaticFiles(directory="static"), name="static")

import os
openai_api_key = os.getenv("OPENAI_API_KEY")



# 1. OpenAI Chat Model 생성
model = ChatOpenAI(openai_api_key=openai_api_key)

prompt = PromptTemplate.from_template(
    """
  You are a database administrator. Generate the DDL to store the following process definition's data value in a supabase's postgres DB. 
  Write the DDL in such a way that it modifies the table if it already exists, and creates it if it does not.
  DO NOT create any other objects like triggers and functions except table.

    For example, if there is the following process:


    
    {{
        "processDefinitionId": "vacation-request",
        "data": [
            {{
                "name": "reason",
                "description": "reason for requesting vacation",
                "type": "Text"
            }}
        ]
        ...
    }}

    Sample SQL looks like this:

    create table vacation_request(
        -- fixed parts 

        proc_inst_id text primary key,  
        proc_inst_id text primary key,
        proc_inst_name text,
        current_activity_ids text array,
        role_bindings jsonb
        
        -- fields for the process variables defined in this process definition    

        reason text,
        start_date date,
        return_date date
    )


    Generate the DDL for the following process definition:


    - Process Definition:
    {processDefinitionJson}

    - Existing Table Schema:
    {process_table_schema}

    The result should be created in SQL within the following markdown:

    ```
        ..DDL SQL..
    
    ```                       
                                      
    """)


def combine_input_with_process_definition(input):
    # 프로세스 인스턴스를 DB에서 검색
    
    processDefinitionJson = None

    process_definition_id = input.get('process_definition_id')  # 'process_definition_id'bytes: \xedbytes:\x82\xa4에 대한bytes: \xec\xa0bytes:\x91bytes:\xea\xb7bytes:\xbc 추가

    if not process_definition_id:
        raise HTTPException(status_code=404, detail="No process definition ID was provided.")
    
    
    processDefinitionJson = fetch_process_definition(process_definition_id)

    if not processDefinitionJson:
        raise HTTPException(status_code=404, detail=f"No process definition where definition id = {process_definition_id}")
    
    process_table_schema = generate_create_statement_for_table(process_definition_id)

    return {
        "processDefinitionJson": processDefinitionJson,
        "process_table_schema": process_table_schema
    }
    

combine_input_with_process_definition_lambda = RunnableLambda(combine_input_with_process_definition)

def extract_markdown_code_blocks(markdown_text):
    # Extract code blocks from markdown text and concatenate them into a single string
    code_blocks = re.findall(r"```(?:sql)?\n?(.*?)\n?```", markdown_text.content, re.DOTALL)
    single_string_result = "\n".join(code_blocks)
    return single_string_result



add_routes(
    app,
    combine_input_with_process_definition_lambda | prompt | model | extract_markdown_code_blocks | execute_sql,
    path="/process-db-schema",
)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="localhost", port=8001)

"""
http :8001/process-db-schema/invoke input[process_definition_id]="company_entrance"
http :8001/process-db-schema/invoke input[process_definition_id]="vacation_request"
http :8001/process-db-schema/invoke input[process_definition_id]="vacation_addition"
"""