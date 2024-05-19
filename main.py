from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from process_engine import add_routes_to_app as add_process_routes_to_app
from process_db_manager import add_routes_to_app as add_db_manager_routes_to_app
from process_image import add_routes_to_app as add_image_routes_to_app
from process_var_sql_gen import add_routes_to_app as add_var_sql_gen_routes_to_app
from audio_input import add_routes_to_app as add_audio_input_routes_to_app
from min import add_routes_to_app as add_min_routes_to_app

import os

os.environ["PYTHONIOENCODING"] = "utf-8"

#캐시 적용
#from langchain.cache import InMemoryCache
from langchain.globals import set_llm_cache

# set_llm_cache(InMemoryCache())
from langchain.cache import SQLiteCache

set_llm_cache(SQLiteCache(database_path=".langchain.db"))


app = FastAPI(
    title="LangChain Server",
    version="1.0",
    description="A simple api server using Langchain's Runnable interfaces",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 모든 출처 허용
    allow_credentials=True,
    allow_methods=["*"],  # 모든 HTTP 메서드 허용
    allow_headers=["*"],  # 모든 HTTP 헤더 허용
)


app.mount("/static", StaticFiles(directory="static"), name="static")


add_process_routes_to_app(app)
add_db_manager_routes_to_app(app)
add_image_routes_to_app(app)
add_var_sql_gen_routes_to_app(app)
add_audio_input_routes_to_app(app)
add_min_routes_to_app(app)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="localhost", port=8000)