from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pathlib import Path
import openai
import re

def create_audio_stream(input_text, model="tts-1", voice="alloy", speed=1.5):
    # Split the input text by both periods and commas
    segments = re.split(r'[.,]', input_text)
    for i, segment in enumerate(segments, start=1):
        if segment.strip():  # Ensure segment is not just whitespace
            speech_file_path = Path(__file__).parent / f"speech_{i}.mp3"
            response = openai.audio.speech.create(
                model=model,
                voice=voice,
                speed=speed,
                input=segment.strip()
            )
            response.stream_to_file(speech_file_path)
            with open(speech_file_path, 'rb') as file:
                yield file.read()

app = FastAPI()

input_text = "현재의 프로세스 는 영업활동프로세스이며, 진행상태는 영업 제안서 작성단계에서 정체가 발생하고 있으며 담당자는 장진영입니다. 영업 담당자는 강서구입니다."

@app.get("/stream")
async def stream_audio():
    return StreamingResponse(create_audio_stream(input_text), media_type='audio/webm')

from fastapi.staticfiles import StaticFiles

app.mount("/static", StaticFiles(directory="static"), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
    app.run()
