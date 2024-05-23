from fastapi import HTTPException, Request
from langchain.prompts import PromptTemplate
from langchain_community.chat_models import ChatOpenAI
from langserve import add_routes
from langchain_core.runnables import RunnableLambda
from database import fetch_all_process_definition_ids, execute_sql, generate_create_statement_for_table
import re
import json
from decimal import Decimal
from langchain.schema.output_parser import StrOutputParser
from datetime import date
from pathlib import Path
import openai

import os
openai_api_key = os.getenv("OPENAI_API_KEY")



# 1. OpenAI Chat Model 생성
model = ChatOpenAI(model="gpt-4o", streaming=True)

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

def default(obj):
    if isinstance(obj, Decimal):
        return str(obj)  # 또는 float(obj)로 변환
    if isinstance(obj, date):
        return obj.isoformat()  # date 객체를 ISO 포맷 문자열로 변환
    raise TypeError(f"Object of type {obj.__class__.__name__} is not JSON serializable")

def runsql(sql):
    result = execute_sql(sql)
    return {"result": json.dumps(result, default=default)}

def extract_html_table(markdown_text):
    # Extract HTML table code block from markdown text
    start = markdown_text.find("```html")
    end = markdown_text.find("```", start + 1)
    if start != -1 and end != -1:
        return markdown_text[start + 7:end].strip()
    return markdown_text

def clean_html_string(html_string):
    # \n 제거
    cleaned_string = html_string.replace("\n", "")
    # \"를 "로 변환
    cleaned_string = cleaned_string.replace('\\"', '"')
    return cleaned_string

draw_table_prompt = PromptTemplate.from_template(
    """
        Please create a html table with this data (<table> element only. DO NOT use escape characters like '\"' or '\n'):
        {result}                                         
    """
    )

describe_result_prompt = PromptTemplate.from_template(
    """
        Please describe the process instance data like this:

        example: 현재의 프로세스는 영업활동프로세스이며, 진행상태는 영업 제안서 작성단계에서 정체가 발생하고 있으며 담당자는 장진영입니다. 영업 담당자는 강서구입니다. 
        (현재 진행단계 설명, 진행상태 설명, 각 담당자 등 프로세스 인스턴스 테이블에서 얻어진 다양한 정보를 바탕으로 설명)

        * 만약 데이터가 오류인 경우는, 그냥 해당 정보가 없다고 답해.
        * 인스턴스 ID는 설명할 필요 없어.
        * 결과는 개조식이 아닌 서술식으로 설명해

        process data:
        {result}     

        * please describe in Korean Language                                    
    """
    )

from langchain.schema.runnable import RunnablePassthrough

def generate_speech(part):
    speech_file_path = Path(__file__).parent / "speech.mp3"
    response = openai.audio.speech.create(
        model="tts-1",
        voice="nova",  # alloy
        speed=1.2,
        input=part
    )
    response.stream_to_file(speech_file_path)
    with open(speech_file_path, 'rb') as file:
        return file.read()
    
def create_audio_stream(input_text):

    chain = (
        combine_input_with_process_definition_lambda | 
        prompt | 
        model | 
        extract_markdown_code_blocks | 
        runsql | 
        describe_result_prompt | 
        model | 
        StrOutputParser()     
    )


    word = ""
    for chunk in chain.stream({"var_name": input_text, "resolution_rule": "    요청된 프로세스 정의와 해당 건에 대한 프로세스 인스턴스 정보를 읽어야. 가능한 하나의 테이블에서 데이터를 조회. UNION 사용하지 말것."}):
        word += chunk

        if ',' in word or '.' in word:
            # Find the position of the first comma or period
            first_comma = word.find(',')
            first_period = word.find('.')
            
            # Determine the earliest punctuation mark
            if first_comma == -1:
                split_index = first_period
            elif first_period == -1:
                split_index = first_comma
            else:
                split_index = min(first_comma, first_period)
            
            # Split the word at the earliest punctuation mark
            part = word[:split_index]
            word = word[split_index+1:]
        
            yield generate_speech(part)
        
    #result = chain.invoke({"var_name": input_text, "resolution_rule": "    요청된 프로세스 정의와 해당 건에 대한 프로세스 인스턴스 정보를 읽어야. 가능한 하나의 테이블에서 데이터를 조회. UNION 사용하지 말것."})


from fastapi.responses import StreamingResponse

#input_text = "현재 영업활동 프로세스 인스턴스들의 상태를 알려줘"

async def stream_audio(request: Request):
    body = await request.json()
    input_text = body.get("query")
    return StreamingResponse(create_audio_stream(input_text), media_type='audio/webm')

def add_routes_to_app(app) :
    add_routes(
        app,
        combine_input_with_process_definition_lambda | prompt | model | extract_markdown_code_blocks,
        path="/process-var-sql",
    )

    add_routes(
        app,
        combine_input_with_process_definition_lambda | prompt | model | extract_markdown_code_blocks | runsql | draw_table_prompt | model | StrOutputParser() | extract_html_table | clean_html_string,
        path="/process-data-query",
    )
   
    app.add_api_route("/audio-stream", stream_audio, methods=["POST"])



 
"""
http :8000/process-data-query/invoke input[var_name]="모든 입사 지원자를 출력해줘"
http :8000/process-data-query/invoke input[var_name]="sw분야 지원한 입사지원자 목록" 
http :8000/process-var-sql/invoke input[var_name]="total_vacation_days_remains" input[resolution_rule]="vacation_addition 테이블의 전체 휴가일수에서 vacation_request 의 사용일수를 제외함. 그리고 10일은 기본적으로 추가"
"""