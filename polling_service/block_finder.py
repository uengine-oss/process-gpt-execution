# block_finder.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Set, Optional, Union, TYPE_CHECKING, Iterable, Deque
from collections import deque
import json

if TYPE_CHECKING:
    # 타입 검사용으로만 import (런타임 순환 의존 방지)
    from process_definition import ProcessDefinition


@dataclass
class BlockResult:
    """
    스플릿(시작 컨테이너) ~ 조인(끝 컨테이너) 사이 블록 정보
    - 조인은 block에 포함되지 않음
    - 스플릿은 포함됨
    """
    start_container_id: str               # 매칭 스플릿 컨테이너 id
    end_container_id: str                 # 입력 조인 컨테이너 id
    branch_count: int                     # 분기 수 N (조인의 incoming 수)
    branch_paths: List[List[str]]         # 각 분기 경로(스플릿 다음 → 조인 직전, 피드백 제외)

    @property
    def node_ids(self) -> List[str]:
        """스플릿 포함, 조인 제외 전체 블록 노드 id(중복 제거, 경로 순서 우선 병합)."""
        seen: Set[str] = set()
        out: List[str] = []
        if self.start_container_id not in seen:
            seen.add(self.start_container_id)
            out.append(self.start_container_id)
        for path in self.branch_paths:
            for nid in path:
                if nid not in seen:
                    seen.add(nid)
                    out.append(nid)
        return out

    def to_dict(self) -> dict:
        return {
            "start_container_id": self.start_container_id,
            "end_container_id": self.end_container_id,
            "branch_count": self.branch_count,
            "branch_paths": self.branch_paths,
            "node_ids": self.node_ids,
        }


class BlockFinder:
    """
    Robust block finder:
      - 입력: (조인 컨테이너 | 임의 노드) id 또는 객체, ProcessDefinition
      - 출력: 스플릿~조인 사이 블록(브랜치별 경로, 피드백 제외)

    강건 검증 규칙:
      1) 스플릿의 out-degree == 조인의 incoming 수(N)
      2) 각 브랜치 경로는 조인까지 '선형'(내부 노드 indeg==1, outdeg==1)
      3) 브랜치 간 노드 중복 없음(조기 머지 금지)
      4) 중간 재분기(outdeg>1) 금지
      5) '피드백' 노드는 그래프에서 제거한 것처럼 취급하여 플래튼
    """

    def __init__(
        self,
        pd: "ProcessDefinition",
        feedback_keywords: Iterable[str] = ("feedback", "피드백"),
        feedback_property_flags: Iterable[str] = ("isFeedback", "feedback"),
    ):
        self.pd = pd
        self._fb_keys = tuple(k.lower() for k in feedback_keywords)
        self._fb_flags = set(feedback_property_flags)

    # ------------------------------------------------------------------
    # 그래프 원자료
    # ------------------------------------------------------------------
    def _get_incoming_ids_raw(self, node_id: str) -> List[str]:
        return [s.source for s in (self.pd.sequences or []) if getattr(s, "target", None) == node_id]

    def _get_outgoing_ids_raw(self, node_id: str) -> List[str]:
        return [s.target for s in (self.pd.sequences or []) if getattr(s, "source", None) == node_id]

    def _resolve_node(self, node_id: str) -> Optional[Any]:
        return (
            self.pd.find_activity_by_id(node_id)
            or self.pd.find_sub_process_by_id(node_id)
            or self.pd.find_gateway_by_id(node_id)
            or self.pd.find_event_by_id(node_id)
        )

    def _get_node_type(self, node_id: str) -> str:
        n = self._resolve_node(node_id)
        return (getattr(n, "type", None) or "").lower()

    def _is_gateway(self, node_id: str) -> bool:
        return "gateway" in self._get_node_type(node_id)

    def _is_start_event(self, node_id: str) -> bool:
        return "startevent" in self._get_node_type(node_id)

    # ------------------------------------------------------------------
    # 피드백 판단/플래튼 이웃
    # ------------------------------------------------------------------
    def _is_feedback_node(self, node_id: str) -> bool:
        n = self._resolve_node(node_id)
        if not n:
            return False
        name = (getattr(n, "name", None) or getattr(n, "id", "")).lower()
        desc = (getattr(n, "description", "") or "").lower()
        if any(k in name or k in desc for k in self._fb_keys):
            return True

        props = getattr(n, "properties", None)
        if not props:
            return False
        try:
            obj = json.loads(props) if isinstance(props, str) else dict(props)
            for f in self._fb_flags:
                val = obj.get(f)
                if val is True or (isinstance(val, str) and val.lower() == "true"):
                    return True
        except Exception:
            # properties가 JSON이 아니거나 dict 변환 실패 → 피드백 아님으로 처리
            pass
        return False

    def _get_outgoing_ids_ignoring_feedback(self, node_id: str) -> List[str]:
        """u -> (feedback ...)* -> v 를 u -> v 로 평탄화한 out-neighbors"""
        res: Set[str] = set()
        stack: List[str] = list(self._get_outgoing_ids_raw(node_id))
        seen: Set[str] = set()
        while stack:
            nid = stack.pop()
            if nid in seen:
                continue
            seen.add(nid)
            if self._is_feedback_node(nid):
                stack.extend(self._get_outgoing_ids_raw(nid))
            else:
                res.add(nid)
        return list(res)

    def _get_incoming_ids_ignoring_feedback(self, node_id: str) -> List[str]:
        """feedback 제거 in-neighbors(플래튼)"""
        res: Set[str] = set()
        stack: List[str] = list(self._get_incoming_ids_raw(node_id))
        seen: Set[str] = set()
        while stack:
            nid = stack.pop()
            if nid in seen:
                continue
            seen.add(nid)
            if self._is_feedback_node(nid):
                stack.extend(self._get_incoming_ids_raw(nid))
            else:
                res.add(nid)
        return list(res)

    def _out_degree_ignoring_feedback(self, node_id: str) -> int:
        return len(self._get_outgoing_ids_ignoring_feedback(node_id))

    def _in_degree_ignoring_feedback(self, node_id: str) -> int:
        return len(self._get_incoming_ids_ignoring_feedback(node_id))

    # ------------------------------------------------------------------
    # 도달성/선형 경로 수집 (강건 검증)
    # ------------------------------------------------------------------
    def _can_reach_ignoring_feedback(self, src: str, dst: str) -> bool:
        if src == dst:
            return True
        seen: Set[str] = {src}
        stack: List[str] = self._get_outgoing_ids_ignoring_feedback(src)
        while stack:
            nid = stack.pop()
            if nid == dst:
                return True
            if nid in seen:
                continue
            seen.add(nid)
            stack.extend(self._get_outgoing_ids_ignoring_feedback(nid))
        return False

    def _collect_linear_path_to_join_ignoring_feedback(self, start: str, join_id: str) -> List[str]:
        """
        start부터 join 직전까지 선형 경로 수집(조인 미포함).
        검증:
          - 내부 노드 indeg==1
          - 재분기(outdeg>1) 금지 (단, 바로 join으로 가는 엣지가 있으면 그 하나만 허용)
          - 막다른 길 금지
        """
        path: List[str] = []
        cur = start
        visited: Set[str] = set()
        guard = 0
        while True:
            guard += 1
            if guard > 10000:
                raise RuntimeError("Path search too deep (cycle?)")
            if cur in visited:
                raise ValueError("Cycle detected on a branch")
            visited.add(cur)

            if cur == join_id:
                return path  # 조인은 포함하지 않음

            # 내부 노드(첫 노드는 제외)는 indeg==1 유지
            if path and self._in_degree_ignoring_feedback(cur) != 1:
                raise ValueError(f"Early-merge detected at {cur}")

            outs = self._get_outgoing_ids_ignoring_feedback(cur)
            if len(outs) == 0:
                raise ValueError(f"Dead-end before join from {start}")
            if len(outs) > 1:
                if join_id in outs:
                    outs = [join_id]  # join 직결만 허용
                else:
                    raise ValueError(f"Re-split detected at {cur}")

            path.append(cur)
            cur = outs[0]

    # ------------------------------------------------------------------
    # 입력이 조인 컨테이너가 아닐 때, 자동으로 '조인' 해석
    # ------------------------------------------------------------------
    def _resolve_join_container_id(self, node_or_id: Union[str, Any], *, log_on_fail: bool) -> Optional[str]:
        """
        규칙:
        1) 입력 자체가 게이트웨이이고 in-degree>=2면 → 그대로 조인
        2) self.pd.get_container_id(node) 가 게이트웨이이고 in-degree>=2면 → 그걸 조인
        3) 앞으로(BFS) 탐색해서 가장 가까운 '게이트웨이 & in-degree>=2'를 조인으로 채택
           - 같은 최소 거리의 후보가 여러 개면 모호 → 실패
        """
        node_id = node_or_id if isinstance(node_or_id, str) else getattr(node_or_id, "id", None)
        if not node_id:
            if log_on_fail:
                print(f"[BlockFinder:AUTOJOIN_FAIL] INVALID_INPUT | {node_or_id!r}")
            return None

        # 1) 입력이 이미 조인처럼 보이는가?
        if self._is_gateway(node_id) and self._in_degree_ignoring_feedback(node_id) >= 2:
            if log_on_fail:
                print(f"[BlockFinder:AUTOJOIN] INPUT_IS_JOIN | join_id={node_id}")
            return node_id

        # 2) 컨테이너(바로 바깥 게이트웨이)로 승격
        if hasattr(self.pd, "get_container_id"):
            container_id = self.pd.get_container_id(node_id)  # type: ignore[attr-defined]
            if container_id and self._is_gateway(container_id) and self._in_degree_ignoring_feedback(container_id) >= 2:
                if log_on_fail:
                    print(f"[BlockFinder:AUTOJOIN] VIA_CONTAINER | node={node_id} -> join_id={container_id}")
                return container_id

        # 3) 앞으로 탐색(BFS, feedback 무시)
        #    가장 가까운 '게이트웨이 & in-degree>=2'들을 수집 → 유일하면 채택
        q: Deque[tuple[str, int]] = deque()
        seen: Set[str] = set([node_id])
        for o in self._get_outgoing_ids_ignoring_feedback(node_id):
            q.append((o, 1))
            seen.add(o)

        best_dist = None
        best_candidates: List[str] = []

        while q:
            nid, dist = q.popleft()
            if best_dist is not None and dist > best_dist:
                break  # 더 먼 노드는 볼 필요 없음

            if self._is_gateway(nid) and self._in_degree_ignoring_feedback(nid) >= 2:
                best_dist = dist if best_dist is None else best_dist
                best_candidates.append(nid)
                continue

            for o in self._get_outgoing_ids_ignoring_feedback(nid):
                if o not in seen:
                    seen.add(o)
                    q.append((o, dist + 1))

        if len(best_candidates) == 1:
            if log_on_fail:
                print(f"[BlockFinder:AUTOJOIN] VIA_FORWARD | node={node_id} -> join_id={best_candidates[0]}")
            return best_candidates[0]
        elif len(best_candidates) > 1:
            if log_on_fail:
                print(f"[BlockFinder:AUTOJOIN_FAIL] AMBIGUOUS | node={node_id} candidates={best_candidates}")
            return None
        else:
            if log_on_fail:
                print(f"[BlockFinder:AUTOJOIN_FAIL] NOT_FOUND | node={node_id}")
            return None

    # ------------------------------------------------------------------
    # 공개 API: 실패 시 None 반환(기본), strict=True면 예외
    # + 실패지점 print
    # ------------------------------------------------------------------
    def find_block(
        self,
        container: Union[str, Any],
        *,
        strict: bool = False,
        log_on_fail: bool = True
    ) -> Optional[BlockResult]:
        """
        성공 시 BlockResult, 실패/모호/검증불가 시 None (strict=True면 예외 발생)
        실패 시 어디서 중단됐는지 콘솔에 print.
        container: (조인 컨테이너 | 임의 노드) id 또는 객체
        """
        def _fail(code: str, **ctx) -> Optional[BlockResult]:
            if log_on_fail:
                try:
                    print(f"[BlockFinder:FAIL] {code} | " + json.dumps(ctx, ensure_ascii=False))
                except Exception:
                    print(f"[BlockFinder:FAIL] {code} | {ctx}")
            if strict:
                raise RuntimeError(f"{code}: {ctx}")
            return None

        try:
            # 0) 입력으로부터 '조인 컨테이너 id' 자동 해석
            join_id = self._resolve_join_container_id(container, log_on_fail=log_on_fail)
            if not join_id:
                return _fail("AUTOJOIN_FAILED", container=str(container))

            # 1) 조인 incoming (피드백 제거) 및 분기 수 확인
            incomings = [nid for nid in self._get_incoming_ids_ignoring_feedback(join_id) if not self._is_start_event(nid)]
            k = len(incomings)
            if k < 2:
                return _fail("INCOMING_TOO_FEW", join_id=join_id, incomings=incomings, count=k)

            # 2) 위로 올라가며 스플릿 후보 탐색
            frontier: Set[str] = set(incomings)
            visited: Set[str] = set([join_id])
            guard = 0

            while True:
                guard += 1
                if guard > 10000:
                    return _fail("SEARCH_TOO_DEEP", join_id=join_id, frontier=list(frontier))

                # 현재 프런티어의 부모 집합(피드백/스타트 제외)
                parents: Set[str] = set()
                for nid in list(frontier):
                    parents.update(
                        p for p in self._get_incoming_ids_ignoring_feedback(nid)
                        if not self._is_start_event(p)
                    )

                if not parents:
                    return _fail("SPLIT_NOT_FOUND_REACHED_START", join_id=join_id, last_frontier=list(frontier))

                valid_split: Optional[str] = None
                final_paths: Optional[List[List[str]]] = None

                for cand in parents:
                    # out-degree == k
                    if self._out_degree_ignoring_feedback(cand) != k:
                        continue

                    outs = self._get_outgoing_ids_ignoring_feedback(cand)

                    # 모든 out이 join으로 도달 가능한가?
                    if not all(self._can_reach_ignoring_feedback(o, join_id) for o in outs):
                        continue

                    # 선형 경로 수집/검증(예외 뜨면 해당 후보는 스킵)
                    try:
                        paths = [self._collect_linear_path_to_join_ignoring_feedback(o, join_id) for o in outs]
                    except Exception as e:
                        if log_on_fail:
                            print(f"[BlockFinder:SKIP_CANDIDATE] split_candidate={cand} reason={e}")
                        continue

                    # 브랜치간 노드 중복 금지(조인 직전까지 독립)
                    seen_nodes: Set[str] = set()
                    collision = False
                    for p in paths:
                        for nid in p:
                            if nid in seen_nodes:
                                collision = True
                                break
                            seen_nodes.add(nid)
                        if collision:
                            break
                    if collision:
                        if log_on_fail:
                            print(f"[BlockFinder:SKIP_CANDIDATE] split_candidate={cand} reason=BRANCH_NODE_COLLISION")
                        continue

                    # 단일 후보 확정(여러 개면 모호하므로 한 단계 위로)
                    if valid_split is None:
                        valid_split = cand
                        final_paths = paths
                    else:
                        valid_split = None
                        final_paths = None
                        break

                if valid_split:
                    return BlockResult(
                        start_container_id=valid_split,
                        end_container_id=join_id,
                        branch_count=k,
                        branch_paths=final_paths or [],
                    )

                # 모호하거나 아직 못 찾음 → 한 단계 위로
                next_frontier = parents - visited
                if not next_frontier:
                    return _fail(
                        "AMBIGUOUS_OR_NO_SPLIT",
                        join_id=join_id,
                        parents=list(parents),
                        visited=len(visited)
                    )
                visited |= next_frontier
                frontier = next_frontier

        except Exception as e:
            return _fail("UNCAUGHT_EXCEPTION", error=str(e))


__all__ = ["BlockFinder", "BlockResult"]
