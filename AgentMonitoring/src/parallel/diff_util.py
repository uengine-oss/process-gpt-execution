import difflib
import json
from typing import List, Tuple, Optional



def compare_strings(original: str, modified: str, name1: str = "original", name2: str = "modified") -> str:
    """
    두 문자열을 비교해서 diff 결과를 리턴합니다.
    """
    original_lines = original.splitlines(keepends=True)
    modified_lines = modified.splitlines(keepends=True)
    
    diff = difflib.unified_diff(
        original_lines,
        modified_lines,
        fromfile=name1,
        tofile=name2,
        lineterm=''
    )
    
    return '\n'.join(diff)



def extract_report_content(json_data: str) -> Optional[str]:
    """
    JSON에서 'report' 키워드가 포함된 키의 값을 추출합니다.
    """
    try:
        if isinstance(json_data, str):
            data = json.loads(json_data)
        else:
            data = json_data
        
        # 첫 번째 레벨의 값을 꺼냄 (예: sales_activity_process_draft_proposal_form의 값)
        first_level_value = list(data.values())[0] if data else {}
        
        # 해당 딕셔너리에서 키를 순회하면서 'report'가 포함된 키 찾기
        if isinstance(first_level_value, dict):
            
            for key, value in first_level_value.items():
                if 'report' in key.lower():
                    return str(value) if value else ""
        
        return None
        
    except Exception as e:
        print(f"Error extracting report content: {e}")
        return None


def compare_report_changes(draft_json: str, output_json: str) -> dict:
    """
    Draft와 Output JSON에서 report 내용만 추출해서 unified diff로 비교합니다.
    """
    draft_content = extract_report_content(draft_json)
    output_content = extract_report_content(output_json)
    
    if not draft_content and not output_content:
        return {
            'unified_diff': '',
            'error': 'No report content found in either draft or output'
        }
    
    if not draft_content:
        draft_content = ""
    if not output_content:
        output_content = ""
    
    # Unified diff 생성 (전체 맥락 포함)
    unified_diff = compare_strings(draft_content, output_content, "draft", "output")
    
    return {
        'unified_diff': unified_diff,
        'draft_content': draft_content,
        'output_content': output_content
    }


def extract_changes(original: str, modified: str) -> dict:
    """
    원본 내용과 변화된 부분만 추출해서 반환합니다.
    """
    original_lines = original.splitlines()
    modified_lines = modified.splitlines()
    
    differ = difflib.Differ()
    diff = list(differ.compare(original_lines, modified_lines))
    
    original_changes = []  # 삭제된 라인들
    modified_changes = []  # 추가된 라인들
    
    for line in diff:
        if line.startswith('- '):  # 삭제된 라인 (원본에만 있던 내용)
            original_changes.append(line[2:])
        elif line.startswith('+ '):  # 추가된 라인 (수정된 내용)
            modified_changes.append(line[2:])
    
    return {
        'original_changes': '\n'.join(original_changes),
        'modified_changes': '\n'.join(modified_changes)
    }


def show_side_by_side_diff(original: str, modified: str, width: int = 80) -> str:
    """
    두 문자열을 나란히 비교해서 보여줍니다.
    """
    original_lines = original.splitlines()
    modified_lines = modified.splitlines()
    
    differ = difflib.Differ()
    diff = list(differ.compare(original_lines, modified_lines))
    
    result = []
    result.append("=" * width)
    result.append("DIFF COMPARISON")
    result.append("=" * width)
    
    for line in diff:
        if line.startswith('  '):  # 동일한 라인
            result.append(f"  {line[2:]}")
        elif line.startswith('- '):  # 삭제된 라인
            result.append(f"- {line[2:]}")
        elif line.startswith('+ '):  # 추가된 라인
            result.append(f"+ {line[2:]}")
        elif line.startswith('? '):  # 변경 힌트
            result.append(f"? {line[2:]}")
    
    return '\n'.join(result)


if __name__ == "__main__":
    # 테스트 예제
    original_code = """def hello():
    print("Hello World")
    return True"""
    
    modified_code = """def hello():
    print("Hello Python")
    print("Modified version")
    return True"""
    
    print("=== 기본 DIFF ===")
    print(compare_strings(original_code, modified_code))
    
    print("\n=== 변화된 부분만 추출 ===")
    changes = extract_changes(original_code, modified_code)
    print("원본 내용:")
    print(changes['original_changes'])
    print("\n변한 내용:")
    print(changes['modified_changes'])
    
    print("\n=== 상세 DIFF ===")
    print(show_side_by_side_diff(original_code, modified_code)) 