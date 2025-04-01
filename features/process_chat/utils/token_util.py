import os
from fastapi import Request, HTTPException

class TokenUtil:
    @staticmethod
    def getTokenFromHeader(request: Request, vendor: str) -> str:
        """
        지정된 vendor에 대한 API 키를 가져옵니다.
        먼저 Authorization 헤더에서 Bearer 토큰을 확인하고,
        없으면 해당 vendor의 환경 변수 (예: OPENAI_API_KEY)를 확인합니다.
        """
        if vendor == "ollama":
            return ""


        api_key = None
        
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            api_key = auth_header.split(" ")[1]

        if not api_key:
            env_var_name = f"{vendor.upper()}_API_KEY"
            api_key = os.getenv(env_var_name)

        if not api_key:
            raise HTTPException(
                status_code=401, 
                detail=f"{vendor.capitalize()} API key not found in Authorization header or environment variables."
            )
            
        return api_key