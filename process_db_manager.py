from fastapi import HTTPException, Request
from langchain.prompts import PromptTemplate
from langchain_openai import ChatOpenAI
from langserve import add_routes
from langchain_core.runnables import RunnableLambda
from database import fetch_process_definition, execute_sql, generate_create_statement_for_table, insert_sample_data
import re
import os

# 1. OpenAI Chat Model 생성
openai_api_key = os.getenv("OPENAI_API_KEY")
model = ChatOpenAI(openai_api_key=openai_api_key)

prompt = PromptTemplate.from_template(
    """
  You are a database administrator. Generate the DDL to store the following process definition's data value in a supabase's postgres DB. 
  Write the DDL in such a way that it modifies the table (ALTER statement) if it already exists, and creates it if it does not.
  Include only newly added or deleted columns in ALTER statements and exclude columns that have not changed or already exist.
  DO NOT create any other objects like triggers and functions except table.
  DO USE the same name for table with the process definition id.


    For example, if there is the following process:


    
    {{
        "processDefinitionId": "vacation-request",
        "data": [
            {{
                "name": "reason",
                "description": "reason for requesting vacation",
                "type": "Text"
            }},
            {{
                "name": "start date",
                "description": "start date of the vacation",
                "type": "Date"
            }},
            {{
                "name": "휴가 복귀일",
                "description": "date of return from vacation",
                "type": "Date"
            }}
        ]
        ...
    }}

    Sample SQL looks like this:

    create table vacation_request(
        -- fixed parts 

        proc_inst_id text primary key,
        proc_inst_name text,
        current_activity_ids text array,
        current_user_ids text array,
        role_bindings jsonb
        
        -- fields for the process variables defined in this process definition    

        reason text,
        start_date date, // Replace with _ if there is a space.
        휴가_복귀일 date // Replace with _ if there is a space.
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


async def combine_input_with_process_definition(input):
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


# Drop Table SQL 생성 함수
def generate_drop_table_sql(input):
    process_definition_id = input.get('process_definition_id')
    if not process_definition_id:
        raise HTTPException(status_code=404, detail="No process definition ID was provided.")
    
    drop_table_sql = f"DROP TABLE IF EXISTS {process_definition_id};"
    return {"drop_table_sql": drop_table_sql}

generate_drop_table_sql_lambda = RunnableLambda(generate_drop_table_sql)

# Drop Table SQL 실행 함수
def execute_drop_table_sql(input):
    drop_table_sql = input.get('drop_table_sql')
    if not drop_table_sql:
        raise HTTPException(status_code=400, detail="No SQL command to execute.")
    
    execute_sql(drop_table_sql)
    return {"status": "success", "message": f"Table {input.get('process_definition_id')} dropped successfully."}

execute_drop_table_sql_lambda = RunnableLambda(execute_drop_table_sql)


def add_routes_to_app(app) :
    add_routes(
        app,
        combine_input_with_process_definition_lambda | prompt | model | extract_markdown_code_blocks | execute_sql,
        path="/process-db-schema",
    )

    add_routes(
        app,
        generate_drop_table_sql_lambda | execute_drop_table_sql_lambda,
        path="/drop-process-table",
    )
    
    app.add_api_route("/insert-sample", insert_sample_data, methods=["POST"])
    
    

"""
http :8000/process-db-schema/invoke input[process_definition_id]="company_entrance"
http :8000/process-db-schema/invoke input[process_definition_id]="vacation_request"
http :8000/process-db-schema/invoke input[process_definition_id]="vacation_addition"

http :8000/drop-process-table/invoke input[process_definition_id]="issue_management_process"

"""