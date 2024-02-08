from fastapi import FastAPI
from langchain.llms import OpenAI
from langchain.prompts import ChatPromptTemplate
from langchain.schema.output_parser import StrOutputParser
from langserve import add_routes

# Prompt Template 생성
prompt_template = ChatPromptTemplate.from_template("tell me a short joke about {topic}")

# OpenAI 언어 모델 인스턴스 생성
model = OpenAI(model="gpt-3.5-turbo")

# 출력 파서 생성
output_parser = StrOutputParser()

# LCEL을 사용하여 컴포넌트 연결
chain = prompt_template | model | output_parser

# FastAPI 앱 정의
app = FastAPI()

# LCEL 체인을 REST API 경로에 연결
add_routes(app, chain, path="/generate_joke")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="localhost", port=8000)