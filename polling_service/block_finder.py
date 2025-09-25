﻿from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Union, TYPE_CHECKING

if TYPE_CHECKING:
    from process_definition import ProcessDefinition


def _normalize_properties(props: Any) -> Dict[str, Any]:
    if not props:
        return {}
    if isinstance(props, dict):
        return dict(props)
    if isinstance(props, str):
        text = props.strip()
        if not text:
            return {}
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {}
    return {}


def _is_truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "y"}
    if isinstance(value, (int, float)):
        return bool(value)
    return False


def _call_optional(obj: Any, method_name: str, *args, **kwargs):
    method = getattr(obj, method_name, None)
    if callable(method):
        return method(*args, **kwargs)
    return None


class ProcessGraph:
    def __init__(self, process_definition: "ProcessDefinition") -> None:
        self.process_definition = process_definition
        self.nodes: Dict[str, ActivityNode] = {}
        self.sequence_flows: List[SequenceFlow] = []
        self._build_nodes()
        self._build_sequences()
        # Infer feedback edges topologically (back-edges) and mark them
        self._infer_feedback_flows()

    def resolve_node(self, node_or_id: Union[str, ActivityNode, None]) -> Optional[ActivityNode]:
        if isinstance(node_or_id, ActivityNode):
            return node_or_id
        if isinstance(node_or_id, str):
            return self.nodes.get(node_or_id)
        return None

    def count_incoming(self, node: ActivityNode, *, ignore_feedback: bool = True) -> int:
        flows = node.getIncomingSequenceFlows()
        if ignore_feedback:
            flows = [f for f in flows if not f.isFeedback()]
        return len(flows)
    def is_gateway(self, node: ActivityNode) -> bool:
        raw = getattr(node, 'raw', None)
        node_type = getattr(raw, 'type', None) if raw is not None else None
        if isinstance(node_type, str):
            return 'gateway' in node_type.lower()
        return False

    def iter_outgoing(self, node: ActivityNode, *, ignore_feedback: bool = True):
        for flow in node.getOutgoingSequenceFlows():
            if ignore_feedback and flow.isFeedback():
                continue
            yield flow.getTargetActivity()

    def find_nearest_join(self, node: ActivityNode, *, max_depth: int = 1000) -> Optional[ActivityNode]:
        visited: Set[ActivityNode] = {node}
        queue = deque([(node, 0)])
        while queue:
            current, depth = queue.popleft()
            if depth > 0 and self.is_gateway(current) and self.count_incoming(current, ignore_feedback=True) >= 2:
                return current
            if depth >= max_depth:
                continue
            for nxt in self.iter_outgoing(current, ignore_feedback=True):
                if nxt not in visited:
                    visited.add(nxt)
                    queue.append((nxt, depth + 1))
        return None


    def _build_nodes(self) -> None:
        for collection_name in ("activities", "gateways", "subProcesses"):
            collection = getattr(self.process_definition, collection_name, None) or []
            for item in collection:
                node_id = getattr(item, "id", None)
                if node_id:
                    self._ensure_node(node_id, item)

    def _build_sequences(self) -> None:
        for sequence in self.process_definition.sequences or []:
            source = self._ensure_node(sequence.source, self._resolve_raw(sequence.source))
            target = self._ensure_node(sequence.target, self._resolve_raw(sequence.target))
            flow = SequenceFlow(
                flow_id=getattr(sequence, "id", f"{sequence.source}->{sequence.target}"),
                source=source,
                target=target,
                properties=_normalize_properties(getattr(sequence, "properties", None)),
            )
            source.add_outgoing(flow)
            target.add_incoming(flow)
            self.sequence_flows.append(flow)

    def _ensure_node(self, node_id: str, raw: Optional[Any]) -> "ActivityNode":
        node = self.nodes.get(node_id)
        if not node:
            node = ActivityNode(node_id=node_id, raw=raw, graph=self)
            self.nodes[node_id] = node
        else:
            if node.raw is None and raw is not None:
                node.raw = raw
        return node

    def _resolve_raw(self, node_id: str) -> Optional[Any]:
        return (
            _call_optional(self.process_definition, "find_activity_by_id", node_id)
            or _call_optional(self.process_definition, "find_sub_process_by_id", node_id)
            or _call_optional(self.process_definition, "find_gateway_by_id", node_id)
            or _call_optional(self.process_definition, "find_event_by_id", node_id)
        )

    def _infer_feedback_flows(self) -> None:
        # 1) pick start nodes: prefer startEvent; fallback to nodes with no incoming
        start_nodes: List[ActivityNode] = []
        for node in self.nodes.values():
            raw = getattr(node, 'raw', None)
            t = getattr(raw, 'type', None)
            if isinstance(t, str) and 'start' in t.lower():
                start_nodes.append(node)
        if not start_nodes:
            for node in self.nodes.values():
                if not [f for f in node.getIncomingSequenceFlows() if not f.isFeedback()]:
                    start_nodes.append(node)
        if not start_nodes:
            # if still empty, choose arbitrary nodes to avoid NPE; levels remain 0
            start_nodes = list(self.nodes.values())

        # 2) level labeling via BFS ignoring explicit feedback
        from collections import deque as _deque
        INF = 10**9
        level: Dict[ActivityNode, int] = {n: INF for n in self.nodes.values()}
        dq = _deque()
        for s in start_nodes:
            level[s] = 0
            dq.append(s)
        while dq:
            cur = dq.popleft()
            cur_level = level[cur]
            for flow in cur.getOutgoingSequenceFlows():
                if flow.isFeedback():
                    continue
                nxt = flow.getTargetActivity()
                if nxt is None:
                    continue
                if level.get(nxt, INF) > cur_level + 1:
                    level[nxt] = cur_level + 1
                    dq.append(nxt)

        # 3) candidate back-edges: source.level >= target.level; confirm cycle t->...->s without this flow
        # build adjacency (excluding explicit feedback) for cycle test
        adj: Dict[ActivityNode, List[ActivityNode]] = {n: [] for n in self.nodes.values()}
        for flow in self.sequence_flows:
            if flow.isFeedback():
                continue
            u = flow.getSourceActivity()
            v = flow.getTargetActivity()
            if u and v:
                adj[u].append(v)

        def _reachable(src: ActivityNode, dst: ActivityNode, skip_flow: SequenceFlow) -> bool:
            seen: Set[ActivityNode] = set()
            q = _deque([src])
            while q:
                x = q.popleft()
                if x in seen:
                    continue
                seen.add(x)
                if x is dst:
                    return True
                for flow in x.getOutgoingSequenceFlows():
                    if flow is skip_flow or flow.isFeedback():
                        continue
                    y = flow.getTargetActivity()
                    if y and y not in seen:
                        q.append(y)
            return False

        for flow in self.sequence_flows:
            if flow.isFeedback():
                continue
            s = flow.getSourceActivity()
            t = flow.getTargetActivity()
            if s is None or t is None:
                continue
            ls = level.get(s, INF)
            lt = level.get(t, INF)
            if ls >= lt and lt != INF:
                if _reachable(t, s, flow):
                    flow.properties["__inferredFeedback"] = True


class ActivityNode:
    __slots__ = ("id", "raw", "_graph", "_incoming", "_outgoing")

    def __init__(self, node_id: str, raw: Optional[Any], graph: ProcessGraph) -> None:
        self.id = node_id
        self.raw = raw
        self._graph = graph
        self._incoming: List[SequenceFlow] = []
        self._outgoing: List[SequenceFlow] = []

    def __repr__(self) -> str:
        return f"ActivityNode(id={self.id!r})"

    def __hash__(self) -> int:
        return hash(self.id)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, ActivityNode) and other.id == self.id

    def add_incoming(self, flow: "SequenceFlow") -> None:
        self._incoming.append(flow)

    def add_outgoing(self, flow: "SequenceFlow") -> None:
        self._outgoing.append(flow)

    def getIncomingSequenceFlows(self) -> List["SequenceFlow"]:
        return list(self._incoming)

    def getOutgoingSequenceFlows(self) -> List["SequenceFlow"]:
        return list(self._outgoing)

    def getTracingTag(self) -> str:
        return self.id

    def getPossibleNextActivities(self, instance: Optional[Any], token: str = "") -> List["ActivityNode"]:  # noqa: ARG002
        return [flow.getTargetActivity() for flow in self._outgoing if not flow.isFeedback()]


class SequenceFlow:
    __slots__ = ("id", "source", "target", "properties")

    def __init__(self, flow_id: str, source: ActivityNode, target: ActivityNode, properties: Optional[Dict[str, Any]] = None) -> None:
        self.id = flow_id
        self.source = source
        self.target = target
        self.properties = properties or {}

    def isFeedback(self) -> bool:
        # Inferred flag takes precedence if present
        if self.properties.get("__inferredFeedback") is True:
            return True
        value = self.properties.get("isFeedback")
        if value is None:
            value = self.properties.get("feedback")
        if value is None and isinstance(self.properties.get("type"), str):
            t = self.properties.get("type")
            if isinstance(t, str) and t.strip().lower() in {"feedback", "back", "rollback"}:
                return True
            value = t
        if isinstance(value, str) and value.strip().lower() in {"feedback", "back", "rollback"}:
            return True
        return _is_truthy(value)

    def getSourceActivity(self) -> ActivityNode:
        return self.source

    def getTargetActivity(self) -> ActivityNode:
        return self.target


class _BlockFinderCore:
    def __init__(self, join_activity: ActivityNode) -> None:
        self.joinActivity = join_activity
        self.blockMembers: List[ActivityNode] = []
        self.depth = 0
        self.activitiesByDistanceMap: Dict[int, List[ActivityNode]] = {}
        self.distancesByActivity: Dict[str, int] = {}
        self.visitCount: Dict[str, int] = {}
        self.visitActivityStack: List[ActivityNode] = []
        self.visitForDepthAndVisitCountSetting(join_activity)
        self.visitToLineUp(join_activity)
        self.findBlockMembers()

    def getBlockMembers(self) -> List[ActivityNode]:
        return self.blockMembers

    def visitForDepthAndVisitCountSetting(self, activity: ActivityNode) -> None:
        self.depth += 1
        self.visitActivityStack.append(activity)

        for sequenceFlow in activity.getIncomingSequenceFlows():
            sourceActivity = sequenceFlow.getSourceActivity()

            if sequenceFlow.isFeedback():
                continue

            if sourceActivity is None:
                continue

            if sourceActivity in self.visitActivityStack:
                continue

            tag = sourceActivity.getTracingTag()
            visitCountForThisActivity = self.visitCount.get(tag, 0) + 1
            self.visitCount[tag] = visitCountForThisActivity

            self.visitForDepthAndVisitCountSetting(sourceActivity)

            self.distancesByActivity[tag] = self.depth

        self.depth -= 1
        self.visitActivityStack.pop()

    def visitToLineUp(self, activity: ActivityNode) -> None:
        self._visitToLineUpInternal(activity, set())

    def _visitToLineUpInternal(self, activity: ActivityNode, visitedActivities: Set[ActivityNode]) -> None:
        if activity in visitedActivities:
            return

        visitedActivities.add(activity)

        for sequenceFlow in activity.getIncomingSequenceFlows():
            if sequenceFlow.isFeedback():
                continue

            sourceActivity = sequenceFlow.getSourceActivity()
            distanceOfThis = self.distancesByActivity.get(sourceActivity.getTracingTag())

            if distanceOfThis is None:
                continue

            activitiesInDistance = self.activitiesByDistanceMap.setdefault(distanceOfThis, [])
            if sourceActivity not in activitiesInDistance:
                activitiesInDistance.append(sourceActivity)

            self._visitToLineUpInternal(sourceActivity, visitedActivities)

    def findBlockMembers(self) -> None:
        self.blockMembers = []
        branch = len([flow for flow in self.joinActivity.getIncomingSequenceFlows() if not flow.isFeedback()])
        if branch == 0:
            return

        depth = 1
        while depth in self.activitiesByDistanceMap and self.activitiesByDistanceMap[depth]:
            activitiesInDepth = self.activitiesByDistanceMap[depth]
            if len(activitiesInDepth) == 1:
                activity = activitiesInDepth[0]
                self.blockMembers.append(activity)
                visitedCountForThis = self.visitCount.get(activity.getTracingTag(), 0)
                if branch == visitedCountForThis:
                    break
            else:
                for activity in activitiesInDepth:
                    inc = len([flow for flow in activity.getIncomingSequenceFlows() if not flow.isFeedback()])
                    branch += max(inc - 1, 0)
                    self.blockMembers.append(activity)
            depth += 1

    @staticmethod
    def getPossibleBlockMembers(blockMembers: List[ActivityNode], instance: Optional[Any]) -> List[ActivityNode]:
        if not blockMembers:
            return []
        theLastBlockMember = blockMembers[-1]
        possibleBlockMembers: List[ActivityNode] = [theLastBlockMember]
        _BlockFinderCore.visitForPossibleNodes(theLastBlockMember, blockMembers, instance, possibleBlockMembers)
        return possibleBlockMembers

    @staticmethod
    def visitForPossibleNodes(activity: ActivityNode, blockMembers: List[ActivityNode], instance: Optional[Any], possibleNodes: List[ActivityNode]) -> None:
        for next_activity in activity.getPossibleNextActivities(instance, ""):
            if next_activity in blockMembers and next_activity not in possibleNodes:
                possibleNodes.append(next_activity)
                _BlockFinderCore.visitForPossibleNodes(next_activity, blockMembers, instance, possibleNodes)


@dataclass
class BlockResult:
    start_container_id: Optional[str]
    end_container_id: str
    branch_count: int
    block_members: List[str]
    possible_block_members: List[str]

    @property
    def node_ids(self) -> List[str]:
        seen: Set[str] = set()
        ordered: List[str] = []
        for node_id in [self.start_container_id] if self.start_container_id else []:
            if node_id not in seen:
                seen.add(node_id)
                ordered.append(node_id)
        for node_id in self.block_members:
            if node_id not in seen:
                seen.add(node_id)
                ordered.append(node_id)
        for node_id in self.possible_block_members:
            if node_id not in seen:
                seen.add(node_id)
                ordered.append(node_id)
        # Include the end (join) node itself as part of the block
        for node_id in [self.end_container_id] if self.end_container_id else []:
            if node_id not in seen:
                seen.add(node_id)
                ordered.append(node_id)
        return ordered

    @property
    def branch_paths(self) -> List[List[str]]:
        return []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "start_container_id": self.start_container_id,
            "end_container_id": self.end_container_id,
            "branch_count": self.branch_count,
            "block_members": self.block_members,
            "possible_block_members": self.possible_block_members,
            "node_ids": self.node_ids,
        }


class BlockFinder:
    def __init__(self, process_definition: "ProcessDefinition") -> None:
        self.graph = ProcessGraph(process_definition)

    def get_block_members(self, join_activity: Union[str, ActivityNode]) -> List[ActivityNode]:
        join_node = self.graph.resolve_node(join_activity)
        if join_node is None:
            raise ValueError(f"Join activity not found: {join_activity}")
        core = _BlockFinderCore(join_node)
        return core.getBlockMembers()

    def find_block(self, join_activity: Union[str, ActivityNode], *, process_instance: Optional[Any] = None) -> Optional[BlockResult]:
        join_node = self.graph.resolve_node(join_activity)
        if join_node is None:
            return None

        # 1) branch_count 계산: (a) 본인 incoming 비피드백 시퀀스 수,
        #    (b) 바로 전단계 게이트웨이가 있으면 그 게이트웨이 incoming 비피드백 시퀀스 수
        def _non_feedback_in(flows):
            return [f for f in flows if not f.isFeedback()]

        def _non_feedback_out(flows):
            return [f for f in flows if not f.isFeedback()]

        incoming_to_join = _non_feedback_in(join_node.getIncomingSequenceFlows())
        branch_count = len(incoming_to_join)

        # 바로 전단계 게이트웨이 확인
        prior_gateways: List[ActivityNode] = []
        for f in incoming_to_join:
            src = f.getSourceActivity()
            if src and self.graph.is_gateway(src):
                prior_gateways.append(src)
        if branch_count < 2 and prior_gateways:
            gw = prior_gateways[0]
            branch_count = len(_non_feedback_in(gw.getIncomingSequenceFlows()))

        # 2) 역방향 탐색으로 split 후보 찾기:
        #    outgoing(비피드백) 중 join까지 도달 가능한 가지 수가 branch_count와 같은 가장 가까운 노드를 split으로 선택
        from collections import deque

        def _can_reach(start: ActivityNode, goal: ActivityNode) -> bool:
            if start is goal:
                return True
            seen: Set[ActivityNode] = set()
            q = deque([start])
            while q:
                x = q.popleft()
                if x in seen:
                    continue
                seen.add(x)
                if x is goal:
                    return True
                for ff in _non_feedback_out(x.getOutgoingSequenceFlows()):
                    y = ff.getTargetActivity()
                    if y and y not in seen:
                        q.append(y)
            return False

        visited: Set[ActivityNode] = set()
        queue = deque([join_node])
        start_candidate: Optional[ActivityNode] = None

        while queue:
            node = queue.popleft()
            if node in visited:
                continue
            visited.add(node)

            # 해당 노드의 비피드백 out 중에서 join까지 도달 가능한 가지 수 계산
            outs = _non_feedback_out(node.getOutgoingSequenceFlows())
            out_to_join = 0
            for of in outs:
                tgt = of.getTargetActivity()
                if tgt and _can_reach(tgt, join_node):
                    out_to_join += 1
            if out_to_join == branch_count and outs:
                start_candidate = node
                break

            for f in _non_feedback_in(node.getIncomingSequenceFlows()):
                src = f.getSourceActivity()
                if src and src not in visited:
                    queue.append(src)

        # 3) 사이 노드 수집: split -> join까지의 모든 노드(비피드백 경로, join에 도달 가능한 경로만) 집합
        between_nodes: List[str] = []
        possible_children: List[str] = []

        if start_candidate is not None:
            # split이 게이트웨이면 즉시 하위의 액티비티/서브프로세스/이벤트 중 join까지 도달 가능한 노드만 수집
            if self.graph.is_gateway(start_candidate):
                for f in _non_feedback_out(start_candidate.getOutgoingSequenceFlows()):
                    tgt = f.getTargetActivity()
                    if tgt and not self.graph.is_gateway(tgt) and _can_reach(tgt, join_node):
                        possible_children.append(tgt.getTracingTag())

            # split에서 join까지 도달 가능한 노드들만 수집
            fwd_visited: Set[ActivityNode] = set()
            fwd_queue = deque([start_candidate])
            while fwd_queue:
                cur = fwd_queue.popleft()
                if cur in fwd_visited:
                    continue
                fwd_visited.add(cur)

                if cur is not start_candidate and cur is not join_node:
                    between_nodes.append(cur.getTracingTag())

                if cur is join_node:
                    continue

                for f in _non_feedback_out(cur.getOutgoingSequenceFlows()):
                    nxt = f.getTargetActivity()
                    if nxt and (nxt is join_node or _can_reach(nxt, join_node)) and nxt not in fwd_visited:
                        fwd_queue.append(nxt)

            # 보수적으로 split의 즉시 자식(비-게이트웨이, join 도달 가능)을 block_members에도 포함
            for nid in possible_children:
                if nid not in between_nodes:
                    between_nodes.append(nid)

            return BlockResult(
                start_container_id=start_candidate.getTracingTag(),
                end_container_id=join_node.getTracingTag(),
                branch_count=branch_count,
                block_members=between_nodes,
                possible_block_members=possible_children,
            )

        # fallback: split을 찾지 못한 경우 안전 반환
        return BlockResult(
            start_container_id=None,
            end_container_id=join_node.getTracingTag(),
            branch_count=branch_count,
            block_members=[],
            possible_block_members=[],
        )

    @staticmethod
    def get_possible_block_members(block_members: List[ActivityNode], process_instance: Optional[Any] = None) -> List[ActivityNode]:
        return _BlockFinderCore.getPossibleBlockMembers(block_members, process_instance)

    @staticmethod
    def get_block_members_from_join(join_activity: ActivityNode) -> List[ActivityNode]:
        return _BlockFinderCore(join_activity).getBlockMembers()


__all__ = [
    "ActivityNode",
    "BlockFinder",
    "BlockResult",
    "ProcessGraph",
    "SequenceFlow",
]
