from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from openai import OpenAI
import base64
import uvicorn

app = FastAPI()

class ImageData(BaseModel):
    image_base64: str

client = OpenAI()

@app.post("/process-image/")
async def process_image(data: ImageData):
    try:
        response = client.chat.completions.create(
            model="gpt-4-vision-preview",
            max_tokens=4096,
            temperature=0,
            messages=[
                {'role': 'system', 'content': """
너는 문서장이야. 그게하 사은 아니고 비적 문서상태가하라도을 하는이고 그어가는일이야. 제출한 문서의트가 일정한지,여기 내기가른지, 번호 서식 등이 일정한지,이 일정한지,의름이 정한지, 개조식인지 서식인지에라 일성이 있는지, 일된 문체인지 (구어체인지 문어체인지) 등을가해. 비적된 문서라면고정적으로가하고,된 문서에 대해서만 지적해. 지적 사 중 가장한서대로하여 3개를지 않도록 해.     
                """},
                {
                    "role": "user",
                    "content": [        
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{data.image_base64}",
                                'detail': 'high'
                            }
                        }, 
                        {'type': 'text', 'text': '\n이 문서에 잘못된 점을 지적해주세요.\n'}
                    ],
                }
            ],
        )
        return {"message": response.choices[0].message.content}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


from fastapi.staticfiles import StaticFiles

# 정적 파일 디렉토리를 마운트합니다. 이 경우, 'static' 폴더를 사용합니다.
app.mount("/static", StaticFiles(directory="static"), name="static")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8003)
