import asyncio
import json
import os
import re
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple
from pathlib import Path

from crewai.flow.flow import Flow, listen, start
from pydantic import BaseModel, Field

from .dynamic_report_flow import DynamicReportFlow
from ..crews.planning_crew.ExecutionPlanningCrew import ExecutionPlanningCrew
from ..crews.slide_crew.SlideCrew import SlideCrew
from ..crews.form_crew.FormCrew import FormCrew
from ..crew_config_manager import CrewConfigManager
from ..event_logging.crew_event_logger import GlobalContextManager
from ..context_manager import context_manager


# 🔧 Configuration Constants
class Config:
    OUTPUT_DIR = "outputs"
    CONTENT_SEPARATOR = "\n\n---\n\n"
    TIMESTAMP_FORMAT = "%Y%m%d_%H%M%S"
    ERROR_PREFIX = "Error:"
    FILE_EXTENSIONS = {
        "report": ".md",
        "slide": ".md", 
        "text": ".json",
        "planning": ".json"
    }
    # JSON 저장 형식 구분
    JSON_PRETTY_INDENT = 2          # outputs용: pretty 형식
    JSON_LOG_SEPARATORS = (',', ':')  # logs용: 한줄 압축


class ExecutionPlan(BaseModel):
    """AI-generated execution plan for form types."""
    ai_plan: Dict[str, Any] = Field(default_factory=dict)
    report_forms: List[Dict[str, Any]] = Field(default_factory=list)
    slide_forms: List[Dict[str, Any]] = Field(default_factory=list) 
    text_forms: List[Dict[str, Any]] = Field(default_factory=list)


class MultiFormatState(BaseModel):
    """State for the multi-format content generation flow."""
    topic: str = ""
    form_types: List[Dict[str, Any]] = Field(default_factory=list)
    user_info: Dict[str, Any] = Field(default_factory=dict)
    todo_id: Optional[str] = None
    proc_inst_id: Optional[str] = None
    form_id: Optional[str] = None
    
    # Planning results
    execution_plan: Optional[ExecutionPlan] = None
    
    # Generated content by form_id
    report_contents: Dict[str, str] = Field(default_factory=dict)
    slide_contents: Dict[str, str] = Field(default_factory=dict)
    text_contents: Dict[str, Any] = Field(default_factory=dict)
    
    # Results mapping (form_id -> filename)
    results: Dict[str, str] = Field(default_factory=dict)


class MultiFormatFlow(Flow[MultiFormatState]):
    """
    Enhanced Multi-Format Content Generation Flow with Advanced Optimizations
    
    🚀 Features:
    - Shared timestamp and cached topic sanitization
    - Content caching and reuse optimization
    - Crew instance reuse when possible
    - Optimized JSON parsing with smart pattern ordering
    - Advanced memory management with cleanup
    """

    def __init__(self, enable_supabase_logging: bool = True, enable_file_logging: bool = True, output_dir: str = None):
        super().__init__(
            description="Advanced optimized flow for generating multiple content formats",
            state_type=MultiFormatState
        )
        
        self.crew_manager = CrewConfigManager(
            enable_supabase_logging=enable_supabase_logging,
            enable_file_logging=enable_file_logging
        )
        
        # 🔧 Advanced optimization: Pre-cache frequently used values
        self.output_dir = Path(output_dir or Config.OUTPUT_DIR)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # 🚀 Flow-level cached values (computed once, reused many times)
        self._flow_timestamp = None
        self._sanitized_topic = None
        self._combined_report_content = None
        self._combined_slide_content = None
        
        # 🔧 Pre-compile regex patterns with optimized order (most likely first)
        self._json_patterns = [
            re.compile(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', re.DOTALL),  # Simple JSON first
            re.compile(r'```(?:json)?\s*(\{.*?\})\s*```', re.DOTALL | re.IGNORECASE)  # Code blocks second
        ]
        
        # 🔄 Crew instance cache for reuse
        self._crew_cache = {}
        
        print(f"🎯 MultiFormatFlow 초기화 완료 - Supabase: {'✅' if enable_supabase_logging else '❌'}, 파일: {'✅' if enable_file_logging else '❌'}")
        print(f"[DEBUG] context_manager id (조회): {id(context_manager)}")

    def _get_previous_context(self) -> Dict[str, Any]:
        """현재 proc_inst_id에 해당하는 이전 작업 컨텍스트를 가져옵니다."""
        if not self.state.proc_inst_id:
            print("⚠️ proc_inst_id가 없어서 빈 컨텍스트 반환")
            return {}
        
        print(f"🔍 [MultiFormatFlow] 이전 컨텍스트 조회 중: proc_inst_id={self.state.proc_inst_id}")
        previous_context = context_manager.get_context(self.state.proc_inst_id) or {}
        print(f"[DEBUG] 파일에서 읽은 컨텍스트: {previous_context}")
        print(f"🔍 [MultiFormatFlow] 조회 완료: {len(previous_context)}개 이전 작업 발견")
        
        return previous_context

    def _get_flow_timestamp(self) -> str:
        """Get cached flow timestamp (computed once per flow execution)."""
        if self._flow_timestamp is None:
            self._flow_timestamp = datetime.now().strftime(Config.TIMESTAMP_FORMAT)
        return self._flow_timestamp

    def _get_sanitized_topic(self) -> str:
        """Get cached sanitized topic (computed once per flow execution)."""
        if self._sanitized_topic is None:
            self._sanitized_topic = self.state.topic.replace(" ", "_").replace("/", "_").replace("\\", "_")
        return self._sanitized_topic

    def _generate_filename(self, prefix: str, form_id: str, extension: str) -> str:
        """Generate standardized filename with cached values."""
        timestamp = self._get_flow_timestamp()
        topic_safe = self._get_sanitized_topic()
        return f"{prefix}_{form_id}_{topic_safe}_{timestamp}{extension}"

    def _is_error_content(self, content: str) -> bool:
        """Check if content represents an error."""
        return content.startswith(Config.ERROR_PREFIX)

    def _filter_valid_content(self, content_dict: Dict[str, str]) -> List[str]:
        """Filter out error content and return valid content list."""
        return [content for content in content_dict.values() 
                if content and not self._is_error_content(content)]

    def _get_cached_report_content(self) -> str:
        """Get cached combined report content."""
        if self._combined_report_content is None:
            valid_reports = self._filter_valid_content(self.state.report_contents)
            self._combined_report_content = Config.CONTENT_SEPARATOR.join(valid_reports)
        return self._combined_report_content

    def _get_cached_slide_content(self) -> str:
        """Get cached combined slide content."""
        if self._combined_slide_content is None:
            valid_slides = self._filter_valid_content(self.state.slide_contents)
            self._combined_slide_content = Config.CONTENT_SEPARATOR.join(valid_slides)
        return self._combined_slide_content

    def _save_file(self, content: str, filepath: Path) -> bool:
        """Save content to file with enhanced error handling."""
        try:
            filepath.write_text(content, encoding="utf-8")
            return True
        except Exception as e:
            print(f"❌ 파일 저장 실패 {filepath}: {e}")
            return False

    def _save_json(self, data: Dict[str, Any], filepath: Path, pretty: bool = True) -> bool:
        """Save JSON data with configurable formatting."""
        try:
            with filepath.open("w", encoding="utf-8") as f:
                if pretty:
                    # outputs용: pretty 형식 (가독성 우선)
                    json.dump(data, f, ensure_ascii=False, indent=Config.JSON_PRETTY_INDENT)
                else:
                    # logs용: 한줄 압축 (로그 형태)
                    json.dump(data, f, ensure_ascii=False, separators=Config.JSON_LOG_SEPARATORS)
            return True
        except Exception as e:
            print(f"❌ JSON 저장 실패 {filepath}: {e}")
            return False

    def _emit_crew_events(self, crew_name: str, job_id: str, started: bool = True, failed: bool = False):
        """Utility method for crew event emission."""
        topic = f"FAILED: {self.state.topic}" if failed else self.state.topic
        
        if started:
            self.crew_manager.event_logger.emit_crew_started(
                crew_name=crew_name, topic=topic, job_id=job_id
            )
        else:
            self.crew_manager.event_logger.emit_crew_completed(
                crew_name=crew_name, topic=topic, job_id=job_id
            )

    def _manage_context(self, output_type: str, form_id: str, filename: str):
        """Context manager for GlobalContextManager operations."""
        class ContextManager:
            def __enter__(context_self):
                GlobalContextManager.set_context(
                    output_type=output_type, 
                    form_id=form_id, 
                    filename=filename,
                    todo_id=self.state.todo_id,      # ✅ todo_id 추가
                    proc_inst_id=self.state.proc_inst_id  # ✅ proc_inst_id 추가
                )
                return context_self
            
            def __exit__(context_self, exc_type, exc_val, exc_tb):
                GlobalContextManager.clear_context()
        
        return ContextManager()

    @start()
    async def ai_analyze_and_plan(self):
        """AI-powered planning phase with enhanced optimization."""
        print(f"🤖 실행 계획 생성 중... (주제: {self.state.topic}, 폼: {len(self.state.form_types)}개)")
        
        planning_filename = self._generate_filename("planning_result", "execution_planning", Config.FILE_EXTENSIONS["planning"])
        
        with self._manage_context("planning", "execution_planning", planning_filename):
            try:
                planning_crew = self.crew_manager.create_execution_planning_crew()
                
                self._emit_crew_events("ExecutionPlanningCrew", "planning", started=True)
                
                planning_result = await planning_crew.kickoff_async(inputs={
                    "topic": self.state.topic,
                    "form_types": self.state.form_types,
                    "user_info": self.state.user_info
                })
                
                self._emit_crew_events("ExecutionPlanningCrew", "planning", started=False)
                
                raw_result = planning_result.raw if planning_result else ""
                
                # Save planning result
                self._save_planning_result(raw_result, planning_filename)
                
                # Parse and create execution plan
                plan = self._create_execution_plan(raw_result)
                self.state.execution_plan = plan
                
                print(f"✅ 계획 생성 완료: 리포트 {len(plan.report_forms)}개, 슬라이드 {len(plan.slide_forms)}개, 텍스트 {len(plan.text_forms)}개")
                return plan
                
            except Exception as e:
                print(f"❌ 계획 생성 실패: {e}")
                return self._create_fallback_plan()

    def _create_execution_plan(self, raw_result: str) -> ExecutionPlan:
        """Create execution plan from AI result with fallback."""
        try:
            ai_plan = self._extract_json_from_text(raw_result)
            if not ai_plan:
                ai_plan = json.loads(raw_result)
            
            if "execution_plan" in ai_plan:
                ai_plan = ai_plan["execution_plan"]
            
            plan = ExecutionPlan()
            plan.ai_plan = ai_plan
            self._parse_forms_from_ai_plan(plan)
            return plan
            
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            print(f"❌ JSON 파싱 실패, 기본 계획 사용: {e}")
            return self._create_fallback_plan()

    def _parse_forms_from_ai_plan(self, plan: ExecutionPlan):
        """Parse forms from AI plan with optimized lookup."""
        ai_plan = plan.ai_plan
        
        # Create lookup dict for O(1) form retrieval
        form_lookup = {f.get("key"): f for f in self.state.form_types}
        
        phase_mappings = [
            ("report_phase", "report_forms"), 
            ("slide_phase", "slide_forms"), 
            ("text_phase", "text_forms")
        ]
        
        for phase_name, forms_key in phase_mappings:
            if phase_name in ai_plan and "forms" in ai_plan[phase_name]:
                for form_data in ai_plan[phase_name]["forms"]:
                    form_id = form_data.get("key")
                    if form_id in form_lookup:
                        getattr(plan, forms_key).append(form_lookup[form_id])

    def _create_fallback_plan(self) -> ExecutionPlan:
        """Create optimized fallback plan."""
        plan = ExecutionPlan()
        
        # Single pass through form_types
        for form in self.state.form_types:
            form_type = form.get("type", "").lower()
            if form_type == "report":
                plan.report_forms.append(form)
            elif form_type == "slide":
                plan.slide_forms.append(form)
            elif form_type == "text":
                plan.text_forms.append(form)
        
        plan.ai_plan = {
            "report_phase": {"strategy": "parallel"},
            "slide_phase": {"strategy": "parallel"},
            "text_phase": {"strategy": "batch"}
        }
        
        self.state.execution_plan = plan
        print(f"🔧 기본 계획 생성: {len(plan.report_forms)}R + {len(plan.slide_forms)}S + {len(plan.text_forms)}T")
        return plan

    @listen("ai_analyze_and_plan")
    async def generate_reports(self):
        """Generate reports with enhanced optimization."""
        if not self.state.execution_plan or not self.state.execution_plan.report_forms:
            return "No reports requested"
        
        reports = self.state.execution_plan.report_forms
        print(f"📝 리포트 {len(reports)}개 병렬 생성 시작...")
        
        start_time = datetime.now()
        
        # Parallel execution with comprehensive error handling
        tasks = [self._generate_single_report(form) for form in reports]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Process results with partial failure handling
        success_count = 0
        for form, result in zip(reports, results):
            form_id = form.get("key", "unknown")
            if isinstance(result, Exception):
                print(f"❌ 리포트 {form_id} 생성 실패: {result}")
                self.state.report_contents[form_id] = f"{Config.ERROR_PREFIX} {str(result)}"
            else:
                self.state.report_contents[form_id] = result
                success_count += 1
        
        duration = (datetime.now() - start_time).total_seconds()
        print(f"✅ 리포트 처리 완료 ({success_count}/{len(reports)} 성공, {duration:.2f}초)")
        
        return self.state.report_contents

    async def _generate_single_report(self, report_form: Dict[str, Any]) -> str:
        """Generate single report with optimized management."""
        form_id = report_form.get("key", "unknown")
        filename = self._generate_filename("report", form_id, Config.FILE_EXTENSIONS["report"])
        
        with self._manage_context("report", form_id, filename):
            try:
                flow = DynamicReportFlow(
                    enable_supabase_logging=True,
                    enable_file_logging=True
                )
                
                # 이전 작업 컨텍스트 가져오기
                previous_context = self._get_previous_context() or {}
                
                flow.state.topic = self.state.topic
                flow.state.user_info = self.state.user_info
                flow.state.previous_context = previous_context
                
                report_content = await flow.kickoff_async()
                final_report = flow.state.final_report if hasattr(flow.state, 'final_report') else str(report_content)
                
                # Save file using Path
                filepath = self.output_dir / filename
                if self._save_file(final_report, filepath):
                    self.state.results[form_id] = str(filepath)
                    
                return final_report
                
            except Exception as e:
                print(f"❌ 리포트 {form_id} 생성 실패: {e}")
                return f"Error generating report {form_id}: {str(e)}"

    @listen("generate_reports")
    async def generate_slides(self):
        """Generate slides with advanced content optimization."""
        if not self.state.execution_plan or not self.state.execution_plan.slide_forms:
            return "No slides requested"
        
        slides = self.state.execution_plan.slide_forms
        print(f"🎬 슬라이드 {len(slides)}개 병렬 생성 시작...")
        
        start_time = datetime.now()
        
        # Get cached combined content (computed once, reused for all slides)
        combined_content = self._get_cached_report_content()
        
        tasks = [self._generate_single_slide(form, combined_content) for form in slides]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Process results
        success_count = 0
        for form, result in zip(slides, results):
            form_id = form.get("key", "unknown")
            if isinstance(result, Exception):
                print(f"❌ 슬라이드 {form_id} 생성 실패: {result}")
                self.state.slide_contents[form_id] = f"{Config.ERROR_PREFIX} {str(result)}"
            else:
                self.state.slide_contents[form_id] = result
                success_count += 1
        
        duration = (datetime.now() - start_time).total_seconds()
        print(f"✅ 슬라이드 처리 완료 ({success_count}/{len(slides)} 성공, {duration:.2f}초)")
        
        return self.state.slide_contents

    async def _generate_single_slide(self, slide_form: Dict[str, Any], combined_content: str) -> str:
        """Generate single slide with pre-combined content."""
        form_id = slide_form.get("key", "unknown")
        filename = self._generate_filename("slides", form_id, Config.FILE_EXTENSIONS["slide"])
        
        with self._manage_context("slide", form_id, filename):
            try:
                if not combined_content:
                    print(f"⚠️ 슬라이드 {form_id}용 리포트 내용 없음")
                    return f"No report content available for slide {form_id}"
                
                self._emit_crew_events("SlideCrew", "slide_generation", started=True)
                
                slide_crew = self.crew_manager.create_slide_crew()
                result = await slide_crew.kickoff_async(inputs={
                    "report_content": combined_content,
                    "user_info": self.state.user_info
                })
                
                self._emit_crew_events("SlideCrew", "slide_generation", started=False)
                
                content = result.raw if result else f"Slide content for {form_id}"
                
                # Save file using Path
                filepath = self.output_dir / filename
                if self._save_file(content, filepath):
                    self.state.results[form_id] = str(filepath)
                    
                return content
                
            except Exception as e:
                print(f"❌ 슬라이드 {form_id} 생성 실패: {e}")
                self._emit_crew_events("SlideCrew", "slide_generation", started=False, failed=True)
                return f"Error generating slide {form_id}: {str(e)}"

    @listen("generate_slides")
    async def generate_texts(self):
        """Generate text forms with maximum efficiency reusing cached content."""
        if not self.state.execution_plan or not self.state.execution_plan.text_forms:
            return "No text forms requested"
        
        texts = self.state.execution_plan.text_forms
        fields = [
            {
                "key":  form.get("key", "unknown"),
                "type": form.get("type", "unknown"),
                "text": form.get("text", "")
            }
            for form in texts
        ]
        print(f"📝 텍스트 폼 {len(texts)}개 배치 처리 중: {[f['key'] for f in fields]}")

        
        json_filename = self._generate_filename("form_data_ALL", "text_generation", Config.FILE_EXTENSIONS["text"])
        
        with self._manage_context("text", "text_generation", json_filename):
            try:
                # Reuse cached combined content (no duplicate computation)
                all_reports = self._get_cached_report_content()
                
                self._emit_crew_events("FormCrew", "text_generation", started=True)
                
                form_crew = self.crew_manager.create_form_crew()
                result = await form_crew.kickoff_async(inputs={
                    "report_content": all_reports,
                    "topic": self.state.topic,
                    "field_info": fields,
                    "user_info": self.state.user_info
                })
                
                self._emit_crew_events("FormCrew", "text_generation", started=False)
                
                # Parse result
                raw_data = result.raw if result else ""
                batch_json = self._extract_json_from_text(raw_data)
                
                if not batch_json:
                    print("⚠️ JSON 파싱 실패, 기본 데이터 생성")
                    batch_json = {field_name: f"Generated value for {field_name}" for field_name in field_names}
                
                # Save JSON file using Path
                json_filepath = self.output_dir / json_filename
                if self._save_json(batch_json, json_filepath):
                    # Store results
                    self.state.text_contents = batch_json
                    for form in texts:
                        self.state.results[form.get("id", "unknown")] = str(json_filepath)
                    
                    print(f"✅ 텍스트 배치 처리 완료 - 필드 {len(batch_json)}개 생성: {json_filename}")
                
                # 🧹 Memory cleanup: Clear cached content after final use
                self._cleanup_cached_content()
                
                return self.state.text_contents
                
            except Exception as e:
                print(f"❌ 텍스트 배치 생성 실패: {e}")
                self._emit_crew_events("FormCrew", "text_generation", started=False, failed=True)
                return {"error": str(e)}

    def _cleanup_cached_content(self):
        """Clean up cached content to free memory."""
        self._combined_report_content = None
        self._combined_slide_content = None

    def _extract_json_from_text(self, text: str) -> Dict[str, Any]:
        """Extract JSON from text with advanced nested structure handling."""
        if not text or not text.strip():
            return {}
        
        # Strategy 1: Direct JSON parsing (fastest)
        try:
            return json.loads(text.strip())
        except json.JSONDecodeError:
            pass
        
        # Strategy 2: Enhanced code block extraction with proper nesting
        code_block_pattern = r'```(?:json)?\s*([\s\S]*?)\s*```'
        code_matches = re.findall(code_block_pattern, text, re.IGNORECASE)
        
        for match in code_matches:
            try:
                return json.loads(match.strip())
            except json.JSONDecodeError:
                continue
        
        # Strategy 3: Balanced brace matching for nested JSON
        def find_complete_json(text):
            """Find complete JSON objects with balanced braces."""
            start_idx = text.find('{')
            if start_idx == -1:
                return None
                
            brace_count = 0
            in_string = False
            escape_next = False
            
            for i in range(start_idx, len(text)):
                char = text[i]
                
                if escape_next:
                    escape_next = False
                    continue
                    
                if char == '\\':
                    escape_next = True
                    continue
                    
                if char == '"' and not escape_next:
                    in_string = not in_string
                    continue
                    
                if not in_string:
                    if char == '{':
                        brace_count += 1
                    elif char == '}':
                        brace_count -= 1
                        if brace_count == 0:
                            return text[start_idx:i+1]
            
            return None
        
        json_text = find_complete_json(text)
        if json_text:
            try:
                return json.loads(json_text)
            except json.JSONDecodeError:
                pass
        
        return {}

    def _save_planning_result(self, raw_planning_result: str, filename: str):
        """Save planning result with enhanced data structure."""
        try:
            parsed_plan = self._extract_json_from_text(raw_planning_result)
            
            planning_data = {
                "timestamp": self._get_flow_timestamp(),
                "topic": self.state.topic,
                "form_types": self.state.form_types,
                "raw_planning_result": raw_planning_result,
                "parsed_planning_result": parsed_plan if parsed_plan else None,
                "parsing_note": "Successfully parsed" if parsed_plan else "Could not extract JSON from response"
            }
            
            filepath = self.output_dir / filename
            if self._save_json(planning_data, filepath):
                print(f"💾 계획 결과 저장: {filename}")
            
        except Exception as e:
            print(f"⚠️ 계획 결과 저장 실패: {e}")

    @listen("generate_texts")
    def finalize_results(self):
        """Enhanced final summary with advanced statistics."""
        print("\n" + "="*60)
        print("🎉 MULTI-FORMAT GENERATION COMPLETED!")
        print("="*60)
        
        unique_files = set(self.state.results.values())
        
        # Advanced statistics calculation
        total_forms = len(self.state.form_types)
        successful_forms = len([r for r in self.state.results.values() if r])
        success_rate = (successful_forms / total_forms * 100) if total_forms > 0 else 0
        
        # Detailed error analysis
        error_reports = sum(1 for content in self.state.report_contents.values() 
                           if self._is_error_content(content))
        error_slides = sum(1 for content in self.state.slide_contents.values() 
                          if self._is_error_content(content))
        
        print(f"📊 처리 결과: {successful_forms}/{total_forms} 성공 ({success_rate:.1f}%)")
        if error_reports or error_slides:
            print(f"⚠️  실패 상세: 리포트 {error_reports}개, 슬라이드 {error_slides}개")
        
        print(f"📁 생성된 파일 {len(unique_files)}개:")
        
        for filepath in unique_files:
            filename = Path(filepath).name
            usage_count = sum(1 for f in self.state.results.values() if f == filepath)
            usage_info = f" (공유: {usage_count}개 폼)" if usage_count > 1 else ""
            print(f"  📄 {filename}{usage_info}")
        
        if self.state.execution_plan:
            plan = self.state.execution_plan
            print(f"\n📋 요약: 리포트 {len(plan.report_forms)}개, 슬라이드 {len(plan.slide_forms)}개, 텍스트 필드 {len(plan.text_forms)}개")
        
        print(f"✅ 모든 파일이 {self.output_dir}/ 폴더에 저장되었습니다!")
        
        # report, slide, text 각각의 key→content 딕셔너리 가져오기
        merged_contents = {}
        merged_contents.update(self.state.report_contents)
        merged_contents.update(self.state.slide_contents)
        merged_contents.update(self.state.text_contents)
        
        # 🆕 새로운 형식: 리포트와 폼을 구분해서 저장 (컨텍스트용)
        new_format = {
            "reports": {},
            "forms": {}
        }
        
        # 리포트 내용 추가
        for report_key, report_content in self.state.report_contents.items():
            if not self._is_error_content(report_content):
                new_format["reports"][report_key] = report_content
        
        # 폼 데이터 추가 (text_contents)
        for form_key, form_value in self.state.text_contents.items():
            if not self._is_error_content(str(form_value)):
                new_format["forms"][form_key] = form_value
        
        # 기존 형식: todolist_poller에서 전달받은 form_id를 사용하여 올바른 구조로 반환
        # form_id는 "formHandler:" 접두어가 제거된 실제 form_def의 id 값
        form_id = getattr(self.state, 'form_id', None)
        if not form_id:
            # fallback: todo_id나 기본값 사용
            form_id = self.state.todo_id or 'default_form'
        
        legacy_format = { form_id: merged_contents }
        
        print(f"\n📊 반환 데이터 요약:")
        print(f"   기존 형식: {form_id} → {len(merged_contents)}개 항목")
        print(f"   새 형식: {len(new_format['reports'])}개 리포트, {len(new_format['forms'])}개 폼")
        
        return (legacy_format, new_format)


def plot():
    """Plot the flow diagram."""
    flow = MultiFormatFlow()
    flow.plot() 

print(f"[DEBUG] context_manager id (조회): {id(context_manager)}") 