from __future__ import annotations

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
        value = self.properties.get("isFeedback")
        if value is None:
            value = self.properties.get("feedback")
        if value is None and isinstance(self.properties.get("type"), str):
            value = self.properties.get("type")
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

        branch_count = self.graph.count_incoming(join_node, ignore_feedback=True)
        if branch_count < 2:
            auto_join = self.graph.find_nearest_join(join_node)
            if auto_join is not None:
                join_node = auto_join
                branch_count = self.graph.count_incoming(join_node, ignore_feedback=True)

        core = _BlockFinderCore(join_node)
        members = core.getBlockMembers()

        if not members:
            return BlockResult(
                start_container_id=None,
                end_container_id=join_node.getTracingTag(),
                branch_count=branch_count,
                block_members=[],
                possible_block_members=[],
            )

        possible_members = _BlockFinderCore.getPossibleBlockMembers(members, process_instance)
        distinct_possible = []
        seen_ids: Set[str] = set()
        for node in possible_members:
            node_id = node.getTracingTag()
            if node_id not in seen_ids:
                seen_ids.add(node_id)
                distinct_possible.append(node_id)

        return BlockResult(
            start_container_id=members[-1].getTracingTag(),
            end_container_id=join_node.getTracingTag(),
            branch_count=branch_count,
            block_members=[member.getTracingTag() for member in members],
            possible_block_members=distinct_possible,
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
