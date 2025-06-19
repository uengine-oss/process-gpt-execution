import asyncio
import logging
import json
import os
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv
from dataclasses import dataclass

from .agents_repository import AgentsRepository
from .diff_util import compare_report_changes, extract_changes
from .knowledge_manager import Mem0Tool
from .event_logging.crew_event_logger import CrewAIEventLogger

# 로거 설정
logger = logging.getLogger("agent_feedback_analyzer")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

@dataclass
class AgentFeedback:
    """에이전트 피드백 데이터 구조"""
    agent: str
    feedback: str

class AgentFeedbackAnalyzer:
    """
    DIFF 분석을 통해 에이전트별 개선점을 식별하고 피드백을 생성하는 클래스
    """
    
    def __init__(self):
        load_dotenv()
        self.agents_repository = AgentsRepository()
        self.openai_api_key = os.getenv("OPENAI_API_KEY")
        self.knowledge_manager = Mem0Tool()
        self.event_logger = CrewAIEventLogger()
        
    async def analyze_diff_and_generate_feedback(
        self, 
        draft_content: str, 
        output_content: str,
        tenant_id: str = "default"
    ) -> List[Dict[str, Any]]:
        """
        DIFF 분석 후 에이전트별 피드백 생성
        
        Args:
            draft_content: Draft 내용
            output_content: Output 내용
            tenant_id: 테넌트 ID
            
        Returns:
            에이전트별 피드백 리스트
        """
        try:
            # 1. DIFF 분석
            diff_result = compare_report_changes(draft_content, output_content)
            
            if not diff_result.get('unified_diff'):
                print("변화가 없어 피드백 분석을 건너뜁니다.")
                return []
            
            # 2. 에이전트 목록 조회
            agents = await self.agents_repository.get_all_agents(tenant_id)
            
            # 3. 변화 분석
            changes = extract_changes(
                diff_result.get('draft_content', ''), 
                diff_result.get('output_content', '')
            )
            
            # 4. 피드백 생성 전 이벤트 기록 (한 번만, 빈 데이터)
            self.event_logger.emit_feedback_event(
                event_type="feedback_started",
                feedback_json={}
            )
            
            # 5. LLM을 통한 에이전트별 피드백 생성
            feedback_list = await self._generate_agent_feedback_with_llm(
                agents, changes, diff_result
            )
            
            logger.info(f"✅ {len(feedback_list)}개의 에이전트 피드백 생성 완료")
            
            # 6. 피드백 생성 후 이벤트 기록 (한 번만, 전체 피드백 리스트 전달)
            self.event_logger.emit_feedback_event(
                event_type="feedback_completed",
                feedback_json={"feedbacks": feedback_list}
            )
            
            # 7. 피드백이 있으면 Mem0에 지식 적재
            if feedback_list:
                await self._store_feedback_to_memory(feedback_list)
            
            return feedback_list
            
        except Exception as e:
            logger.error(f"피드백 분석 중 오류 발생: {e}")
            return []
    
    async def _generate_agent_feedback_with_llm(
        self, 
        agents: List[Dict[str, Any]], 
        changes: Dict[str, str], 
        diff_result: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        LLM을 사용하여 에이전트별 맞춤 피드백 생성
        """
        
        # 에이전트 정보
        agents_summary = agents
        
        # 변화 내용
        deleted_content = changes['original_changes']
        added_content = changes['modified_changes']
        
        # LLM 프롬프트 생성
        prompt = self._create_feedback_prompt(agents_summary, deleted_content, added_content, diff_result)
        
        # LLM 호출 (OpenAI 사용)
        feedback_result = await self._call_openai_for_feedback(prompt)
        
        return feedback_result
    
    def _create_feedback_prompt(
        self, 
        agents: List[Dict[str, Any]], 
        deleted_content: str, 
        added_content: str,
        diff_result: Dict[str, Any]
    ) -> str:
        """
        에이전트 피드백 생성을 위한 상세한 LLM 프롬프트 작성
        """
        
        prompt = f"""
# 에이전트 성과 분석 및 피드백 생성

## 목적
문서 초안(Draft)과 최종본(Output) 간의 변화를 분석하여, 각 에이전트에게 구체적이고 실행 가능한 개선 피드백을 제공합니다.

## 사용 가능한 에이전트 목록
{json.dumps(agents, indent=2, ensure_ascii=False)}

## 문서 변화 분석
### 삭제된 내용:
{deleted_content if deleted_content.strip() else "없음"}

### 추가된 내용:
{added_content if added_content.strip() else "없음"}

## 변화의 맥락
아래는 실제 diff 내용으로, 변화가 일어난 맥락을 파악할 수 있습니다:
```
{diff_result.get('unified_diff', '')}...
```

## 분석 지침
1. **의미 있는 변화 판별 (중요!)**: 먼저 변화가 실질적인 개선인지 판단하세요
   - ✅ **피드백 필요**: 내용 추가/삭제, 정확성 향상, 구조 개선, 새로운 정보 추가
   - ❌ **피드백 불필요**: 단순 마크다운 문법 변경(```mermaid 제거, 백틱 변경), 공백/줄바꿈 조정, 형식만 변경
   
   **만약 변화가 단순히 마크다운 문법 변경이나 형식 조정뿐이라면, 빈 배열 []을 반환하세요.**

2. **변화의 성격 분석**: 삭제/추가된 내용이 어떤 종류의 개선인지 판단
   - 구조적 개선 (논리적 흐름, 섹션 구성)
   - 내용적 개선 (정보 추가/삭제, 정확성 향상)
   - 스타일 개선 (가독성, 표현 방식)
   - 기술적 개선 (새로운 데이터, 분석 방법)

3. **에이전트별 책임 영역 매핑**: 각 에이전트의 role, goal, persona를 기반으로 어떤 변화가 해당 에이전트와 관련있는지 판단
   - **중요**: 모든 에이전트에게 피드백을 주지 마세요. 변화와 직접 관련된 에이전트에게만 피드백을 제공하세요.
   - 변화된 내용의 문맥을 파악하여 해당 에이전트에게 피드백을 제공하세요.
   
4. **선별적 피드백**: 
   - 변화 내용과 직접 관련된 에이전트만 선택
   - 관련성이 낮은 에이전트는 제외
   - 연관성 있는 에이전트에게만 피드백 제공
   - 같은 에이전트에 대해 여러번 피드백을 주지 마세요.

## 출력 형식
반드시 아래 JSON 형식으로만 응답하세요:

```json
[
  {{
    "agent": "에이전트_이름",
    "feedback": "구체적이고 실행 가능한 피드백 (한국어, 2-3문장)"
  }}
]
```

## 피드백 작성 원칙
1. **구체성**: "더 나은 내용을 작성하세요" ❌ → "마크다운 문법을 올바르게 사용하여 다이어그램을 표시하세요" ✅
2. **실행가능성**: 에이전트가 바로 적용할 수 있는 명확한 가이드라인 제시
3. **역할 연관성**: 해당 에이전트의 전문 분야와 연결된 피드백
4. **긍정적 톤**: 비판보다는 개선 방향 제시
5. **한국어 사용**: 자연스러운 한국어로 작성

## 예시 상황별 피드백

### ✅ 피드백이 필요한 경우:
- **새로운 데이터 추가**: "다음번에는 최신 통계 데이터를 포함하여 더욱 설득력 있는 분석을 제공해주세요."
- **내용 정확성 개선**: "사실 확인을 더욱 철저히 하여 정확한 정보만 포함되도록 검토 과정을 강화해주세요."
- **구조 개선**: "정보 전달 효과를 높이기 위해 논리적 흐름과 섹션 구성을 더욱 체계화해주세요."
- **분석 방법 개선**: "데이터 해석 시 다각도 관점을 고려하여 더욱 균형잡힌 분석을 제공해주세요."

### ❌ 피드백이 불필요한 경우 (빈 배열 [] 반환):
- ```mermaid 블록 제거하고 일반 텍스트로 변경
- 백틱(```) 문법 수정
- 공백이나 줄바꿈 조정
- 단순 형식 변경 (굵기, 기울임 등)

**중요**: 만약 삭제/추가된 내용이 위의 "불필요한 경우"에만 해당한다면, 반드시 빈 배열 []을 반환하세요.

이제 위 분석을 바탕으로 각 에이전트에게 적절한 피드백을 생성해주세요.
"""
        
        return prompt
    
    async def _call_openai_for_feedback(self, prompt: str) -> List[Dict[str, Any]]:
        """
        OpenAI API를 호출하여 피드백 생성
        """
        try:
            import openai
            
            client = openai.AsyncOpenAI(api_key=self.openai_api_key)
            
            response = await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system", 
                        "content": "당신은 AI 에이전트 성과 분석 전문가입니다. 문서 변화를 분석하여 각 에이전트에게 구체적이고 건설적인 피드백을 제공합니다."
                    },
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=2000
            )
            
            content = response.choices[0].message.content
            
            # JSON 추출 (```json 블록이 있는 경우)
            if "```json" in content:
                json_start = content.find("```json") + 7
                json_end = content.find("```", json_start)
                content = content[json_start:json_end].strip()
            
            # JSON 파싱
            feedback_list = json.loads(content)
            
            return feedback_list
            
        except Exception as e:
            logger.error(f"OpenAI API 호출 중 오류: {e}")
            return []
    
    async def _store_feedback_to_memory(self, feedback_list: List[Dict[str, Any]]):
        """
        생성된 피드백을 Mem0에 지식으로 적재
        """
        try:
            logger.info(f"🧠 {len(feedback_list)}개의 피드백을 Mem0에 저장 중...")
            
            for feedback in feedback_list:
                agent_name = feedback.get('agent')
                feedback_content = feedback.get('feedback')
                
                if agent_name and feedback_content:
                    # 피드백을 지식 형태로 포맷팅
                    knowledge_content = f"[피드백] {feedback_content}"
                    
                    # Mem0에 저장
                    result = self.knowledge_manager._run(
                        agent_name=agent_name,
                        mode="add",
                        content=knowledge_content
                    )
                    
                    logger.info(f"💾 {agent_name}에게 피드백 저장: {result}")
            
            logger.info("✅ 모든 피드백이 Mem0에 저장되었습니다.")
            
        except Exception as e:
            logger.error(f"Mem0 지식 적재 중 오류: {e}")
    