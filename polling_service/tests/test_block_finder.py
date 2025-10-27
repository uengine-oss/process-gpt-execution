from typing import Optional

import json
from pathlib import Path
import pytest
from process_definition import load_process_definition
from block_finder import BlockFinder, FeedbackOptions


class _Node:
    def __init__(self, id: str, type: str):
        self.id = id
        self.type = type


class _Seq:
    def __init__(self, source: str, target: str, properties: Optional[dict] = None, id: Optional[str] = None):
        self.id = id or f"{source}->{target}"
        self.source = source
        self.target = target
        self.properties = dict(properties or {})


class _PD:
    def __init__(self, activities=None, gateways=None, subProcesses=None, sequences=None):
        self.activities = activities or []
        self.gateways = gateways or []
        self.subProcesses = subProcesses or []
        self.sequences = sequences or []

    def find_activity_by_id(self, node_id: str):
        for a in self.activities:
            if a.id == node_id:
                return a
        return None

    def find_gateway_by_id(self, node_id: str):
        for g in self.gateways:
            if g.id == node_id:
                return g
        return None


def _has_cycle(block_finder: BlockFinder) -> bool:
    from collections import defaultdict, deque

    adj = defaultdict(list)
    indeg = {}
    nodes = set()
    for n in block_finder.graph.nodes.values():
        nodes.add(n)
    for f in block_finder.graph.sequence_flows:
        if f.isFeedback():
            continue
        u = f.getSourceActivity()
        v = f.getTargetActivity()
        if u is None or v is None:
            continue
        adj[u].append(v)
        indeg[v] = indeg.get(v, 0) + 1
        indeg.setdefault(u, indeg.get(u, 0))
    q = deque([n for n in nodes if indeg.get(n, 0) == 0])
    seen = 0
    while q:
        x = q.popleft()
        seen += 1
        for y in adj.get(x, []):
            indeg[y] -= 1
            if indeg[y] == 0:
                q.append(y)
    return seen < len(nodes)


# ------------------------------
# JSON-driven BlockFinder tests
# ------------------------------
@pytest.mark.parametrize("filename", [
    "exclusiveExclusive.json",
    "exclusiveInclusive.json",
    "exclusiveParallel.json",
    "inclusiveExclusive.json",
    "inclusiveInclusive.json",
    "inclusiveParallel.json",
    "parallelExclusive.json",
    "parallelInclusive.json",
    "parallelParallel.json",
])
def test_block_finder_on_process_json(filename: str):
    base_dir = Path(__file__).resolve().parent
    json_path = base_dir / filename
    assert json_path.exists(), f"Process JSON not found: {json_path}"

    with json_path.open("r", encoding="utf-8") as f:
        proc_def_dict = json.load(f)
    pd = load_process_definition(proc_def_dict)

    bf = BlockFinder(pd)
    # Target join gateway
    target_join_id = "Gateway_1bwgkit"

    br = bf.find_block(target_join_id)
    assert br is not None, f"Block not found for {target_join_id} in {filename}"
    assert br.end_container_id == target_join_id

    # Basic structural expectations for this process family
    # - split gateway is Gateway_1x586s7
    # - three branches converge into Gateway_1bwgkit
    assert br.branch_count >= 1

    # Members should include the three branch activities before the join
    members = [n.id for n in bf.get_block_members(target_join_id)]
    for expected_id in ["Activity_0wmbn0q", "Activity_1l2ci7f", "Activity_0rwrgae"]:
        assert expected_id in members, f"{expected_id} not found in block members for {filename}"


@pytest.fixture
def make_graph():
    def _build(nodes: list[tuple[str, str]], edges: list[tuple[str, str]]):
        ns = {i: _Node(i, t) for i, t in nodes}
        seqs = [_Seq(a, b) for a, b in edges]
        pd = _PD(activities=[ns[i] for i, _ in nodes], sequences=seqs)
        return BlockFinder(pd)
    return _build


def test_linear_no_loop(make_graph):
    r"""
    (S) --> [T1] --> (E)
              ↑ join=E
              start_container_id=T1
              branch_count=1
              block_members=[]
              possible_block_members=[]
    """
    # S -> T1 -> E 직선 흐름 (루프 없음)
    bf = make_graph(
        nodes=[("S", "startEvent"), ("T1", "task"), ("E", "endEvent")],
        edges=[("S", "T1"), ("T1", "E")],
    )

    inferred = [f for f in bf.graph.sequence_flows if f.properties.get("__inferredFeedback") is True]
    assert len(inferred) == 0

    br = bf.find_block("E")
    assert br is not None
    assert br.end_container_id == "E"
    assert br.branch_count == 1
    assert br.start_container_id == "T1"
    assert sorted(br.block_members) == []
    assert sorted(br.possible_block_members) == []

    assert bf.graph.distance_from_start.get(bf.graph.resolve_node("S")) == 0
    assert bf.graph.distance_to_end.get(bf.graph.resolve_node("E")) == 0


def test_parallel_split_join(make_graph):
    r"""
    (S) --> <Gs> --+--> [A] --+
                   |          |
                   +--> [B] --+--> <Gj> --> (E)

    split=<Gs>
    join=<Gj>
    branch_count=2
    block_members=[A,B]
    possible_block_members=[A,B]
    """
    bf = make_graph(
        nodes=[
            ("S", "startEvent"),
            ("Gs", "parallelGateway"),
            ("A", "task"),
            ("B", "task"),
            ("Gj", "exclusiveGateway"),
            ("E", "endEvent"),
        ],
        edges=[("S", "Gs"), ("Gs", "A"), ("Gs", "B"), ("A", "Gj"), ("B", "Gj"), ("Gj", "E")],
    )

    inferred = [f for f in bf.graph.sequence_flows if f.properties.get("__inferredFeedback") is True]
    assert len(inferred) == 0

    br = bf.find_block("Gj")
    assert br is not None
    assert br.end_container_id == "Gj"
    assert br.branch_count == 2
    assert br.start_container_id == "Gs"
    assert sorted(br.block_members) == ["A", "B"]
    assert sorted(br.possible_block_members) == ["A", "B"]

    members = [n.id for n in bf.get_block_members("Gj")]
    assert "A" in members and "B" in members


def test_loop_inferred_feedback_edge(make_graph):
    r"""
    (S) --> [X] --> [Y] --> [Z] --> (E)
                  ^        |
                  |        +--> [Y]  --> [FB] (Z->Y 추론)

    - 루프 (Y,Z)
    - feedback 선택: 시작에서 가장 멀고 종료에 가장 가까운 간선 Z->Y
    """
    bf = make_graph(
        nodes=[("S", "startEvent"), ("X", "task"), ("Y", "task"), ("Z", "task"), ("E", "endEvent")],
        edges=[("S", "X"), ("X", "Y"), ("Y", "Z"), ("Z", "Y"), ("Z", "E")],
    )

    inferred = [f for f in bf.graph.sequence_flows if f.properties.get("__inferredFeedback") is True]
    assert len(inferred) == 1
    inferred_flow = inferred[0]
    assert inferred_flow.getSourceActivity().id == "Z"
    assert inferred_flow.getTargetActivity().id == "Y"

    br = bf.find_block("E")
    assert br is not None
    assert br.end_container_id == "E"
    assert br.branch_count >= 1


def test_self_loop_inferred_feedback(make_graph):
    r"""
    (S) --> [L] --> (E)
              ^
              |
              +--------- [FB] (L->L 자기루프 추론)

    - 단일 노드 자기 루프를 피드백으로 지정
    """
    bf = make_graph(
        nodes=[("S", "startEvent"), ("L", "task"), ("E", "endEvent")],
        edges=[("S", "L"), ("L", "L"), ("L", "E")],
    )

    inferred = [f for f in bf.graph.sequence_flows if f.properties.get("__inferredFeedback") is True]
    assert len(inferred) == 1
    inferred_flow = inferred[0]
    assert inferred_flow.getSourceActivity().id == "L"
    assert inferred_flow.getTargetActivity().id == "L"

    br = bf.find_block("E")
    assert br is not None
    assert br.end_container_id == "E"


def test_distance_maps_present(make_graph):
    r"""
    (S) --> [A] --> [B] --> (E)

    dist_from_start: S=0, A=1, B=2, E=3
    dist_to_end:     E=0, B=1, A=2, S=3
    """
    bf = make_graph(
        nodes=[("S", "startEvent"), ("A", "task"), ("B", "task"), ("E", "endEvent")],
        edges=[("S", "A"), ("A", "B"), ("B", "E")],
    )

    assert hasattr(bf.graph, "distance_from_start")
    assert hasattr(bf.graph, "distance_to_end")
    assert bf.graph.distance_from_start.get(bf.graph.resolve_node("S")) == 0
    assert bf.graph.distance_to_end.get(bf.graph.resolve_node("E")) == 0


def test_iterative_break_multiloop_scc(make_graph):
    r"""
    (S) --> [A] --> [B] --> [C] --+
             ^                   |
             +-------------------+
             \------------------------------> (E)

    - 3-사이클 (A,B,C) + C -> E
    - 전략: iterative_break => 사이클이 제거될 때까지 반복적으로 1개씩 [FB] 지정
    - 결과: 사이클 제거, 그래프 무사이클
    """
    opts = FeedbackOptions(strategy="iterative_break")
    bf = make_graph(
        nodes=[("S", "startEvent"), ("A", "task"), ("B", "task"), ("C", "task"), ("E", "endEvent")],
        edges=[("S", "A"), ("A", "B"), ("B", "C"), ("C", "A"), ("C", "E")],
    )
    bf.graph.options = opts

    inferred = [f for f in bf.graph.sequence_flows if f.properties.get("__inferredFeedback") is True]
    assert len(inferred) >= 1
    assert _has_cycle(bf) is False


def test_all_back_edges_strategy_marks_all_cycle_edges(make_graph):
    r"""
    (S) --> [A] --> [B] --> [C] --> [D] --+
             ^                             |
             +-----------------------------+

    - 전략: all_back_edges => 루프에 참여하는 모든 간선을 [FB]
    - 4-사이클 모든 간선이 루프 참여이므로 4개 모두 [FB]
    """
    opts = FeedbackOptions(strategy="all_back_edges")
    bf = make_graph(
        nodes=[("S", "startEvent"), ("A", "task"), ("B", "task"), ("C", "task"), ("D", "task")],
        edges=[("S", "A"), ("A", "B"), ("B", "C"), ("C", "D"), ("D", "A")],
    )
    bf.graph.options = opts
    bf.graph.recompute_feedback_flows()

    inferred = [f for f in bf.graph.sequence_flows if f.properties.get("__inferredFeedback") is True]
    assert len(inferred) == 4


def test_single_best_strategy_marks_one(make_graph):
    r"""
    (S) --> [A] --> [B] --> [C] --+
             ^                   |
             +-------------------+

    - 전략: single_best => 하나만 [FB]
    """
    opts = FeedbackOptions(strategy="single_best")
    bf = make_graph(
        nodes=[("S", "startEvent"), ("A", "task"), ("B", "task"), ("C", "task")],
        edges=[("S", "A"), ("A", "B"), ("B", "C"), ("C", "A")],
    )
    bf.graph.options = opts

    inferred = [f for f in bf.graph.sequence_flows if f.properties.get("__inferredFeedback") is True]
    assert len(inferred) == 1


def test_event_exclusion_prevents_feedback_on_timer_nodes(make_graph):
    r"""
    (S) --> [A] --> (T)timer --> [B] --+
             ^                         |
             +-------------------------+

    - timerEvent가 관여한 간선은 후보에서 제외되어 [FB] 추론이 되지 않음
    """
    bf = make_graph(
        nodes=[("S", "startEvent"), ("A", "task"), ("T", "timerEvent"), ("B", "task")],
        edges=[("S", "A"), ("A", "T"), ("T", "B"), ("B", "A")],
    )

    inferred = [f for f in bf.graph.sequence_flows if f.properties.get("__inferredFeedback") is True]
    assert len(inferred) == 0
    assert _has_cycle(bf) is True


def test_stable_tiebreak_determinism(make_graph):
    r"""
    (S) --> [A] --> [B] --> (E)
     |                 ^
     |                 |
     +--> [C] --> [D] -+
     ^                  |
     +------------------+

    - 4-사이클 (A,B,C,D)에서 A->B와 C->D 후보가 동률(ds, de 동일)
    - stable_tiebreak=True 이면 src id가 빠른 A->B가 선택됨
    """
    opts = FeedbackOptions(strategy="single_best", stable_tiebreak=True)
    bf = make_graph(
        nodes=[("S", "startEvent"), ("A", "task"), ("B", "task"), ("C", "task"), ("D", "task"), ("E", "endEvent")],
        edges=[("S", "A"), ("S", "C"), ("A", "B"), ("C", "D"), ("B", "C"), ("D", "A"), ("B", "E"), ("D", "E")],
    )
    bf.graph.options = opts

    inferred = [f for f in bf.graph.sequence_flows if f.properties.get("__inferredFeedback") is True]
    assert len(inferred) == 1
    chosen = inferred[0]
    assert (chosen.getSourceActivity().id, chosen.getTargetActivity().id) in [("A", "B"), ("B", "C")]


def test_recompute_feedback_with_different_strategy(make_graph):
    r"""
    동일 그래프에 대해 전략 변경 후 재계산이 반영되는지 확인
    - 3-사이클에서 single_best -> all_back_edges 로 변경 시 [FB] 수가 증가해야 함
    """
    bf = make_graph(
        nodes=[("A", "task"), ("B", "task"), ("C", "task")],
        edges=[("A", "B"), ("B", "C"), ("C", "A")],
    )
    bf.graph.options = FeedbackOptions(strategy="single_best")
    inferred1 = [f for f in bf.graph.sequence_flows if f.properties.get("__inferredFeedback") is True]
    assert len(inferred1) == 1

    bf.graph.options.strategy = "all_back_edges"
    bf.graph.recompute_feedback_flows()
    inferred2 = [f for f in bf.graph.sequence_flows if f.properties.get("__inferredFeedback") is True]
    assert len(inferred2) == 3


def test_sales_proposal_process_feedback():
    r"""
    실제 영업제안서 프로세스 형태

    (start_event) -> [customer_request_activity] -> [proposal_draft_activity] -> [sales_review_activity] -> <Gateway_0xwhalm>
                                                                                                         |           \
                                                                                                         |            -> [Activity_1ic0mq5] -> (Event_0fyizd2)
                                                                                                          -> [proposal_draft_activity]  (루프)

    - 루프: proposal_draft_activity -> sales_review_activity -> Gateway_0xwhalm -> proposal_draft_activity
    - 기대 feedback: Gateway_0xwhalm -> proposal_draft_activity
    """
    start_event = _Node("start_event", "startEvent")
    end_event = _Node("Event_0fyizd2", "endEvent")
    gateway = _Node("Gateway_0xwhalm", "exclusiveGateway")
    customer_request_activity = _Node("customer_request_activity", "userTask")
    proposal_draft_activity = _Node("proposal_draft_activity", "userTask")
    sales_review_activity = _Node("sales_review_activity", "userTask")
    activity_1ic0mq5 = _Node("Activity_1ic0mq5", "userTask")

    seqs = [
        _Seq("start_event", "customer_request_activity"),
        _Seq("customer_request_activity", "proposal_draft_activity"),
        _Seq("proposal_draft_activity", "sales_review_activity"),
        _Seq("sales_review_activity", "Gateway_0xwhalm"),
        _Seq("Gateway_0xwhalm", "Activity_1ic0mq5"),
        _Seq("Gateway_0xwhalm", "proposal_draft_activity"),  # expected feedback
        _Seq("Activity_1ic0mq5", "Event_0fyizd2"),
    ]

    pd = _PD(
        activities=[
            start_event,
            end_event,
            customer_request_activity,
            proposal_draft_activity,
            sales_review_activity,
            activity_1ic0mq5,
        ],
        gateways=[gateway],
        sequences=seqs,
    )

    bf = BlockFinder(pd)
    inferred = [f for f in bf.graph.sequence_flows if f.properties.get("__inferredFeedback") is True]
    assert len(inferred) == 1
    assert (inferred[0].getSourceActivity().id, inferred[0].getTargetActivity().id) == ("Gateway_0xwhalm", "proposal_draft_activity")

    br = bf.find_block("Event_0fyizd2")
    assert br is not None
    assert br.branch_count >= 1


