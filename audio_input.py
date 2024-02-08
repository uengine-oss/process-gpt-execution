# audio_input.py
from fastapi import FastAPI, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
import uuid
import openai
import os

app = FastAPI()

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 모든메인용 (보상 주의 필요)
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/upload")
async def upload_audio(audio: UploadFile = File(...)):
    filename = str(uuid.uuid4())
    file_location = f"uploads/{filename}.mp3"
    with open(file_location, "wb+") as file_object:
        file_object.write(audio.file.read())
    

    # OpenAI Whisper API를 이용하여스크트 생성
    with open(file_location, "rb") as audio_file:
        transcript_response = openai.audio.transcriptions.create(
            model="whisper-1", 
            file=audio_file,
            response_format="text"
        )

        os.remove(file_location)  # 파일 삭제

        return {
            "info": f"file '{audio.filename}' saved at '{file_location}'",
            "transcript": transcript_response  # 수정된 부분:트 반환
        }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8003)
