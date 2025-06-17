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
        # role -> profile 매핑 캐시
        self._role_profile_cache = {}
        print("✅ AgentsRepository - Supabase 연결 완료")
    
    async def get_all_agents(self, tenant_id: str = "default") -> List[Dict[str, Any]]:
        """agents 테이블 모든 데이터 조회 (tenant_id 필터링 없이 전체)"""
        try:
            # 모든 에이전트 조회 (tenant_id 필터링 없음)
            response = self.client.table("agents").select("*").execute()
            
            # role -> profile 매핑 캐시 업데이트
            for agent in response.data:
                role = agent.get('role')
                profile = agent.get('profile')
                if role and profile:
                    self._role_profile_cache[role] = profile
            
            print(f"✅ {len(response.data)}개 에이전트 조회 완료 (전체 데이터)")
            return response.data
            
        except Exception as e:
            print(f"❌ 에이전트 조회 실패: {e}")
            return []
    
    def get_profile_by_role(self, role: str) -> str:
        """role로 profile 조회"""
        return self._role_profile_cache.get(role, "") 