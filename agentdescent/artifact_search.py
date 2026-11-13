"""Opt-in proposal routing, batch novelty screening and measured-gain feedback.

Use a fresh ``ArtifactSearch`` per run and pass ``search.policies()`` to
``evolve`` or ``async_evolve``. The task runner stays fixed. Screening saves
downstream held-out evaluation, not the worker's initial rollout or optional
self-verification. Approximate screening is a text heuristic, not code equality.
"""

from __future__ import annotations

import hashlib
import math
import threading
import time
import uuid
from collections import OrderedDict, deque
from dataclasses import asdict
from typing import Any, Callable, Dict, Mapping, Optional, Sequence

from .defaults import DefaultAcceptance
from .model_router import ModelRouter, ModelSpec, RouteContext
from .policies import MergeContext, Policies, Proposal, ProposalContext
from .semantic_dedup import simhash, simhash_similarity

__all__ = ["ArtifactSearch"]


class ArtifactSearch:
    """Compose existing policies without changing the acceptance or audit gates.

    ``proposers`` maps each model name to an ordinary four-argument reflector
    (rendered, task, output, reward). One call selects one reflector, with no
    hidden retries. Each model gets one initial attempt before Thompson routing.

    Feedback is positive *measured held-out gain*, not a commit reward. Only a
    measured candidate matching one identified proposal receives credit; fused
    candidates are not assigned speculative per-model rewards. Unmeasured work
    is not a zero-quality observation. Costs are ModelSpec's configured units,
    not inferred token counts or measured prices. Pending identities are bounded
    and run-local; checkpoint/resume does not restore this learner's state.
    """

    def __init__(self, models: Sequence[ModelSpec],
                 proposers: Mapping[str, Callable], *, acceptance: Any = None,
                 similarity_threshold: Optional[float] = None,
                 max_pending: int = 4096, cost_weight: float = 0.5,
                 seed: int = 0) -> None:
        models = tuple(models)
        if set(proposers) != {model.name for model in models}:
            raise ValueError("proposers must match the model names exactly")
        if any(not callable(fn) for fn in proposers.values()):
            raise TypeError("each proposer must be callable")
        if isinstance(max_pending, bool) or not isinstance(max_pending, int) or max_pending < 1:
            raise ValueError("max_pending must be a positive integer")
        if similarity_threshold is not None:
            if (isinstance(similarity_threshold, bool)
                    or not math.isfinite(float(similarity_threshold))
                    or not 0.0 < float(similarity_threshold) <= 1.0):
                raise ValueError("similarity_threshold must be in (0, 1]")
            similarity_threshold = float(similarity_threshold)
        self.router = ModelRouter(models, cost_weight=cost_weight, seed=seed)
        self.proposers = dict(proposers)
        self.acceptance = acceptance if acceptance is not None else DefaultAcceptance()
        if not callable(getattr(self.acceptance, "accept", None)):
            raise TypeError("acceptance must implement accept")
        self.similarity_threshold = similarity_threshold
        self.max_pending = max_pending
        self.seed = seed
        self._models = {model.name: model for model in models}
        self._cold = deque(self._models)
        self._pending: OrderedDict[str, str] = OrderedDict()
        self._seen: OrderedDict[Any, Optional[int]] = OrderedDict()
        self._artifact = None
        self._lock = threading.RLock()
        self._counters = dict.fromkeys(("generated", "generation_failures", "empty",
                                       "screened", "duplicates", "feedback",
                                       "unattributed", "evicted"), 0)
        self._generation_seconds = 0.0
        self._configured_cost = 0.0

    def policies(self) -> Policies:
        """The optional bundle; other Policies slots retain their defaults."""
        return Policies(proposal=self, screen=self, acceptance=self)

    def configure(self, config: Any) -> None:
        hook = getattr(self.acceptance, "configure", None)
        if callable(hook):
            hook(config)

    def bind(self, verifier: Any) -> None:
        hook = getattr(self.acceptance, "bind", None)
        if callable(hook):
            hook(verifier)

    def on_screen_reject(self) -> None:
        hook = getattr(self.acceptance, "on_screen_reject", None)
        if callable(hook):
            hook()

    def policy_fingerprint(self) -> Dict[str, Any]:
        from .policies import policy_digest
        return {"models": [asdict(m) for m in self._models.values()],
                "similarity_threshold": self.similarity_threshold,
                "max_pending": self.max_pending,
                "seed": self.seed,
                "cost_weight": self.router.cost_weight,
                "acceptance": policy_digest(Policies(acceptance=self.acceptance))}

    def propose(self, ctx: ProposalContext) -> Sequence[Proposal]:
        with self._lock:
            model = (self._cold.popleft() if self._cold else
                     self.router.choose(RouteContext(
                         task_id=str(ctx.task.id), difficulty=1.0 - ctx.reward)).model)
            self._configured_cost += self._models[model].cost
        started = time.perf_counter()
        try:
            text = self.proposers[model](ctx.rendered, ctx.task, ctx.output, ctx.reward)
            if text is not None and not isinstance(text, str):
                raise TypeError("an ArtifactSearch proposer must return str or None")
        except Exception:
            with self._lock:
                self._counters["generation_failures"] += 1
            raise
        finally:
            with self._lock:
                self._generation_seconds += time.perf_counter() - started
        with self._lock:
            if text is None or not text.strip():
                self._counters["empty"] += 1
                return ()
            pid = uuid.uuid4().hex
            self._pending[pid] = model
            self._counters["generated"] += 1
            if len(self._pending) > self.max_pending:
                self._pending.popitem(last=False)
                self._counters["evicted"] += 1
            return (Proposal(text, pid),)

    def begin_batch(self, artifact: Any) -> None:
        """Reset deduplication for this head and batch, allowing later retries."""
        with self._lock:
            self._artifact = artifact
            self._seen.clear()

    def screen(self, card: Any) -> Optional[str]:
        with self._lock:
            if self._artifact is None:
                raise RuntimeError("begin_batch must supply the candidate's base artifact")
            # Applying the actual diff preserves paths, deletions and unchanged
            # files. Comparing just ops would conflate edits to different bases.
            rendered = self._artifact.apply(card.diff).render()
            digest = hashlib.sha256(rendered.encode("utf-8")).hexdigest()
            # Screening precedes staleness. An old card that is later dropped
            # must not suppress a fresh proposal of the same candidate.
            scope = (card.diff.target, card.branch or "dev",
                     tuple(sorted(card.base_version.items())))
            key = (scope, digest)
            fingerprint = simhash(rendered) if self.similarity_threshold is not None else None
            duplicate = key in self._seen
            if not duplicate and fingerprint is not None:
                duplicate = any(simhash_similarity(fingerprint, previous) >= self.similarity_threshold
                                for (prior_scope, _), previous in self._seen.items()
                                if prior_scope == scope)
            self._counters["screened"] += 1
            if duplicate:
                self._counters["duplicates"] += 1
                self._pending.pop(card.proposal_id, None)
                return "duplicate candidate in this merge batch"
            self._seen[key] = fingerprint
            if len(self._seen) > self.max_pending:
                self._seen.popitem(last=False)
            return None

    def accept(self, ctx: MergeContext):
        decision = self.acceptance.accept(ctx)
        with self._lock:
            ids = {card.proposal_id for card in ctx.cards
                   if card.proposal_id and ctx.diff is not None
                   and card.diff.diff_id == ctx.diff.diff_id
                   and card.diff.target == ctx.diff.target
                   and card.diff.ops == ctx.diff.ops}
            counts = (*ctx.base_counts, *ctx.cand_counts)
            measured = (ctx.comparable() and all(math.isfinite(v) and v >= 0 for v in counts)
                        and sum(ctx.base_counts) > 0 and sum(ctx.cand_counts) > 0)
            pid = next(iter(ids)) if len(ids) == 1 else None
            model = self._pending.get(pid)
            if model is not None and measured:
                gain = max(0.0, MergeContext.rate(ctx.cand_counts) - MergeContext.rate(ctx.base_counts))
                self.router.observe(model, reward=gain, cost=self._models[model].cost)
                self._counters["feedback"] += 1
            elif any(card.proposal_id in self._pending for card in ctx.cards):
                self._counters["unattributed"] += 1
            # Other cards in this completed merge were not individually measured.
            # Retire their tickets without inventing negative quality labels.
            for card in ctx.cards:
                self._pending.pop(card.proposal_id, None)
        return decision

    def report(self) -> Dict[str, Any]:
        """Measured generation time, configured cost units and routing feedback."""
        with self._lock:
            return {"counters": dict(self._counters), "pending": len(self._pending),
                    "generation_seconds": self._generation_seconds,
                    "configured_cost": self._configured_cost,
                    "routing": asdict(self.router.report())}
