from langchain.prompts import PromptTemplate
from langchain_openai import ChatOpenAI
from langchain.output_parsers.json import SimpleJsonOutputParser
from fastapi import HTTPException
from dotenv import load_dotenv
import json
import re
import httpx
import os
import logging

from database import fetch_todolist_by_proc_inst_id, upsert_workitem, upsert_chat_message, fetch_workitem_by_proc_inst_and_activity

load_dotenv()

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ChatOpenAI 객체 생성
model = ChatOpenAI(model="gpt-4o", streaming=True)

# parser 생성
class CustomJsonOutputParser(SimpleJsonOutputParser):
    def parse(self, text: str) -> dict:
        # Extract JSON from markdown if present
        match = re.search(r'```json\n(.*?)\n```', text, re.DOTALL)
        if match:
            text = match.group(1)
        else:
            raise ValueError("No JSON content found within backticks.")
        
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON: {str(e)}")

parser = CustomJsonOutputParser()

agent_request_prompt = PromptTemplate.from_template(
"""
Please create a request text for the agent using the information provided below. 

Previous Output: {previous_output}
Workitem: {workitem}

Generate a clear and concise request text that the agent can understand and process.
The text should include all relevant context from the previous output and workitem information.
"""
)

output_processing_prompt = PromptTemplate.from_template(
    """
Please convert the agent's response to the required output format.

Agent Response: {agent_response}

Convert the agent's response into the following JSON format:
{{
    "agent_result": {{
        "html": "<table>...</table> with <thead>, <tbody>, and clickable <a href> links for the 'link' column",
        "table_data": [
            {{
                "name": "...",
                "rating": ...,
                "reviews": ...,
                "link": "..."
            }},
            ...
        ]
    }}
}}

Requirements:
- The "html" field must contain a valid HTML table as a string. Use <thead> and <tbody> tags properly.
- In the HTML, render the "link" field as a clickable anchor tag (<a href="...">...</a>).
- The "table_data" array must use **snake_case keys only** (e.g., "name", "rating", "reviews", "link").
- Output must be a single JSON object with exactly one top-level key: "agent_result".
- Input data may not always be about accommodations, so apply formatting logic generically without assuming field semantics.

IMPORTANT: Return ONLY valid JSON without any comments, explanations, or additional text.
If a field value is not available from the agent response, use an empty string "" instead of adding comments.
"""
)

preprocessing_chain = (
    agent_request_prompt | model
)

output_processing_chain = (
    output_processing_prompt | model | parser
)

EXECUTION_SERVICE_URL = os.getenv("EXECUTION_SERVICE_URL", "http://execution-service:8000")

async def generate_agent_request_text(prev_workitem, current_workitem, tenant_id):
    """Step 1: LLM에게 output과 workitem 정보를 주고 에이전트 요청 텍스트 생성"""
    logger.info(f"Starting agent request text generation for workitem {current_workitem.id if current_workitem else 'None'}")
    try:
        worklist = fetch_todolist_by_proc_inst_id(prev_workitem["proc_inst_id"], tenant_id)
        previous_output = {}
        if worklist:
            for todo_item in worklist:
                if hasattr(todo_item, 'output') and todo_item.output is not None:
                    previous_output[todo_item.activity_id] = todo_item.output

        preprocessing_input = {
            "previous_output": previous_output,
            "workitem": current_workitem.dict() if current_workitem else {}
        }
        logger.info(f"Calling preprocessing chain with input keys: {list(preprocessing_input.keys())}")
        response = await preprocessing_chain.ainvoke(preprocessing_input)
        
        request_text = response.content if hasattr(response, 'content') else str(response)
        
        upsert_workitem({
            "id": current_workitem.id,
            "log": f"에이전트에게 전송할 메시지를 생성하였습니다..."
        }, tenant_id)
        
        logger.info(f"Successfully generated agent request text, length: {len(request_text)}")
        return request_text
    except Exception as e:
        logger.error(f"[ERROR] Failed to generate agent request text: {str(e)}")
        raise e

async def send_request_to_agent(request_text, agent_url, current_workitem, proc_inst_id):
    """Step 2: 생성된 텍스트를 A2A API에 전송"""
    logger.info(f"Starting agent request to {agent_url} for workitem {current_workitem.id if current_workitem else 'None'}")
    try:
        upsert_workitem({
            "id": current_workitem.id,
            "log": f"에이전트에게 메시지를 전송 중 입니다..."
        }, current_workitem.tenant_id)
        
        # execution-service의 API 엔드포인트 호출
        logger.info(f"Calling execution service at {EXECUTION_SERVICE_URL}/multi-agent/chat")
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{EXECUTION_SERVICE_URL}/multi-agent/chat",
                json={
                    "text": request_text,
                    "type": "a2a",
                    "chat_room_id": proc_inst_id,
                    "options": {
                        "agent_url": agent_url,
                        "task_id": current_workitem.id if current_workitem else None,
                        "is_stream": False
                    }
                },
                timeout=60.0
            )
            
            if response.status_code != 200:
                logger.error(f"Execution service returned status {response.status_code}: {response.text}")
                raise HTTPException(status_code=response.status_code, detail=response.text)
            
            agent_response = response.json()
            logger.info(f"Received response from execution service, status: {response.status_code}")
            
            # API 응답에서 실제 에이전트 응답 추출
            if isinstance(agent_response, dict) and 'response' in agent_response:
                agent_response = agent_response['response']
        
        upsert_workitem({
            "id": current_workitem.id,
            "log": f"에이전트에게 응답을 받았습니다..."
        }, current_workitem.tenant_id)
        
        logger.info(f"Successfully received agent response, length: {len(str(agent_response))}")
        return agent_response
    except Exception as e:
        logger.error(f"[ERROR] Failed to send request to agent: {str(e)}")
        raise e

async def process_agent_response(agent_response, current_workitem):
    """Step 3: A2A 응답을 LLM에게 전달하여 JSON 형식으로 반환"""
    logger.info(f"Starting agent response processing for workitem {current_workitem.id if current_workitem else 'None'}")
    try:
        upsert_workitem({
            "id": current_workitem.id,
            "log": f"에이전트에게 받은 응답을 기반으로 결과를 처리 중 입니다..."
        }, current_workitem.tenant_id)
        
        output_processing_input = {
            "agent_response": agent_response
        }
        logger.info(f"Calling output processing chain with agent response length: {len(str(agent_response))}")
        final_output = await output_processing_chain.ainvoke(output_processing_input)
        
        if hasattr(final_output, 'content'):
            final_output = final_output.content
        elif not isinstance(final_output, (dict, str)):
            final_output = str(final_output)
        
        if isinstance(final_output, str):
            lines = final_output.split('\n')
            cleaned_lines = []
            for line in lines:
                stripped_line = line.strip()
                if not stripped_line.startswith('//') and not stripped_line.startswith('#') and stripped_line:
                    cleaned_lines.append(line)
            final_output = '\n'.join(cleaned_lines)
            
            try:
                import json
                final_output = json.loads(final_output)
                logger.info("Successfully parsed JSON from agent response")
            except json.JSONDecodeError as e:
                logger.warning(f"[WARNING] JSON parsing failed, treating as string: {str(e)}")
                final_output = {}
        
        if isinstance(final_output, dict):
            if 'agent_result' in final_output:
                final_output = final_output['agent_result']
        
        upsert_workitem({
            "id": current_workitem.id,
            "status": "SUBMITTED",
            "consumer": None,
            "output": final_output,
            "log": f"Agent processing completed successfully"
        }, current_workitem.tenant_id)
        
        logger.info(f"Successfully processed agent response, output type: {type(final_output)}")
        return final_output
    except Exception as e:
        logger.error(f"[ERROR] Failed to process agent response: {str(e)}")
        raise e

async def handle_workitem_with_agent(prev_workitem, activity, agent):
    logger.info(f"Starting handle_workitem_with_agent for activity {activity.id if activity else 'None'}, agent: {agent.get('name') if agent else 'None'}")
    try:
        if isinstance(agent, list):
            for agent in agent:
                handle_workitem_with_agent(prev_workitem, activity, agent)
        else:
            proc_inst_id = prev_workitem["proc_inst_id"]
            tenant_id = prev_workitem["tenant_id"]
            activity_id = activity.id
            agent_url = agent.get("url")
            
            logger.info(f"Processing workitem - proc_inst_id: {proc_inst_id}, tenant_id: {tenant_id}, activity_id: {activity_id}, agent_url: {agent_url}")
            
            current_workitem = fetch_workitem_by_proc_inst_and_activity(proc_inst_id, activity_id, tenant_id)
            if not current_workitem:
                logger.error(f"[ERROR] Workitem not found for activity {activity_id}")
                return None
            
            # Step 1: 에이전트 요청 텍스트 생성
            request_text = None
            for attempt in range(3):
                try:
                    message_data = {
                        "role": "system",
                        "content": f"'{agent.get('name')}'가 업무를 시작합니다...",
                    }
                    upsert_chat_message(proc_inst_id, message_data, tenant_id)
                    request_text = await generate_agent_request_text(prev_workitem, current_workitem, tenant_id)
                    break
                except Exception as e:
                    if attempt == 2:
                        logger.error(f"[ERROR] Failed to generate request text after 3 attempts: {str(e)}")
                        return None
                    logger.warning(f"[WARNING] Request text generation failed, retrying... (attempt {attempt + 1}/3)")
            
            # Step 2: A2A에 요청 전송
            agent_response = None
            for attempt in range(3):
                try:
                    message_data = {
                        "role": "system",
                        "content": f"'{agent.get('name')}'에게 메시지를 전송 중 입니다...",
                    }
                    upsert_chat_message(proc_inst_id, message_data, tenant_id)
                    agent_response = await send_request_to_agent(request_text, agent_url, current_workitem, proc_inst_id)
                    break
                except Exception as e:
                    if attempt == 2:
                        logger.error(f"[ERROR] Failed to send request to agent after 3 attempts: {str(e)}")
                        return None
                    logger.warning(f"[WARNING] Agent request failed, retrying... (attempt {attempt + 1}/3)")
            
            # Step 3: 에이전트 응답 처리
            final_output = None
            for attempt in range(3):
                try:
                    message_data = {
                        "role": "system",
                        "content": f"'{agent.get('name')}'에게 받은 응답을 처리 중 입니다...",
                    }
                    upsert_chat_message(proc_inst_id, message_data, tenant_id)
                    final_output = await process_agent_response(agent_response, current_workitem)
                    break
                except Exception as e:
                    if attempt == 2:
                        logger.error(f"[ERROR] Failed to process agent response after 3 attempts: {str(e)}")
                        return None
                    logger.warning(f"[WARNING] Agent response processing failed, retrying... (attempt {attempt + 1}/3)")
            
            message_data = {
                "role": "system",
                "content": f"'{agent.get('name')}' 검색 결과입니다.",
            }
            upsert_chat_message(proc_inst_id, message_data, tenant_id)
            
            message_data = {
                "role": "agent",
                "name": f"[A2A 호출] {agent.get('name')} 검색 결과",
                "content": f"{agent.get('name')} 검색 결과입니다.",
                "jsonContent": final_output.get("table_data"),
                "htmlContent": final_output.get("html"),
                "contentType": "html" if final_output.get("html") else "text"
            }
            upsert_chat_message(proc_inst_id, message_data, tenant_id)
            
            logger.info(f"Successfully completed handle_workitem_with_agent for activity {activity_id}")
            return final_output
            
    except Exception as e:
        if 'current_workitem' in locals() and current_workitem:
            upsert_workitem({
                "id": current_workitem.id,
                "status": "DONE",
                "consumer": None,
                "log": f"Agent processing failed for activity {activity.id}: {str(e)}"
            }, tenant_id)
            logger.error(f"[ERROR] Agent processing failed for activity {activity.id}: {str(e)}")

        logger.error(f"[ERROR] Agent processing failed for activity {activity.id}: {str(e)}")
        return None 