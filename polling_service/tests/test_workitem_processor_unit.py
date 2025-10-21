import sys
import types
import json
import pathlib
import importlib.util
import pytest


# ------------------------------------------------------------
# Helpers: stub external heavy deps BEFORE importing module
# ------------------------------------------------------------
class _DummyPrompt:
    def __init__(self, template: str):
        self.template = template

    def format(self, **kwargs):
        return self.template


class _DummyPromptTemplate:
    @classmethod
    def from_template(cls, template: str):
        return _DummyPrompt(template)


class _DummySimpleJsonOutputParser:
    pass


class _DummyModel:
    async def astream(self, *_args, **_kwargs):
        if False:
            yield None
        return

    def invoke(self, *_args, **_kwargs):
        class R:
            content = ""

        return R()


def _install_stub_modules():
    # langchain.*
    langchain = types.ModuleType("langchain")
    langchain_prompts = types.ModuleType("langchain.prompts")
    langchain_prompts.PromptTemplate = _DummyPromptTemplate
    langchain_schema = types.ModuleType("langchain.schema")
    langchain_schema.Document = object
    langchain_output_parsers = types.ModuleType("langchain.output_parsers")
    langchain_output_parsers_json = types.ModuleType("langchain.output_parsers.json")
    langchain_output_parsers_json.SimpleJsonOutputParser = _DummySimpleJsonOutputParser

    sys.modules["langchain"] = langchain
    sys.modules["langchain.prompts"] = langchain_prompts
    sys.modules["langchain.schema"] = langchain_schema
    sys.modules["langchain.output_parsers"] = langchain_output_parsers
    sys.modules["langchain.output_parsers.json"] = langchain_output_parsers_json

    # llm_factory
    llm_factory = types.ModuleType("llm_factory")
    llm_factory.create_llm = lambda **_kwargs: _DummyModel()
    sys.modules["llm_factory"] = llm_factory

    # fastapi
    fastapi = types.ModuleType("fastapi")

    class HTTPException(Exception):
        def __init__(self, status_code=500, detail=""):
            super().__init__(detail)
            self.status_code = status_code
            self.detail = detail

    fastapi.HTTPException = HTTPException
    sys.modules["fastapi"] = fastapi

    # dotenv
    dotenv = types.ModuleType("dotenv")

    def load_dotenv(*_args, **_kwargs):
        return None

    dotenv.load_dotenv = load_dotenv
    sys.modules["dotenv"] = dotenv

    # mcp_processor
    mcp_processor_mod = types.ModuleType("mcp_processor")

    class _DummyMCP:
        async def execute_mcp_tools(self, *_args, **_kwargs):
            return {"messages": []}

        async def cleanup(self):
            return None

    mcp_processor_mod.mcp_processor = _DummyMCP()
    sys.modules["mcp_processor"] = mcp_processor_mod

    # code_executor
    code_executor_mod = types.ModuleType("code_executor")

    class _ExecResult:
        def __init__(self, rc=0, out="", err=""):
            self.returncode = rc
            self.stdout = out
            self.stderr = err

    def execute_python_code(*_args, **_kwargs):
        return _ExecResult(0, "ok", "")

    code_executor_mod.execute_python_code = execute_python_code
    sys.modules["code_executor"] = code_executor_mod

    # smtp_handler
    smtp_handler_mod = types.ModuleType("smtp_handler")

    def generate_email_template(*_args, **_kwargs):
        return "<html></html>"

    def send_email(*_args, **_kwargs):
        return None

    smtp_handler_mod.generate_email_template = generate_email_template
    smtp_handler_mod.send_email = send_email
    sys.modules["smtp_handler"] = smtp_handler_mod

    # agent_processor
    agent_processor_mod = types.ModuleType("agent_processor")

    async def handle_workitem_with_agent(*_args, **_kwargs):
        return None

    agent_processor_mod.handle_workitem_with_agent = handle_workitem_with_agent
    sys.modules["agent_processor"] = agent_processor_mod


def _load_workitem_processor_module():
    _install_stub_modules()
    file_path = pathlib.Path(__file__).resolve().parents[1] / "workitem_processor.py"
    spec = importlib.util.spec_from_file_location("wiproc", str(file_path))
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)  # type: ignore[attr-defined]
    return module


@pytest.fixture(scope="module")
def wiproc():
    return _load_workitem_processor_module()


# ------------------------------------------------------------
# Dummy process definition structures for local tests
# ------------------------------------------------------------
class _Seq:
    def __init__(self, id, source, target, name=None, properties=None):
        self.id = id
        self.source = source
        self.target = target
        self.name = name
        self.properties = properties


class _Gateway:
    def __init__(self, id, type, name=None, condition=None, properties=None):
        self.id = id
        self.type = type
        self.name = name
        self.condition = condition
        self.properties = properties


class _Activity:
    def __init__(self, id, name=None, description=None, role=None, type="userTask"):
        self.id = id
        self.name = name
        self.description = description
        self.role = role
        self.type = type


class _SubProcess:
    def __init__(self, id, name=None, description=None):
        self.id = id
        self.name = name
        self.description = description


class _ProcDef:
    def __init__(self, activities=None, gateways=None, sequences=None, sub_processes=None, events=None):
        self.activities = activities or []
        self.gateways = gateways or []
        self.sequences = sequences or []
        self.subProcesses = sub_processes or []
        self.events = events or []

    def find_activity_by_id(self, aid):
        return next((a for a in self.activities if getattr(a, "id", None) == aid), None)

    def find_gateway_by_id(self, gid):
        return next((g for g in self.gateways if getattr(g, "id", None) == gid), None)

    def find_event_by_id(self, eid):
        return next((e for e in (self.events or []) if getattr(e, "id", None) == eid), None)

    def find_sub_process_by_id(self, sid):
        return next((s for s in self.subProcesses if getattr(s, "id", None) == sid), None)


# ------------------------------------------------------------
# Tests
# ------------------------------------------------------------
 


def test_resolve_next_activity_payloads_exclusive_branch(wiproc):
    # A1 -> G1 -> (s2) B1, (s3) B2
    gw = _Gateway("G1", type="exclusiveGateway", name="XOR")
    seqs = [
        _Seq("s1", source="A1", target="G1"),
        _Seq("s2", source="G1", target="B1"),
        _Seq("s3", source="G1", target="B2"),
    ]
    acts = [_Activity("A1"), _Activity("B1", name="Task B1"), _Activity("B2", name="Task B2")]
    proc_def = _ProcDef(activities=acts, gateways=[gw], sequences=seqs)

    sequence_condition_data = {"s2": {"conditionEval": True}, "s3": {"conditionEval": False}}
    workitem = {"assignees": []}

    payloads = wiproc.resolve_next_activity_payloads(
        proc_def,
        activity_id="A1",
        workitem=workitem,
        sequence_condition_data=sequence_condition_data,
    )

    ids = [p.get("nextActivityId") for p in payloads]
    assert ids == ["B1"]


 

