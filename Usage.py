from database import insert_usage, get_service, get_available_credits
from fastapi import HTTPException

# 서비스 목록 조회
def get_service_by_category(category: str, model: str):
    try:
        return get_service(category, model)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"서비스 목록 조회 중 오류: {str(e)}") from e

# 사용량 기록
def usage(raw_data):
    try:
        if not is_service_available(raw_data.get("tenantId", raw_data.get("tenant_id", "")).strip()):
            raise HTTPException(status_code=403, detail="테넌트 제한 초과 관리자에게 문의하세요.")
        
        insert_usage({
            "service_master_id": raw_data.get("service_master_id", raw_data.get("service_master_id", "")).strip(),
            "quantity": raw_data.get("quantity", 0),
            "model": raw_data.get("model", "").strip(),
            "user_id": raw_data.get("userId", raw_data.get("user_id", "")).strip(),
            "used_at": raw_data.get("used_at", raw_data.get("used_at", "")).strip(),
            "metadata": raw_data.get("metadata", {})
        })
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    
# 서비스 이용 제한
def is_service_available(tenant_id: str) -> bool:
    try:
        # available_credits = get_available_credits(tenant_id)
        # return available_credits['remaining_credit'] > 0
        return True
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"제한 확인 중 오류: {str(e)}") from e

# def get_usage_format():
#     return { 
#         "used_at": "", #필수 (실제 시작 시점)
#         "model": "", #필수 (모델명)
#         "user_id": "", 
#         "service_master_id": "",
#         "quantity": 0, #필수 (총 토크수, 총 호출 수)
#         "metadata": {
#             "request": {
#                 "tokens": 0,
#                 "creditPerUnit": 0
#             },
#             "cachedRequest": {
#                 "tokens": 0,
#                 "creditPerUnit": 0
#             },
#             "response": {
#                 "tokens": 0,
#                 "creditPerUnit": 0
#             },
#             "usedFor": "",
#             "usedForId": "",
#             "usedForName": ""
#         }
#     }
"""
DB DDL

# service(서비스 종류)
CREATE TABLE public.service (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,      -- 서비스 ID
    name TEXT NOT NULL,                                 -- 서비스명 (AI 모델명)
    category TEXT NOT NULL,                             -- 서비스 분류 ('llm', 'compute', ...)

    description TEXT,                                   -- 서비스 설명
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),  -- 생성일
    tenant_id TEXT REFERENCES tenants(id),              -- 테넌트

    CONSTRAINT unique_name_category UNIQUE (id, name, category)
);

# service_rate(서비스 종류별 가격) - 실제 credits_per_unit 파악.
CREATE TABLE public.service_rate (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,             -- 고유 ID
    service_id UUID REFERENCES service(id),                    -- 서비스 ID
    credit_per_unit DECIMAL(10,4) NOT NULL DEFAULT 0,          -- 단위당 크레딧
    unit TEXT NOT NULL,                                        -- 단위 ('tokens','requests')
    dimension TEXT DEFAULT NULL,                               -- 요소 (request,response,NULL)
    included_quantity INTEGER NOT NULL DEFAULT 0,              -- 서비스에 포함된 토큰, api 양.
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),         -- 생성일
    tenant_id TEXT REFERENCES tenants(id),                     -- 테넌트

    CONSTRAINT unique_service_dimension
      UNIQUE(service_id, dimension, tenant_id)
);

CREATE TABLE public.service_master (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,      -- 고유 ID
    name TEXT NOT NULL,                                 -- 상품 이름 혹은 서비스 묶음 이름
    description TEXT,                                   -- 상품 설명
    tenant_id TEXT REFERENCES tenants(id),              -- 테넌트
    version DECIMAL(10,1) NOT NULL,                     -- 상품의 버전
    created_at TIMESTAMPTZ DEFAULT now()                -- 생성시간
);

# service_master_item(서비스의 동일한 서비스목록을 그룹화)
CREATE TABLE public.service_master_item (
    master_id UUID REFERENCES service_master(id),       -- 마스터 ID
    service_id UUID REFERENCES service(id),             -- 서비스 ID
    service_rate_id UUID REFERENCES service_rate(id),   -- 서비스 가격 ID

    CONSTRAINT unique_service_master_item
      UNIQUE(master_id, service_id, service_rate_id)
);


# usage(사용량)
CREATE TABLE public.usage (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,            -- 사용량 ID
    service_master_id UUID REFERENCES service_master(id),     -- 서비스 ID 
    tenant_id TEXT NOT NULL REFERENCES tenants(id),           -- (필수)테넌트
    user_id TEXT,                                             -- 사용자
    quantity DECIMAL(12,4) NOT NULL,                          -- (필수)사용 양(토큰, 호출수..)  
    model TEXT,                                               -- 사용모델(GPT-4, .. )
    amount DECIMAL(12,4),                                     -- 총 합계(트리거사용- metadata으로 계산)
    metadata JSONB,                                           -- (토큰 ,개별 price) / 추가 정보 저장 (가격)
    used_at TIMESTAMP WITH TIME ZONE NOT NULL,                -- (필수)실제 사용 시점
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),        -- 생성일
);

"""
