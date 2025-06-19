"""
Knowledge Manager - Mem0 전용 지식 관리 시스템
"""

import os
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field
from crewai.tools import BaseTool
from dotenv import load_dotenv

# .env 파일 로드
load_dotenv()

# Mem0 임포트 (필수)
try:
    from mem0 import MemoryClient
    MEM0_AVAILABLE = True
except ImportError:
    print("❌ Mem0가 설치되지 않음 - 지식 관리 기능을 사용할 수 없습니다")
    MEM0_AVAILABLE = False


class KnowledgeQuerySchema(BaseModel):
    agent_name: str = Field(..., description="에이전트 이름 (지식 네임스페이스 용)")
    mode: str = Field(..., description="'add' 또는 'retrieve' 중 하나")
    content: Optional[str] = Field(None, description="추가할 지식 내용 (mode=add일 때)")
    query: Optional[str] = Field(None, description="검색 쿼리 (mode=retrieve일 때)")


class Mem0Tool(BaseTool):
    """Mem0 전용 지식 관리 도구"""
    
    name: str = "mem0"
    description: str = """
    Mem0 클라우드 기반 지식 관리 시스템입니다.
    - 에이전트별 지식 저장 및 검색
    - Mem0 클라우드에서만 지식을 검색
    """
    args_schema: type = KnowledgeQuerySchema
    
    # 🔧 Pydantic 호환성을 위해 필드를 클래스 레벨에서 정의
    mem0_client: Optional[Any] = Field(default=None, exclude=True)
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._initialize_mem0_client()
    
    def _initialize_mem0_client(self):
        """Mem0 클라이언트 초기화"""
        # Mem0 클라이언트 초기화 (필수)
        if not MEM0_AVAILABLE:
            print("❌ Mem0가 설치되지 않음 - 지식 관리 기능 비활성화")
            return
        
        api_key = os.environ.get('MEM_ZERO_API_KEY')
        if not api_key:
            print("❌ MEM_ZERO_API_KEY 환경변수가 설정되지 않음 - mem0 비활성화")
            return
        
        try:
            object.__setattr__(self, 'mem0_client', MemoryClient(api_key=api_key))
            print("✅ mem0 도구 초기화 완료")
        except Exception as e:
            print(f"❌ mem0 클라이언트 초기화 실패: {e}")
            object.__setattr__(self, 'mem0_client', None)
    
    def _run(self, agent_name: str, mode: str, content: Optional[str] = None, 
             query: Optional[str] = None):
        """지식 관리 실행 (Mem0 전용)"""
        
        if not self.mem0_client:
            return "❌ Mem0 클라이언트가 초기화되지 않았습니다."
        
        if mode == "add":
            return self._add_knowledge_to_mem0(agent_name, content)
        elif mode == "retrieve":
            return self._retrieve_knowledge_from_mem0(agent_name, query)
        else:
            return "❌ mode는 'add' 또는 'retrieve'만 지원합니다."
    
    def _add_knowledge_to_mem0(self, agent_name: str, content: str) -> str:
        """Mem0에 지식 추가"""
        if not content:
            return "❌ 추가할 content가 필요합니다."
        
        try:
            # Mem0에 저장
            messages = [{"role": "user", "content": content}]
            result = self.mem0_client.add(messages, agent_id=agent_name)
            print(f"✅ Mem0에 지식 저장 성공: {agent_name}")
            return f"✅ 지식이 Mem0에 성공적으로 저장되었습니다. (Agent: {agent_name})"
            
        except Exception as e:
            print(f"❌ Mem0 지식 저장 실패: {e}")
            return f"❌ Mem0 지식 저장 실패: {str(e)}"
    
    def _retrieve_knowledge_from_mem0(self, agent_name: str, query: str) -> str:
        """Mem0에서만 지식 검색"""
        if not query:
            # 빈 query일 때는 해당 에이전트의 모든 지식을 검색
            query = agent_name  # 에이전트 이름으로 검색
            print(f"⚠️  빈 query 감지 - 에이전트명으로 검색: '{query}'")
        
        try:
            print(f"🔍 Mem0에서 지식 검색 중: '{query}' (Agent: {agent_name})")
            
            # Mem0에서 검색
            results = self.mem0_client.search(query, agent_id=agent_name)
            
            if not results:
                print(f"📭 Mem0에서 관련 지식을 찾지 못함: '{query}'")
                return f"📭 '{query}'에 대한 저장된 지식이 Mem0에 없습니다.\n\n💡 관련 지식을 먼저 추가하거나 다른 검색어를 시도해보세요."
            
            # 검색 결과 포맷팅 (상위 3개)
            output = []
            print(f"✅ Mem0에서 {len(results)}개 관련 지식 발견")
            
            for i, result in enumerate(results[:3]):  # 상위 3개만
                memory = result.get('memory', '')
                score = result.get('score', 0)
                
                if memory:  # 빈 메모리는 제외
                    output.append(f"**지식 {i+1}** (관련도: {score:.2f})\n{memory}")
            
            if not output:
                return f"📭 '{query}'에 대한 유효한 지식이 Mem0에 없습니다."
            
            return f"🧠 **Mem0에서 찾은 지식:**\n\n" + "\n\n---\n\n".join(output)
            
        except Exception as e:
            print(f"❌ Mem0 지식 검색 실패: {e}")
            return f"❌ Mem0 지식 검색 중 오류 발생: {str(e)}\n\n💡 네트워크 연결이나 API 키를 확인해보세요."
    
    def get_status(self) -> str:
        """Mem0 연결 상태 확인"""
        if not self.mem0_client:
            return "❌ Mem0 클라이언트 미연결"
        
        try:
            # 간단한 테스트 검색으로 연결 확인
            test_results = self.mem0_client.search("test", agent_id="system_test")
            return "✅ Mem0 연결 정상"
        except Exception as e:
            return f"❌ Mem0 연결 오류: {str(e)}" 