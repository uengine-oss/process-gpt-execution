"""
CrewAI Event Logger - Task/Agent 이벤트 전용 (Supabase 스키마 호환)
"""

import os
import uuid
import json
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Dict, Any, Set, Any as TypeAny
import logging
import re

from dotenv import load_dotenv

# .env 파일 로드
load_dotenv()


# 로깅 설정
logger = logging.getLogger(__name__)

# Supabase client availability
try:
    from supabase import create_client, Client
    SUPABASE_AVAILABLE = True
except ImportError:
    SUPABASE_AVAILABLE = False

# 🆕 전역 컨텍스트 관리자
class GlobalContextManager:
    """전역 컨텍스트를 관리하여 현재 실행 중인 작업의 출신 정보를 추적"""
    _context_stack = []  # 중첩된 작업을 위한 스택 구조
    _role_profile_mapping = {}  # role -> profile 매핑
    
    @classmethod
    def set_context(cls, output_type: str, form_id: str, filename: str = None, todo_id: str = None, proc_inst_id: str = None):
        """현재 작업의 컨텍스트 설정"""
        context = {
            "output_type": output_type,  # "report", "slide", "text"
            "form_id": form_id,         # "report_user_guide" etc.
            "filename": filename,        # 생성될 파일명
            "todo_id": todo_id,          # TODO 리스트 레코드 ID
            "proc_inst_id": proc_inst_id, # 프로세스 인스턴스 ID
            "timestamp": datetime.now().isoformat()
        }
        cls._context_stack.append(context)
        logger.info(f"🎯 컨텍스트 설정: {output_type}/{form_id}")
    
    @classmethod
    def set_role_profile_mapping(cls, role_profile_mapping: Dict[str, str]):
        """role -> profile 매핑 설정"""
        # role 키에서 탭/공백 제거
        cleaned_mapping = {k.strip(): v for k, v in role_profile_mapping.items()}
        cls._role_profile_mapping = cleaned_mapping
        logger.info(f"🎭 role->profile 매핑 설정: {len(cleaned_mapping)}개")
    
    @classmethod
    def get_profile_by_role(cls, role: str) -> str:
        """role로 profile 조회, 매칭 안되면 기본값 반환"""
        # 디버깅: 현재 매핑 상태 확인
        print(f"🔍 [DEBUG] role 매칭 시도: '{role}'")
        print(f"🔍 [DEBUG] 현재 매핑 개수: {len(cls._role_profile_mapping)}")
        if cls._role_profile_mapping:
            print(f"🔍 [DEBUG] 매핑 키들: {list(cls._role_profile_mapping.keys())}")
        
        # 정확한 매칭 시도
        clean_role = role.strip()
        profile = cls._role_profile_mapping.get(clean_role, "")
        if profile:
            print(f"✅ [DEBUG] 매칭 성공: '{clean_role}'")
            return profile
            
        # 매칭 실패시 기본값 반환
        print(f"❌ [DEBUG] 매칭 실패: '{clean_role}' → 기본값 사용")
        return "/images/chat-icon.png"
    
    @classmethod
    def get_current_context(cls):
        """현재 컨텍스트 반환"""
        return cls._context_stack[-1] if cls._context_stack else None
    
    @classmethod
    def clear_context(cls):
        """현재 컨텍스트 제거"""
        if cls._context_stack:
            removed = cls._context_stack.pop()
            logger.info(f"🔄 컨텍스트 제거: {removed.get('output_type')}/{removed.get('form_id')}")
    
    @classmethod
    def get_context_info(cls):
        """현재 컨텍스트 정보 반환 (디버깅용)"""
        current = cls.get_current_context()
        if current:
            return f"{current['output_type']}/{current['form_id']}"
        return "no_context"

class CrewAIEventLogger:
    """
    CrewAI 이벤트 로깅 시스템 - Task/Agent 전용, Supabase 스키마 호환
    
    특징:
    - Task와 Agent 이벤트만 기록 (Crew 이벤트 완전 제외)
    - Supabase 스키마 완벽 호환 (id, run_id, job_id, type, data, timestamp)
    - 중복 이벤트 자동 제거
    - 단일 로그 파일 생성
    """
    
    # === Initialization ===
    def __init__(self, run_id: str = None, enable_supabase: bool = True, enable_file_logging: bool = True):
        """이벤트 로거 초기화"""
        self.run_id = run_id or str(uuid.uuid4())[:8]
        self.enable_supabase = enable_supabase and SUPABASE_AVAILABLE
        self.enable_file_logging = enable_file_logging
        self._processed_events = set()  # 중복 제거용
        
        # Supabase 클라이언트 초기화
        self.supabase_client = self._init_supabase() if self.enable_supabase else None
        
        # 파일 로깅 설정
        if self.enable_file_logging:
            os.makedirs("logs", exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            # self.log_file = f"logs/crew_events_{timestamp}_{self.run_id}.jsonl"  # 파일 로깅 비활성화
            self.log_file = None
        else:
            self.log_file = None
        
        logger.info(f"🎯 CrewAI Event Logger 초기화 (run_id: {self.run_id})")
        print(f"   - Supabase: {'✅' if self.supabase_client else '❌'}")
        print(f"   - 파일 로깅: ❌")  # 파일 로깅 상태 표시 수정

    def _init_supabase(self) -> Optional[Client]:
        """Supabase 클라이언트 초기화"""
        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_KEY") 
        
        if not url or not key:
            logger.warning("⚠️ Supabase 자격증명 누락 - 로깅 비활성화")
            return None
        
        try:
            client = create_client(url, key)
            logger.info("✅ Supabase 백엔드 연결됨")
            return client
        except Exception as e:
            logger.error(f"❌ Supabase 연결 실패: {e}")
            return None

    # === Job ID Generation ===
    def _generate_job_id(self, event_obj: TypeAny, source: TypeAny) -> str:
        # 항상 task.id 사용
        if hasattr(event_obj, 'task') and hasattr(event_obj.task, 'id'):
            return str(event_obj.task.id)
        if source and hasattr(source, 'task') and hasattr(source.task, 'id'):
            return str(source.task.id)
        return 'unknown'

    # === Event Signature Creation ===
    def _create_event_signature(self, event_obj: TypeAny, source: TypeAny) -> str:
        """중복 제거를 위한 고유 시그니처 생성"""
        signature_parts = [
            str(event_obj.type),
            str(event_obj.timestamp),
            str(getattr(event_obj, 'source_fingerprint', 'None')),
        ]
        
        if source and hasattr(source, 'id'):
            signature_parts.append(str(source.id))
        
        return "_".join(signature_parts)

    # === Event Data Extraction ===
    def _extract_event_data(self, event_obj: TypeAny, source: Optional[TypeAny] = None) -> Dict[str, Any]:
        event_type = event_obj.type
        try:
            if event_type == "task_started":
                role = getattr(event_obj.task.agent, 'role', 'Unknown')
                goal = getattr(event_obj.task.agent, 'goal', 'Unknown')
                agent_profile = GlobalContextManager.get_profile_by_role(role)
                return {"role": role, "goal": goal, "agent_profile": agent_profile}
            elif event_type == "task_completed":
                final_result = getattr(event_obj, 'output', 'Completed')
                return {"final_result": str(final_result)}
            elif event_type.startswith('tool_'):
                tool_name = getattr(event_obj, 'tool_name', None)
                tool_args = getattr(event_obj, 'tool_args', None)
                query = None
                if tool_args:
                    try:
                        args_dict = json.loads(tool_args)
                        query = args_dict.get('query')
                    except Exception:
                        query = None
                return {"tool_name": tool_name, "query": query}
            else:
                return {"info": f"Event type: {event_type}"}
        except Exception as e:
            logger.error(f"Error extracting event data: {e}")
            return {"error": f"Failed to extract data: {str(e)}"}

    # === Backend Writing ===
    def _write_to_backends(self, event_record: Dict[str, Any]) -> None:
        """Supabase와 파일에 기록 (동기화 처리로 누락 방지)"""
        # Supabase 기록
        if self.supabase_client:
            try:
                # 🔧 안전한 JSON 직렬화: 모든 객체를 문자열로 변환
                def safe_serialize(obj):
                    """모든 객체를 JSON 직렬화 가능한 형태로 변환"""
                    if hasattr(obj, 'raw'):  # TaskOutput 객체
                        return str(obj.raw)
                    elif hasattr(obj, '__dict__'):  # 일반 객체
                        return str(obj)
                    else:
                        return str(obj)
                
                serializable_record = json.loads(json.dumps(event_record, default=safe_serialize))
                self.supabase_client.table("events").insert(serializable_record).execute()
            except Exception as e:
                logger.error(f"❌ Supabase 저장 실패: {e}")
                print(f"❌ Supabase 저장 실패: {e}")
                # 디버깅용: 문제가 되는 데이터 구조 출력
                print(f"🔍 문제 데이터: {type(event_record.get('data', {}))}")
                for key, value in event_record.get('data', {}).items():
                    print(f"🔍 data.{key}: {type(value)} = {str(value)[:100]}...")
        
        # 파일 기록 (비활성화)
        # if self.log_file:
        #     record_str = json.dumps(event_record, ensure_ascii=False, default=str, separators=(',', ':'))
        #     try:
        #         with open(self.log_file, "a", encoding="utf-8") as f:
        #             f.write(record_str + "\n")
        #             f.flush()  # 즉시 디스크에 쓰기
        #     except Exception as e:
        #         logger.error(f"❌ 파일 저장 실패 (ID: {event_record.get('id', 'unknown')}): {e}")
        #         # 백업 파일에 저장 시도
        #         try:
        #             backup_file = self.log_file + ".backup"
        #             backup_record_str = json.dumps(event_record, ensure_ascii=False, default=str, separators=(',', ':'))
        #             with open(backup_file, "a", encoding="utf-8") as f:
        #                 f.write(backup_record_str + "\n")
        #                 f.flush()
        #             logger.warning(f"⚠️ 백업 파일에 저장됨: {backup_file}")
        #         except Exception as backup_e:
        #             logger.error(f"❌ 백업 파일 저장도 실패: {backup_e}")

    # === Event Processing Entry Point ===
    def on_event(self, event_obj: TypeAny, source: Optional[TypeAny] = None) -> None:
        """Task와 Tool 이벤트 처리 (Agent/Crew 이벤트는 완전히 제외)"""
        try:
            # 🚫 Crew 이벤트 완전 차단
            if event_obj.type.startswith('crew_'):
                return  # 조용히 무시
            
            # 🚫 Agent 이벤트 완전 차단 (사용자 요청)
            if event_obj.type.startswith('agent_'):
                return  # 조용히 무시
            
            # ✅ Task 이벤트와 Tool 이벤트만 처리
            if not (event_obj.type.startswith('task_') or event_obj.type.startswith('tool_')):
                return  # 조용히 무시
            
            # 중복 제거
            event_signature = self._create_event_signature(event_obj, source)
            if event_signature in self._processed_events:
                return  # 중복 이벤트 무시
            
            self._processed_events.add(event_signature)
            
            # job_id 생성 및 데이터 추출
            job_id = self._generate_job_id(event_obj, source)
            event_data = self._extract_event_data(event_obj, source)
            
            # 🆕 현재 컨텍스트에서 crew_type, todo_id 및 proc_inst_id 가져오기
            current_context = GlobalContextManager.get_current_context()
            crew_type = current_context.get("output_type") if current_context else "unknown"
            todo_id = current_context.get("todo_id") if current_context else None
            proc_inst_id = current_context.get("proc_inst_id") if current_context else None
            
            # 🔧 data 필드를 안전하게 직렬화 가능한 형태로 변환
            safe_data = {}
            for key, value in event_data.items():
                try:
                    # TaskOutput 객체 처리
                    if hasattr(value, 'raw'):
                        safe_data[key] = str(value.raw)
                    # 기타 복잡한 객체 처리
                    elif hasattr(value, '__dict__') and not isinstance(value, (str, int, float, bool, type(None))):
                        safe_data[key] = str(value)
                    else:
                        safe_data[key] = value
                except Exception as e:
                    logger.warning(f"Data 직렬화 실패 ({key}): {e}")
                    safe_data[key] = f"[직렬화 실패: {type(value).__name__}]"
            
            # 🆕 단순화된 스키마로 레코드 생성
            event_record = {
                "id": str(uuid.uuid4()),
                "run_id": self.run_id,
                "job_id": job_id,
                "todo_id": todo_id,              # todolist 항목 ID
                "proc_inst_id": proc_inst_id,    # 프로세스 인스턴스 ID
                "event_type": event_obj.type,
                "crew_type": crew_type,
                "data": safe_data,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            
            # 백엔드에 기록
            self._write_to_backends(event_record)
            
            # 출신 정보 포함한 상세한 콘솔 출력
            tool_info = f" ({safe_data.get('tool_name', 'unknown tool')})" if event_obj.type.startswith('tool_') else ""
            print(f"📝 [{event_obj.type}]{tool_info} [{crew_type}] {job_id[:8]} → 파일: ❌(비활성화), Supabase: {'✅' if self.supabase_client else '❌'}")
            
        except Exception as e:
            logger.error(f"❌ 이벤트 처리 실패 ({getattr(event_obj, 'type', 'unknown')}): {e}")

    # === Statistics ===
    def get_stats(self) -> Dict[str, Any]:
        """로거 통계 반환"""
        return {
            "run_id": self.run_id,
            "processed_events": len(self._processed_events),
            "supabase_enabled": self.supabase_client is not None,
            "file_logging_enabled": self.log_file is not None,
            "log_file": self.log_file
        }

    # === Custom Event Emission ===
    def emit_task_started(self, role: str, goal: str, job_id: str = "final_compilation"):
        """🆕 커스텀 task_started 이벤트 발행 (crew_type 포함)"""
        # 🆕 현재 컨텍스트에서 crew_type, todo_id, proc_inst_id 가져오기
        current_context = GlobalContextManager.get_current_context()
        crew_type = current_context.get("output_type") if current_context else "unknown"
        todo_id = current_context.get("todo_id") if current_context else None
        proc_inst_id = current_context.get("proc_inst_id") if current_context else None
        agent_profile = GlobalContextManager.get_profile_by_role(role)
        
        event_record = {
            "id": str(uuid.uuid4()),
            "run_id": self.run_id,
            "job_id": job_id,
            "todo_id": todo_id,              # ✅ todo_id 추가
            "proc_inst_id": proc_inst_id,    # ✅ proc_inst_id 추가
            "event_type": "task_started",     # type → event_type
            "crew_type": crew_type,           # 🆕 커스텀 이벤트에도 crew_type 적용!
            "data": {
                "role": role,
                "goal": goal,
                "agent_profile": agent_profile
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self._write_to_backends(event_record)
        print(f"📝 [task_started] [{crew_type}] {job_id[:8]} → 파일: ❌(비활성화), Supabase: {'✅' if self.supabase_client else '❌'}")

    def emit_task_completed(self, final_result: str, job_id: str = "final_compilation"):
        """🆕 커스텀 task_completed 이벤트 발행 (crew_type 포함)"""
        # 🆕 현재 컨텍스트에서 crew_type, todo_id, proc_inst_id 가져오기
        current_context = GlobalContextManager.get_current_context()
        crew_type = current_context.get("output_type") if current_context else "unknown"
        todo_id = current_context.get("todo_id") if current_context else None
        proc_inst_id = current_context.get("proc_inst_id") if current_context else None
        
        event_record = {
            "id": str(uuid.uuid4()),
            "run_id": self.run_id,
            "job_id": job_id,
            "todo_id": todo_id,              # ✅ todo_id 추가
            "proc_inst_id": proc_inst_id,    # ✅ proc_inst_id 추가
            "event_type": "task_completed",   # type → event_type
            "crew_type": crew_type,           # 🆕 커스텀 이벤트에도 crew_type 적용!
            "data": {
                "final_result": final_result
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self._write_to_backends(event_record)
        print(f"📝 [task_completed] [{crew_type}] {job_id[:8]} → 파일: ❌(비활성화), Supabase: {'✅' if self.supabase_client else '❌'}")

    def emit_crew_started(self, crew_name: str, topic: str, job_id: str = "crew_execution"):
        """🆕 crew_started 이벤트 발행 - 전체 crew 작업 시작"""
        # 현재 컨텍스트에서 crew_type, todo_id, proc_inst_id 가져오기
        current_context = GlobalContextManager.get_current_context()
        crew_type = current_context.get("output_type") if current_context else "unknown"
        todo_id = current_context.get("todo_id") if current_context else None
        proc_inst_id = current_context.get("proc_inst_id") if current_context else None
        
        event_record = {
            "id": str(uuid.uuid4()),
            "run_id": self.run_id,
            "job_id": job_id,
            "todo_id": todo_id,              # ✅ todo_id 추가
            "proc_inst_id": proc_inst_id,    # ✅ proc_inst_id 추가
            "event_type": "crew_started",
            "crew_type": crew_type,
            "data": {
                "crew_name": crew_name,
                "topic": topic
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self._write_to_backends(event_record)
        print(f"🚀 [crew_started] [{crew_type}] {crew_name} → {job_id[:8]} → 파일: ❌(비활성화), Supabase: {'✅' if self.supabase_client else '❌'}")

    def emit_crew_completed(self, crew_name: str, topic: str, job_id: str = "crew_execution"):
        """🆕 crew_completed 이벤트 발행 - 전체 crew 작업 완료"""
        # 현재 컨텍스트에서 crew_type, todo_id, proc_inst_id 가져오기
        current_context = GlobalContextManager.get_current_context()
        crew_type = current_context.get("output_type") if current_context else "unknown"
        todo_id = current_context.get("todo_id") if current_context else None
        proc_inst_id = current_context.get("proc_inst_id") if current_context else None
        
        event_record = {
            "id": str(uuid.uuid4()),
            "run_id": self.run_id,
            "job_id": job_id,
            "todo_id": todo_id,              # ✅ todo_id 추가
            "proc_inst_id": proc_inst_id,    # ✅ proc_inst_id 추가
            "event_type": "crew_completed",
            "crew_type": crew_type,
            "data": {
                "crew_name": crew_name,
                "topic": topic
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self._write_to_backends(event_record)
        print(f"✅ [crew_completed] [{crew_type}] {crew_name} → {job_id[:8]} → 파일: ❌(비활성화), Supabase: {'✅' if self.supabase_client else '❌'}")


# 호환성을 위한 별칭
SupabaseGlobalListener = CrewAIEventLogger 