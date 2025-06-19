import asyncio
import json
from agent_feedback_analyzer import AgentFeedbackAnalyzer

async def test_feedback_with_memory():
    """의미 있는 변화가 있는 경우 피드백 생성 및 Mem0 저장 테스트"""
    
    analyzer = AgentFeedbackAnalyzer()
    
    # 의미 있는 변화가 있는 테스트 데이터 (중첩된 JSON 구조)
    draft = json.dumps({
        "sales_activity_process_draft_proposal_form": {
            "business_report": "Basic analysis content. Only simple summary included.",
            "other_field": "some data"
        }
    })
    
    output = json.dumps({
        "sales_activity_process_draft_proposal_form": {
            "business_report": "Basic analysis content. Only simple summary included. Additionally, detailed data analysis, market trends, and competitor comparison analysis have been added. Future strategic recommendations are also included.",
            "other_field": "some data"
        }
    })
    
    print("🧪 의미 있는 변화 테스트 시작...")
    print(f"Draft: {draft}")
    print(f"Output: {output}")
    print("-" * 50)
    
    # 피드백 분석 및 Mem0 저장
    feedback_list = await analyzer.analyze_diff_and_generate_feedback(draft, output)
    
    print(f"\n🎯 최종 결과: {len(feedback_list)}개의 피드백 생성")
    
    # JSON 형태로 결과 출력
    print("\n📋 JSON 결과:")
    print(json.dumps(feedback_list, indent=2, ensure_ascii=False))
    
    print("\n📝 피드백 요약:")
    for feedback in feedback_list:
        print(f"- {feedback['agent']}: {feedback['feedback']}")

if __name__ == "__main__":
    asyncio.run(test_feedback_with_memory()) 