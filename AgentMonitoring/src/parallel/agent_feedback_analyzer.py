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
        todo_id: str = None,
        proc_inst_id: str = None,
        tenant_id: str = "default"
    ) -> List[Dict[str, Any]]:
        """
        DIFF 분석 후 에이전트별 피드백 생성
        
        Args:
            draft_content: Draft 내용
            output_content: Output 내용
            todo_id: TODO 리스트 레코드 ID
            proc_inst_id: 프로세스 인스턴스 ID
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
                feedback_json={},
                todo_id=todo_id,
                proc_inst_id=proc_inst_id
            )
            
            # 5. LLM을 통한 에이전트별 피드백 생성
            feedback_list = await self._generate_agent_feedback_with_llm(
                agents, changes, diff_result
            )
            
            logger.info(f"✅ {len(feedback_list)}개의 에이전트 피드백 생성 완료")
            
            # 6. 피드백 생성 후 이벤트 기록 (한 번만, 전체 피드백 리스트 전달)
            self.event_logger.emit_feedback_event(
                event_type="feedback_completed",
                feedback_json={"feedbacks": feedback_list},
                todo_id=todo_id,
                proc_inst_id=proc_inst_id
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
문서 초안(Draft)과 최종본(Output) 간의 변화를 분석하여, 각 에이전트에게 간단하고 명확한 피드백을 제공합니다.

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

### 1. 변화 유형 분석
다음과 같은 변화 유형을 구체적으로 분석하세요:

**A. 내용 추가**
- 새로운 정보나 설명이 추가된 경우
- 예시나 데이터가 보강된 경우

**B. 내용 제거**
- 불필요한 내용이 삭제된 경우
- 중복된 정보가 정리된 경우

**C. 구조 변경**
- 내용의 위치가 이동된 경우
- 섹션 순서가 변경된 경우

**D. 품질 개선**
- 오류가 수정된 경우
- 표현이 개선된 경우

### 2. 의미 있는 변화 판별
- ✅ **피드백 필요**: 위의 A, B, C, D 유형에 해당하는 실질적 개선
- ❌ **피드백 불필요**: 단순 마크다운 문법 변경, 공백/줄바꿈 조정, 형식만 변경

### 3. 에이전트별 책임 영역 매핑
- 변화 내용과 직접 관련된 에이전트만 선택
- 해당 에이전트의 role, goal, persona를 고려하여 연관성 판단
- 모든 에이전트에게 피드백을 주지 말고, 관련된 에이전트에게만 제공

## 출력 형식
반드시 아래 JSON 형식으로만 응답하세요:

```json
[
  {{
    "agent": "에이전트_이름",
    "feedback": "간단한 피드백 (2-3줄, 한국어)"
  }}
]
```

## 피드백 작성 원칙

### 1. 간단하고 명확한 피드백 (2-3줄)
**내용 추가의 경우:**
- "실제 내용(요약)이 추가되었군요. 앞으로도 중요한 포인트는 구체적인 예시와 함께 설명해주세요."

**내용 제거의 경우:**
- "실제 내용(요약)은 제외하는 것이 더 효과적이군요. 핵심에 집중하여 불필요한 정보는 생략해주세요."

**구조 변경의 경우:**
- "실제 수정된 순서로 배치하는 것이 더 논리적이군요. 앞으로도 정보의 흐름을 고려한 구성해주세요."

**품질 개선의 경우:**
- "실제 내용 부분의 정확성과 품질이 향상되었군요. 항상 사실 확인을 철저히 해주세요."

### 2. 피드백 스타일
- **간결성**: 2-3줄로 핵심만 전달
- **구체성**: 어떤 변화가 있었는지 명확히 설명
- **긍정적 톤**: 변화를 인정하고 개선 방향 제시
- **실행가능성**: 구체적인 행동 가이드라인 제공

## 예시 상황별 피드백

### ✅ 피드백이 필요한 경우:
- **내용 추가**: "이런 내용이 추가되었군요. 앞으로도 중요한 포인트는 구체적인 예시와 함께 설명해주세요."
- **내용 제거**: "이런 내용은 제외하는 것이 더 효과적이군요. 핵심에 집중하여 불필요한 정보는 생략해주세요."
- **구조 변경**: "이런 순서로 배치하는 것이 더 논리적이군요. 앞으로도 정보의 흐름을 고려한 구성해주세요."
- **품질 개선**: "정확성과 품질이 향상되었군요. 항상 사실 확인을 철저히 해주세요."

### ❌ 피드백이 불필요한 경우 (빈 배열 [] 반환):
- ```mermaid 블록 제거하고 일반 텍스트로 변경
- 백틱(```) 문법 수정
- 공백이나 줄바꿈 조정
- 단순 형식 변경 (굵기, 기울임 등)

**중요**: 만약 삭제/추가된 내용이 위의 "불필요한 경우"에만 해당한다면, 반드시 빈 배열 []을 반환하세요.

이제 위 분석을 바탕으로 각 에이전트에게 간단하고 명확한 피드백을 생성해주세요.
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
                model="gpt-4.1",
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
    