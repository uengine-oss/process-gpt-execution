from database import insert_usage
from fastapi import HTTPException

def is_service_available(tenant_id: str) -> bool:
    try:
        # 서비스가 사용 가능한지 확인하는 로직을 여기에 추가
        return True
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"제한 확인 중 오류: {str(e)}") from e
    
def Usage(raw_data):
    try:
        if not is_service_available(raw_data.get("tenantId", raw_data.get("tenant_id", "")).strip()):
            raise HTTPException(status_code=403, detail="서비스가 현재 사용 불가능합니다.")
        
        insert_usage({
            "service_id": raw_data.get("serviceId", raw_data.get("service_id", "")).strip(),
            "tenant_id": raw_data.get("tenantId", raw_data.get("tenant_id", "")).strip(),
            "recorded_at": raw_data.get("recordedAt", raw_data.get("recorded_at", "")).strip(),
            "quantity": raw_data.get("quantity", 0),
            "model": raw_data.get("model", "").strip(),
            "user_id": raw_data.get("userId", raw_data.get("user_id", "")).strip(),
            "metadata": raw_data.get("metadata", {})
        })
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

"""
DB DDL

CREATE TABLE public.service (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,      -- 서비스 ID
    name TEXT NOT NULL,                                 -- 서비스명
    description TEXT,                                   -- 서비스 설명
    unit TEXT NOT NULL,                                 -- 서비스의 단위 ('tokens', 'requests', ...)
    category TEXT NOT NULL,                             -- 서비스 분류 ('llm', 'compute', ...)
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),  -- 서비스 생성날짜
    tenant_id TEXT REFERENCES tenants(id)               -- 테넌트
);

CREATE TABLE public.usage (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,            -- 사용량 ID
    service_id UUID REFERENCES service(id),                   -- (필수)서비스ID
    tenant_id TEXT NOT NULL REFERENCES tenants(id),           -- (필수)테넌트
    recorded_at TIMESTAMP WITH TIME ZONE NOT NULL,            -- (필수)실제 사용 시점
    quantity DECIMAL(12,4) NOT NULL,                          -- (필수)사용 양(토큰, 호출수..)  
    model TEXT,                                               -- 사용모델(GPT-4, .. )
    user_id TEXT,                                             -- 사용자  
    metadata JSONB,                                           -- 추가 정보 저장
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()         -- 생성일(자동 생성)
);

CREATE INDEX idx_usage_tenant_service_date
   ON public.usage (tenant_id, service_id, recorded_at);
"""

"""
from Usage import Usage, is_service_available

# 서비스 사용 가능 여부 확인 예시
tenant_id = "example_tenant_id"
if is_service_available(tenant_id):
    print("서비스를 사용할 수 있습니다.")
else:
    print("서비스를 사용할 수 없습니다.")

# 사용 예시
raw_data = { 
    "tenantId": "테넌트 ID", #필수
    "recordedAt": "2023-10-01T12:00:00+09:00", #필수
    "quantity": "100", #필수
    "model": "GPT-4", #필수
    "userId": "사용자 ID", 
    "serviceId": "서비스 ID",
    "metadata": {
        "used_for": "chat",
        "used_for_id": "1234567890",
        "used_for_name": "AI 생성 처리 채팅"
    }
}
Usage(raw_data)
"""