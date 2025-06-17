"""
Simple Tool Loader - 간소화된 버전 (tool_names만 사용)
"""

import os
import json
from typing import Dict, List, Any, Optional
import platform
import tempfile
import subprocess
import anyio
from anyio._core._subprocesses import open_process as _original_open_process


class SafeToolLoader:
    """도구 이름만 관리하는 간소화된 로더"""
    
    def __init__(self, 
                 security_config_path: str = None):
        # 현재 파일의 위치를 기준으로 절대 경로 생성
        if security_config_path is None:
            current_dir = os.path.dirname(os.path.abspath(__file__))  # AgentMonitoring/src/parallel/
            config_dir = os.path.join(current_dir, "..", "..", "config")  # AgentMonitoring/config/
            security_config_path = os.path.join(config_dir, "tool_security.json")
        
        self.security_config_path = security_config_path
        
        # 보안 설정 로드
        self.security_config = self._load_security_config()
        
        print("✅ SafeToolLoader 초기화 완료 (간소화된 버전)")
    
    def _load_security_config(self) -> Dict[str, Any]:
        """보안 설정 파일 로드"""
        try:
            if os.path.exists(self.security_config_path):
                with open(self.security_config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    print(f"✅ 보안 설정 로드: {config.get('description', '알 수 없음')}")
                    return config
            else:
                print(f"⚠️  보안 설정 파일이 없습니다: {self.security_config_path}")
        except Exception as e:
            print(f"❌ 보안 설정 로드 실패: {e}")
        
        # 기본 설정
        return {
            "security_policy": "allowlist",
            "allowed_tools": ["mem0", "perplexity(mcp)"],
            "description": "기본 안전 정책"
        }
    
    def create_tools_from_names(self, tool_names: List[str]) -> List:
        """tool_names 리스트에서 실제 Tool 객체들 생성"""
        print(f"🔧 도구 객체 생성 요청: {tool_names}")
        
        if not tool_names:
            print("⚠️  tool_names가 비어있음 - 빈 리스트 반환")
            return []
        
        tools = []
        
        for tool_name in tool_names:
            print(f"🔍 도구 생성 중: {tool_name}")
            
            if tool_name == "mem0":
                try:
                    from .knowledge_manager import Mem0Tool
                    mem0_tool = Mem0Tool()
                    tools.append(mem0_tool)
                    print(f"✅ {tool_name} 도구 생성 완료")
                except Exception as e:
                    print(f"❌ {tool_name} 도구 생성 실패: {e}")
            
            elif tool_name == "perplexity(mcp)":
                try:
                    from mcp import StdioServerParameters
                    from crewai_tools import MCPServerAdapter
                    
                    # 모든 플랫폼에서 MCP stderr 몽키패치 적용
                    print(f"🔧 MCP stderr 몽키패치 적용 (OS: {platform.system()})")

                    async def _patched_open_process(*args, **kwargs):
                        # 모든 stderr를 PIPE로 강제 교체
                        if 'stderr' in kwargs:
                            stderr_arg = kwargs['stderr']
                            print(f"🔍 원본 stderr 타입: {type(stderr_arg)}")
                            
                            # fileno() 체크를 더 안전하게
                            has_fileno = False
                            try:
                                if hasattr(stderr_arg, 'fileno'):
                                    stderr_arg.fileno()  # 실제 호출 테스트
                                    has_fileno = True
                                    print(f"✅ stderr에 유효한 fileno() 있음")
                            except Exception as e:
                                print(f"❌ stderr.fileno() 실패: {e}")
                                has_fileno = False
                            
                            # fileno()가 없거나 실패하면 PIPE로 교체
                            if not has_fileno:
                                print("🔧 stderr를 subprocess.PIPE로 강제 교체")
                                kwargs['stderr'] = subprocess.PIPE
                            else:
                                print("⚠️  stderr fileno() 작동 - 그대로 유지")
                        
                        return await _original_open_process(*args, **kwargs)

                    # 실제 사용 함수 교체
                    anyio.open_process = _patched_open_process
                    anyio._core._subprocesses.open_process = _patched_open_process
                    print("✅ anyio.open_process 몽키패치 완료")
                    
                    # MCP 설정 로드
                    # 현재 파일 위치를 기준으로 절대 경로 생성
                    current_dir = os.path.dirname(os.path.abspath(__file__))  # AgentMonitoring/src/parallel/
                    config_dir = os.path.join(current_dir, "..", "..", "config")  # AgentMonitoring/config/
                    mcp_config_path = os.path.join(config_dir, "mcp.json")
                    if os.path.exists(mcp_config_path):
                        with open(mcp_config_path, 'r') as f:
                            mcp_config = json.load(f)
                            
                        if "perplexity" in mcp_config.get("mcpServers", {}):
                            server_config = mcp_config["mcpServers"]["perplexity"]
                            
                            print(f"🔧 {tool_name} MCP 연결 시도... (OS: {platform.system()})")
                            
                            mcp_server_params = StdioServerParameters(
                                command=server_config.get("command", "uvx"),
                                args=server_config.get("args", ["perplexity-mcp"]),
                                env=os.environ
                            )
                            
                            print(f"🔧 MCP 어댑터 생성 중...")
                            mcp_server_adapter = MCPServerAdapter(mcp_server_params)
                            tools.extend(mcp_server_adapter.tools)
                            print(f"✅ {tool_name} 도구 생성 완료: {len(mcp_server_adapter.tools)}개")
                                
                        else:
                            print(f"❌ {tool_name} 설정이 MCP 파일에 없습니다")
                    else:
                        print(f"❌ MCP 설정 파일이 없습니다: {mcp_config_path}")
                            
                except Exception as e:
                    print(f"❌ {tool_name} 도구 생성 실패: {e}")
                    print(f"🔄 {tool_name} 없이 계속 진행합니다 (mem0만 사용)")
                    # perplexity 실패해도 계속 진행
            
            else:
                print(f"🚫 지원하지 않는 도구: {tool_name}")
        
        print(f"🎯 최종 생성된 도구: {len(tools)}개")
        return tools
    
    def get_tool_connection_status(self) -> Dict[str, str]:
        """도구 연결 상태 확인 (정보용)"""
        status = {}
        
        # 허용된 도구들
        allowed_tools = self.security_config.get("allowed_tools", ["mem0", "perplexity(mcp)"])
        for tool in allowed_tools:
            status[tool] = "✅ 사용 가능"
        
        # 보안 설정 상태
        status["security_policy"] = f"✅ {self.security_config.get('description', '알 수 없음')}"
        
        return status
    
    def get_available_tools_summary(self) -> str:
        """사용 가능한 도구 요약"""
        allowed_tools = self.security_config.get("allowed_tools", ["mem0", "perplexity(mcp)"])
        
        summary = "🛠️  **사용 가능한 도구 목록:**\n\n"
        
        for i, tool in enumerate(allowed_tools, 1):
            summary += f"{i}. ✅ **{tool}**\n"
        
        summary += "\n**사용법:**\n"
        summary += "- Supabase agents 테이블의 tools 필드에 입력\n"
        summary += f"- 예: `{', '.join(allowed_tools)}`\n"
        
        return summary 