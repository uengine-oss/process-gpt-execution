"""
Supabase Agents Repository - 정말 간단 버전
"""

import os
from typing import List, Dict, Any
from dotenv import load_dotenv
from supabase import create_client, Client
load_dotenv()

class AgentsRepository:
    """Supabase agents 테이블에서 데이터 조회만"""
    
    def __init__(self):


        self.supabase_url = os.getenv("SUPABASE_URL")
        self.supabase_key = os.getenv("SUPABASE_KEY")
        self.client: Client = create_client(self.supabase_url, self.supabase_key)
        print("✅ AgentsRepository - Supabase 연결 완료")
    
    async def get_all_agents(self, tenant_id: str = "default") -> List[Dict[str, Any]]:
        """agents 테이블 모든 데이터 조회 (원본 그대로)"""
        response = self.client.table("agents").select("*").eq("tenant_id", tenant_id).execute()
        
        print(f"✅ {len(response.data)}개 에이전트 조회 완료 (원본 데이터)")
        return response.data 