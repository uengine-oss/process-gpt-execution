from typing import Dict, Any, Optional, List
import threading
import openai
import os
import json
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


class ProcessContextManager:
    """
    proc_inst_id별로 작업 내용을 파일(json)로만 저장/조회하는 컨텍스트 매니저 (메모리 캐시 없음)
    activity_name별이 아니라 proc_inst_id별로만 구분하며, 산출물 전체를 하나로 요약해서 저장
    """
    _instance = None
    _lock = threading.Lock()
    _context_dir = Path(__file__).parent / "contexts"
    _max_reports = 10  # 최근 N개 산출물만 유지
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    # contexts 폴더 생성
                    cls._context_dir.mkdir(exist_ok=True)
        return cls._instance
    
    def __init__(self):
        # OpenAI 클라이언트 초기화
        try:
            openai.api_key = os.getenv("OPENAI_API_KEY")
            self.openai_client = openai
            print("✅ OpenAI 클라이언트 초기화 완료")
        except Exception as e:
            print(f"⚠️ OpenAI 클라이언트 초기화 실패: {e}")
            self.openai_client = None

    def _context_file(self, proc_inst_id: str) -> Path:
        return self._context_dir / f"{proc_inst_id}.json"

    def _summarize_reports(self, reports: Dict[str, str]) -> str:
        """LLM을 사용해 리포트들을 요약"""
        if not self.openai_client or not reports:
            return "요약 불가"
        
        # 모든 리포트 합치기
        combined_reports = "\n\n=== 리포트 구분 ===\n\n".join(reports.values())
        
        prompt = f"""다음은 이전 요약 내용과 새로 추가된 산출물(폼, 리포트 등)입니다. 
이전 요약과 새 산출물을 병합하여, 아래 형식에 맞는 하나의 통합 요약을 생성하세요. 

!!중요!! 아래 형식은 '보고서'가 아니라, 단순히 정보를 구조적으로 정리하는 요약 양식일 뿐입니다. 반드시 이전 요약과 새 산출물의 모든 핵심 정보를 빠짐없이 반영하여, 병합된 하나의 요약을 작성하세요.

리포트 내용:
{combined_reports}

===== 요약 형식 (반드시 이 형식을 따르세요) =====

📋 보고서 제목: [리포트에서 정확히 추출한 제목 없으면, 문맥상 흐름을 분석하여 제목을 정의]

📌 목적 : [사용자 요청 및 문맥상 흐름을 분석하여 목적을 정의]
📌 요구사항 : [사용자 요청 및 문맥상 흐름을 분석하여 요구사항을 정의]
📌 피드백 : [사용자 요청 및 문맥상 흐름을 분석하여 피드백을 정의]
📌 이슈 : [사용자 요청 및 문맥상 흐름을 분석하여 이슈를 정의]

👤 작성 정보:
- 작성자: [작성자명]
- 소속부서: [부서명]

📑 목차별 핵심 요약:

1️⃣ [목차1 제목]:
   • 핵심내용 1: [중요 포인트를 한 문장으로]
   • 핵심내용 2: [주요 데이터나 결과를 한 문장으로]
   • 핵심내용 3: [결론이나 시사점을 한 문장으로]

2️⃣ [목차2 제목]:
   • 핵심내용 1: [중요 포인트를 한 문장으로]
   • 핵심내용 2: [주요 데이터나 결과를 한 문장으로]
   • 핵심내용 3: [결론이나 시사점을 한 문장으로]

3️⃣ [목차3 제목]:
   • 핵심내용 1: [중요 포인트를 한 문장으로]
   • 핵심내용 2: [주요 데이터나 결과를 한 문장으로]
   • 핵심내용 3: [결론이나 시사점을 한 문장으로]

[계속해서 모든 목차에 대해 동일한 형식으로...]

🎯 전체 요약:
- 주요 목적: [핵심 목적]
- 핵심 결과: [가장 중요한 결과나 발견사항]
- 향후 계획: [제안사항이나 후속 조치]

===== 작성 지침 =====
!!중요!! 요약 내용은 2500자 이내로 작성하세요. 
1. 목차는 리포트에서 정확히 추출하여 누락 없이 모두 포함
2. 각 목차별로 반드시 3개의 핵심내용을 추출 (부족하면 관련 내용으로 보완)
3. 숫자, 데이터, 구체적 사실을 우선적으로 포함
4. 한 문장은 최대 50자 이내로 간결하게 작성
5. 메타데이터(작성자, 부서 등)는 반드시 찾아서 포함 (없으면 "정보 없음"으로 표시)
6. 이모지와 구조화된 형식을 정확히 유지
7. 전문용어는 그대로 유지하되 이해하기 쉽게 설명 추가
8. 중요도 순으로 내용 배치"""

        try:
            response = self.openai_client.chat.completions.create(
                model="gpt-4.1",
                messages=[
                    {"role": "system", "content": """당신은 전문적인 요약 전문가입니다. 
                    
주요 역할:
- 복잡한 산출물(보고서, 폼 등)을 구조화된 형식으로 정확히 요약
- 목차별 핵심 내용을 빠짐없이 추출
- 메타데이터와 중요 데이터를 정확히 파악
- 비즈니스 문서의 핵심 가치를 보존하면서 간결하게 정리

작업 원칙:
1. 정확성: 원문의 내용을 왜곡하지 않고 정확히 요약
2. 완전성: 모든 목차와 중요 정보를 누락 없이 포함
3. 구조화: 일관된 형식으로 읽기 쉽게 정리
4. 간결성: 핵심만 추출하여 효율적으로 전달
5. 실용성: 후속 작업에 활용하기 쉬운 형태로 가공"""},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=3000,
                temperature=0.1
            )
            
            summary = response.choices[0].message.content.strip()
            print(f"✅ 리포트 요약 완료: {len(summary)}자")
            return summary
            
        except Exception as e:
            print(f"❌ 리포트 요약 실패: {e}")
            return f"요약 실패: {str(e)}"
    
    def save_context(self, proc_inst_id: str, activity_name: str, content: Any):
        """
        컨텍스트에 데이터 저장 (activity_name별로 관리, save_context 호출 시마다 전체를 합쳐 즉시 요약)
        Args:
            proc_inst_id: 프로세스 인스턴스 ID
            activity_name: 산출물/폼의 액티비티 이름(구분자)
            content: 저장할 내용 (dict, str 등)
        """
        if not proc_inst_id or not activity_name:
            return
        path = self._context_file(proc_inst_id)
        # 파일에서 기존 데이터 읽기
        data = {}
        if path.exists():
            try:
                with path.open("r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception as e:
                print(f"⚠️ 파일 읽기 실패: {e}")
        # 기존 activity별 데이터
        activity_data = data.get("activity_data", {})
        # activity_name별로 저장/갱신
        activity_data[activity_name] = content
        # 이전 summary
        prev_summary = data.get("reports_summary", None)
        # 요약 프롬프트 구성: 이전 summary + 모든 activity별 산출물/폼
        merged_for_summary = {}
        if prev_summary:
            merged_for_summary["이전 요약"] = prev_summary
        for act, val in activity_data.items():
            # value가 dict나 list면 문자열로 변환
            if isinstance(val, (dict, list)):
                merged_for_summary[act] = json.dumps(val, ensure_ascii=False, indent=2)
            else:
                merged_for_summary[act] = str(val)
        # 요약
        summarized_reports = self._summarize_reports(merged_for_summary) if merged_for_summary else prev_summary
        # 저장 구조
        save_data = {
            "reports_summary": summarized_reports,
            "activity_data": activity_data
        }
        try:
            with path.open("w", encoding="utf-8") as f:
                json.dump(save_data, f, ensure_ascii=False, indent=2)
            print(f"💾 파일에 컨텍스트 저장 (activity_name별, proc_inst_id 단위): {proc_inst_id} / {activity_name}")
            print(f"   요약 길이: {len(summarized_reports) if summarized_reports else 0}자, 액티비티 수: {len(activity_data)}")
        except Exception as e:
            print(f"⚠️ 파일 컨텍스트 저장 실패: {e}")
    
    def get_context(self, proc_inst_id: str) -> Dict[str, Any]:
        """
        컨텍스트 데이터 가져오기 (항상 파일에서 읽음)
        
        Args:
            proc_inst_id: 프로세스 인스턴스 ID
            
        Returns:
            해당 proc_inst_id의 모든 데이터
        """
        if not proc_inst_id:
            return {}
        
        path = self._context_file(proc_inst_id)
        if path.exists():
            try:
                with path.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                print(f"📖 파일에서 컨텍스트 조회: {proc_inst_id}")
                if data:
                    summary_length = len(data.get("reports_summary", ""))
                    reports_count = len(data.get("_all_reports", []))
                    forms_count = len(data.get("forms", []))
                    print(f"   리포트 요약 {summary_length}자, 리포트 {reports_count}개, 폼 {forms_count}개")
                else:
                    print("   조회된 컨텍스트 없음")
                return data
            except Exception as e:
                print(f"⚠️ 파일 컨텍스트 조회 실패: {e}")
        return {}

# 전역 인스턴스
context_manager = ProcessContextManager() 