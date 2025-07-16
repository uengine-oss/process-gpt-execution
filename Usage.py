from database import insert_usage, get_service_list, get_available_credits
from fastapi import HTTPException

def is_service_available(tenant_id: str) -> bool:
    try:
        # available_credits = get_available_credits(tenant_id)
        # return available_credits['remaining_credit'] > 0
        return True
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"제한 확인 중 오류: {str(e)}") from e

def get_service_list(category: str):
    try:
        # 서비스 목록을 조회하는 로직을 여기에 추가
        return get_service_list(category)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"서비스 목록 조회 중 오류: {str(e)}") from e

def get_usage_format():
    return { 
        "used_at": "", #필수 (실제 시작 시점)
        "model": "", #필수 (모델명)
        "user_id": "", 
        "service_master_id": "",
        "quantity": 0, #필수 (총 토크수, 총 호출 수)
        "metadata": {
            "request": {
                "tokens": 0,
                "creditPerUnit": 0
            },
            "cachedRequest": {
                "tokens": 0,
                "creditPerUnit": 0
            },
            "response": {
                "tokens": 0,
                "creditPerUnit": 0
            },
            "usedFor": "",
            "usedForId": "",
            "usedForName": ""
        }
    }
    
    
def usage(raw_data):
    try:
        if not is_service_available(raw_data.get("tenantId", raw_data.get("tenant_id", "")).strip()):
            raise HTTPException(status_code=403, detail="존재하지 않은 테넌트입니다.")
        
        insert_usage({
            "service_master_id": raw_data.get("service_master_id", raw_data.get("service_master_id", "")).strip(),
            "tenant_id": raw_data.get("tenantId", raw_data.get("tenant_id", "")).strip(),
            "quantity": raw_data.get("quantity", 0),
            "model": raw_data.get("model", "").strip(),
            "user_id": raw_data.get("userId", raw_data.get("user_id", "")).strip(),
            "used_at": raw_data.get("used_at", raw_data.get("used_at", "")).strip(),
            "metadata": raw_data.get("metadata", {})
        })
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

"""
DB DDL

#service_mater (서비스 관리 테이블) - 해당 테이블 기
CREATE TABLE public.service_mater (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,      -- 고유 ID
    service_id UUID REFERENCES service(id),             -- 서비스 ID
    service_rate_id UUID REFERENCES service_rate(id),   -- 서비스 
    version DECIMAL(10,1) NOT NULL                      -- 버전
);


# service(서비스 종류)
CREATE TABLE public.service (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,      -- 서비스 ID
    name TEXT NOT NULL,                                 -- 서비스명
    description TEXT,                                   -- 서비스 설명
    unit TEXT NOT NULL,                                 -- 단위 ('tokens', 'requests', ...)
    category TEXT NOT NULL,                             -- 서비스 분류 ('llm', 'compute', ...)
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),  -- 생성일
    tenant_id TEXT REFERENCES tenants(id),              -- 테넌트
);


# service_rate(서비스 종류별 가격) - 실제 credits_per_unit 파악.
CREATE TABLE public.service_rate (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,             -- 고유 ID
    service_id UUID REFERENCES service(id),                    -- 서비스 ID
    credit_per_unit DECIMAL(10,4) NOT NULL DEFAULT 0,          -- 단위당 크레딧
    tier_name TEXT NOT NULL,                                   -- 구간 ('free':무료 ,'overage':사용량 만큼, 'included':부분 무료)
    min_quantity INTEGER NOT NULL DEFAULT 0,                   -- 최소 수량
    max_quantity INTEGER,                                      -- 최대 수량 (NULL = 무제한)
    included_quantity INTEGER NOT NULL DEFAULT 0,              -- 서비스에 포함된 기본양
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),         -- 생성일
    tenant_id TEXT REFERENCES tenants(id),                     -- 테넌트

    UNIQUE(service_id, tenant_id, tier_name)
);
"""

"""
from Usage import Usage, is_service_available, get_service_list

# 서비스 사용 가능 여부 확인 예시
tenant_id = "example_tenant_id"
if is_service_available(tenant_id):
    print("서비스를 사용할 수 있습니다.")
else:
    print("서비스를 사용할 수 없습니다.")




# 사용 예시
raw_data = { 
    "tenantId": "테넌트 ID", #필수
    "used_at": "2023-10-01T12:00:00+09:00", #필수 (실제 시작 시점)
    "quantity": "100", #필수 (총 토크수, 총 호출 수)
    "model": "GPT-4", #필수 (모델명)
    "userId": "사용자 ID", 
    "service_master_id": "서비스 마스터 ID",
    "metadata": {
        "request": {
            "tokens": 11202,
            "creditPerUnit": 0.4
        },
        "cachedRequest": {
            "tokens": 11202,
            "creditPerUnit": 0.1
        },
        "response": {
            "tokens": 71,
            "creditPerUnit": 1.6
        },
        "usedFor": "chat",
        "usedForId": "1234567890",
        "usedForName": "AI Chating"
    }
}
Usage(raw_data)
"""