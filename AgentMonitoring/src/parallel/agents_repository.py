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
        """agents 테이블에서 5개 필드(name, role, goal, persona, description)가 모두 비어있지 않은 데이터만 조회"""
        try:
            # 5개 필드가 모두 null이 아니고 비어있지 않은 에이전트만 조회
            response = (self.client.table("agents")
                       .select("*")
                       .not_.is_("name", "null")
                       .not_.is_("role", "null") 
                       .not_.is_("goal", "null")
                       .not_.is_("persona", "null")
                       .neq("name", "")
                       .neq("role", "")
                       .neq("goal", "")
                       .neq("persona", "")
                       .execute())
            
            # 🆕 tools 필드 기본값 처리
            for agent in response.data:
                tools = agent.get('tools')
                if not tools or tools.strip() == "":  # null이거나 빈값이면
                    agent['tools'] = "mem0"  # 기본값 설정
                
                # role -> profile 매핑 캐시 업데이트
                role = agent.get('role')
                profile = agent.get('profile')
                if role and profile:
                    self._role_profile_cache[role] = profile
            
            print(f"✅ {len(response.data)}개 완전한 에이전트 조회 완료 (tools 기본값 처리됨)")
            return response.data
            
        except Exception as e:
            print(f"❌ 에이전트 조회 실패: {e}")
            return []
    
    def get_profile_by_role(self, role: str) -> str:
        """role로 profile 조회"""
        return self._role_profile_cache.get(role, "") 