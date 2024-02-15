from fastapi import FastAPI, HTTPException, Body
from langchain.prompts import PromptTemplate
from langchain.chat_models import ChatOpenAI
from langserve import add_routes
from fastapi.staticfiles import StaticFiles
from langchain_core.runnables import RunnableLambda
from database import fetch_all_process_definition_ids, execute_sql, generate_create_statement_for_table
import re
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

app = FastAPI(
    title="LangChain Server",
    version="1.0",
    description="A simple api server using Langchain's Runnable interfaces",
)

# CORS 미들웨어 추가
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 모든 출처 허용
    allow_credentials=True,
    allow_methods=["*"],  # 모든 HTTP 메서드 허용
    allow_headers=["*"],  # 모든 HTTP 헤더 허용
)

app.mount("/static", StaticFiles(directory="static"), name="static")

import os
openai_api_key = os.getenv("OPENAI_API_KEY")



# 1. OpenAI Chat Model 생성
model = ChatOpenAI(openai_api_key=openai_api_key)

prompt = PromptTemplate.from_template(
    """
     아래의 데이터베이스 스키마를 참고하여  "{var_name}" 의 값을 얻어올 수 있도록 하는 SQL을 생성해줘:

  
    - Existing Table Schemas:
    {process_table_schema}
    - 규칙은 이러함:
    {resolution_rule}

    The result should be created in SQL within the following markdown:
    ```
      ...SQL..
    ```
                                      
    """)


def combine_input(input):
    
    var_name = input.get('var_name')  # 'process_definition_id'bytes: \xedbytes:\x82\xa4에 대한bytes: \xec\xa0bytes:\x91bytes:\xea\xb7bytes:\xbc 추가
    resolution_rule = input.get('resolution_rule')  # 'process_definition_id'bytes: \xedbytes:\x82\xa4에 대한bytes: \xec\xa0bytes:\x91bytes:\xea\xb7bytes:\xbc 추가

    if not var_name:
        raise HTTPException(status_code=404, detail="No process Variable name was provided.")
    
    
    # processDefinitionJson = fetch_process_definition(process_definition_id)

    # if not processDefinitionJson:
    #     raise HTTPException(status_code=404, detail=f"No process definition where definition id = {process_definition_id}")
    
    process_table_schemas = []
    for process_definition_id in fetch_all_process_definition_ids():
        process_table_schema = generate_create_statement_for_table(process_definition_id)
        process_table_schemas.append(process_table_schema)
    
    process_table_schema = "\n".join(process_table_schemas)

    return {
        "var_name": var_name,
        "resolution_rule": resolution_rule,
        "process_table_schema": process_table_schema
    }
    

combine_input_with_process_definition_lambda = RunnableLambda(combine_input)

def extract_markdown_code_blocks(markdown_text):
    # Extract code blocks from markdown text and concatenate them into a single string
    code_blocks = re.findall(r"```(?:sql)?\n?(.*?)\n?```", markdown_text.content, re.DOTALL)
    single_string_result = "\n".join(code_blocks)
    return single_string_result



add_routes(
    app,
    combine_input_with_process_definition_lambda | prompt | model | extract_markdown_code_blocks,
    path="/process-var-sql",
)

from fastapi import APIRouter

router = APIRouter()

@router.post("/execute-sql")  # API 경로 설정
async def execute_sql_api(query: dict = Body(...)):
    sql_query = query.get("sql_query", "")  # 'sql_query' 키로부터 SQL 쿼리 문자열 추출
    try:
        result = execute_sql(sql_query)  # database.py의 execute_sql 함수 사용
        return {"success": True, "data": result}
    except Exception as e:
        return {"success": False, "error": str(e)}

app.include_router(router)  # 앱에 라우터 포함

# 호출 예시
# http POST :8001/execute-sql sql_query="SELECT * FROM table_name"
# http POST :8001/execute-sql Content-Type:application/json sql_query="SELECT * FROM table_name"

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="localhost", port=8001)

"""
http :8001/process-var-sql/invoke input[var_name]="total_vacation_days_remains" input[resolution_rule]="vacation_addition 테이블의 전체 휴가일수에서 vacation_request 의 사용일수를 제외함. 그리고 10일은 기본적으로 추가"
"""