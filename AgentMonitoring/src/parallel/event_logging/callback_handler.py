"""
CrewAI 에이전트 스텝 콜백 핸들러 (최적화 버전)
"""

import json
from datetime import datetime, timezone
from typing import Dict, Any
from pathlib import Path


class CallbackHandler:
    """CrewAI 에이전트 스텝별 콜백 처리 (최적화)"""
    
    def __init__(self, log_dir: str = "logs"):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(exist_ok=True)
        
        # 현재 실행용 로그 파일
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        self.log_file = self.log_dir / f"agent_steps_{timestamp}.jsonl"
        
        print(f"📁 Agent 스텝 로그가 {self.log_file}에 저장됩니다.")
    
    def step_callback(self, step: Dict[str, Any], agent_name: str = "Unknown"):
        """에이전트 스텝 콜백 (최적화)"""
        try:
            # 스텝 정보 구조화
            step_info = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "agent": agent_name,
                "type": step.get("type", "unknown"),
                "id": step.get("id", "unknown"),
                "data": step
            }
            
            # 간단한 콘솔 출력
            self._log_step(step_info)
            
            # 파일 저장
            self._save_step(step_info)
            
        except Exception as e:
            print(f"❌ 콜백 오류: {e}")
    
    def _log_step(self, step_info: Dict[str, Any]):
        """간단한 스텝 로그 출력"""
        agent = step_info["agent"]
        step_type = step_info["type"]
        step_id = step_info["id"][:8] if step_info["id"] != "unknown" else "unknown"
        
        print(f"🤖 Agent: {agent} | Type: {step_type} | ID: {step_id}")
        
        # 핵심 정보만 출력
        data = step_info["data"]
        if "action" in data:
            action = str(data["action"])[:100] + "..." if len(str(data["action"])) > 100 else str(data["action"])
            print(f"   Action: {action}")
        
        if "thought" in data:
            thought = str(data["thought"])[:150] + "..." if len(str(data["thought"])) > 150 else str(data["thought"])
            print(f"   Thought: {thought}")
    
    def _save_step(self, step_info: Dict[str, Any]):
        """스텝 정보를 JSONL 파일에 저장"""
        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(step_info, ensure_ascii=False) + "\n")
        except Exception as e:
            print(f"❌ 파일 저장 실패: {e}")
    
    def create_callback_for_agent(self, agent_name: str):
        """특정 에이전트용 콜백 함수 생성"""
        return lambda step: self.step_callback(step, agent_name) 