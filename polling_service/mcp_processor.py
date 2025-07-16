import json
import asyncio
from typing import List, Dict, Any, Optional
from langchain_mcp_adapters import MCPAdapter
from langchain.schema import HumanMessage, SystemMessage
import os
from dotenv import load_dotenv

load_dotenv()

class MCPProcessor:
    def __init__(self):
        self.adapters = {}
        self.mcp_configs = {}
    
    async def get_mcp_tools_from_tenant(self, tenant_id: str, agent_id: str) -> Dict[str, Any]:
        """
        테넌트의 mcp 설정에서 에이전트의 tools를 확인하고 가져옵니다.
        """
        try:
            # 데이터베이스에서 tenants 테이블의 mcp 컬럼 조회
            from database import fetch_tenant_mcp_config
            
            mcp_config = fetch_tenant_mcp_config(tenant_id)
            if not mcp_config:
                print(f"[WARNING] No MCP config found for tenant: {tenant_id}")
                return {}
            
            # 에이전트 정보 조회
            from database import fetch_user_info
            agent_info = fetch_user_info(agent_id)
            if not agent_info:
                print(f"[ERROR] Agent not found: {agent_id}")
                return {}
            
            # 에이전트의 tools 확인
            agent_tools = agent_info.get("tools", [])
            if not agent_tools:
                print(f"[WARNING] No tools found for agent: {agent_id}")
                return {}
            
            # MCP 설정에서 해당 tools가 있는지 확인
            available_tools = {}
            for tool_name in agent_tools:
                if tool_name in mcp_config:
                    available_tools[tool_name] = mcp_config[tool_name]
                    print(f"[INFO] Found MCP tool: {tool_name} for agent: {agent_id}")
                else:
                    print(f"[WARNING] Tool {tool_name} not found in MCP config for tenant: {tenant_id}")
            
            return available_tools
            
        except Exception as e:
            print(f"[ERROR] Failed to get MCP tools from tenant: {str(e)}")
            return {}
    
    async def initialize_mcp_adapters(self, tenant_id: str, agent_id: str) -> bool:
        """
        MCP 어댑터들을 초기화합니다.
        """
        try:
            available_tools = await self.get_mcp_tools_from_tenant(tenant_id, agent_id)
            if not available_tools:
                return False
            
            # 각 tool에 대해 MCP 어댑터 생성
            for tool_name, tool_config in available_tools.items():
                try:
                    # MCP 어댑터 초기화 (실제 API에 맞게 수정)
                    adapter = MCPAdapter(
                        server_url=tool_config.get("server_url"),
                        server_name=tool_name,
                        config=tool_config.get("config", {})
                    )
                    self.adapters[tool_name] = adapter
                    self.mcp_configs[tool_name] = tool_config
                    print(f"[INFO] Initialized MCP adapter for tool: {tool_name}")
                    
                except Exception as e:
                    print(f"[ERROR] Failed to initialize MCP adapter for tool {tool_name}: {str(e)}")
                    continue
            
            return len(self.adapters) > 0
            
        except Exception as e:
            print(f"[ERROR] Failed to initialize MCP adapters: {str(e)}")
            return False
    
    async def execute_mcp_tools(self, workitem: Dict[str, Any], agent_id: str, tenant_id: str) -> Dict[str, Any]:
        """
        MCP 도구들을 사용하여 서비스 업무를 실행합니다.
        """
        try:
            # MCP 어댑터 초기화
            if not await self.initialize_mcp_adapters(tenant_id, agent_id):
                return {"error": "Failed to initialize MCP adapters"}
            
            # 워크아이템에서 필요한 정보 추출
            activity_id = workitem.get('activity_id')
            proc_inst_id = workitem.get('proc_inst_id')
            output = workitem.get('output', {})
            
            # 각 어댑터에 대해 작업 실행
            results = {}
            for tool_name, adapter in self.adapters.items():
                try:
                    # 툴별 실행 로직
                    result = await self._execute_single_mcp_tool(
                        adapter, tool_name, workitem, output
                    )
                    results[tool_name] = result
                    
                except Exception as e:
                    print(f"[ERROR] Failed to execute MCP tool {tool_name}: {str(e)}")
                    results[tool_name] = {"error": str(e)}
            
            return results
            
        except Exception as e:
            print(f"[ERROR] Failed to execute MCP tools: {str(e)}")
            return {"error": str(e)}
    
    async def _execute_single_mcp_tool(self, adapter: MCPAdapter, tool_name: str, 
                                      workitem: Dict[str, Any], output: Dict[str, Any]) -> Dict[str, Any]:
        """
        단일 MCP 도구를 실행합니다.
        """
        try:
            # 툴별 실행 로직 구현
            if tool_name == "file_system":
                return await self._execute_file_system_tool(adapter, workitem, output)
            elif tool_name == "database":
                return await self._execute_database_tool(adapter, workitem, output)
            elif tool_name == "web_search":
                return await self._execute_web_search_tool(adapter, workitem, output)
            else:
                # 기본 실행 로직
                return await self._execute_generic_tool(adapter, workitem, output)
                
        except Exception as e:
            print(f"[ERROR] Failed to execute single MCP tool {tool_name}: {str(e)}")
            return {"error": str(e)}
    
    async def _execute_file_system_tool(self, adapter: MCPAdapter, workitem: Dict[str, Any], 
                                       output: Dict[str, Any]) -> Dict[str, Any]:
        """
        파일 시스템 도구 실행
        """
        try:
            # 파일 시스템 관련 작업 수행
            # 예: 파일 읽기, 쓰기, 디렉토리 탐색 등
            command = output.get("command", "list")
            path = output.get("path", "/")
            
            # MCP 어댑터를 통해 파일 시스템 작업 실행
            # 실제 MCP 어댑터 API에 맞게 수정
            result = await adapter.ainvoke({
                "command": command,
                "path": path,
                "workitem_id": workitem.get('id')
            })
            
            return {
                "tool": "file_system",
                "status": "success",
                "result": result
            }
            
        except Exception as e:
            return {
                "tool": "file_system",
                "status": "error",
                "error": str(e)
            }
    
    async def _execute_database_tool(self, adapter: MCPAdapter, workitem: Dict[str, Any], 
                                    output: Dict[str, Any]) -> Dict[str, Any]:
        """
        데이터베이스 도구 실행
        """
        try:
            # 데이터베이스 관련 작업 수행
            # 예: 쿼리 실행, 데이터 조회, 업데이트 등
            query = output.get("query", "")
            operation = output.get("operation", "select")
            
            # MCP 어댑터를 통해 데이터베이스 작업 실행
            result = await adapter.ainvoke({
                "operation": operation,
                "query": query,
                "workitem_id": workitem.get('id')
            })
            
            return {
                "tool": "database",
                "status": "success",
                "result": result
            }
            
        except Exception as e:
            return {
                "tool": "database",
                "status": "error",
                "error": str(e)
            }
    
    async def _execute_web_search_tool(self, adapter: MCPAdapter, workitem: Dict[str, Any], 
                                      output: Dict[str, Any]) -> Dict[str, Any]:
        """
        웹 검색 도구 실행
        """
        try:
            # 웹 검색 관련 작업 수행
            query = output.get("query", "")
            search_type = output.get("search_type", "web")
            
            # MCP 어댑터를 통해 웹 검색 작업 실행
            result = await adapter.ainvoke({
                "search_type": search_type,
                "query": query,
                "workitem_id": workitem.get('id')
            })
            
            return {
                "tool": "web_search",
                "status": "success",
                "result": result
            }
            
        except Exception as e:
            return {
                "tool": "web_search",
                "status": "error",
                "error": str(e)
            }
    
    async def _execute_generic_tool(self, adapter: MCPAdapter, workitem: Dict[str, Any], 
                                   output: Dict[str, Any]) -> Dict[str, Any]:
        """
        일반적인 도구 실행
        """
        try:
            # 기본 실행 로직
            result = await adapter.ainvoke({
                "workitem": workitem,
                "output": output
            })
            
            return {
                "tool": "generic",
                "status": "success",
                "result": result
            }
            
        except Exception as e:
            return {
                "tool": "generic",
                "status": "error",
                "error": str(e)
            }
    
    def cleanup(self):
        """
        리소스 정리
        """
        try:
            for adapter in self.adapters.values():
                if hasattr(adapter, 'close'):
                    adapter.close()
            self.adapters.clear()
            self.mcp_configs.clear()
            print("[INFO] MCP adapters cleaned up")
            
        except Exception as e:
            print(f"[ERROR] Failed to cleanup MCP adapters: {str(e)}")

# 전역 MCP 프로세서 인스턴스
mcp_processor = MCPProcessor()
