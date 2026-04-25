"""
masev.metrics -- Core metric computations for multi-agent evaluation.

Implements the four MASEV dimensions:
  C: Coordination Efficiency
  Q: Communication Quality
  R: Role Adherence
  E: Emergent Behavior Detection
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
from scipy.spatial.distance import cosine as cosine_dist
from scipy.stats import entropy as scipy_entropy

from .models import (
    Action,
    AgentSpec,
    EmergentBehaviors,
    Message,
    Trace,
    TraceStep,
)


@dataclass
class MetricConfig:
    """Hyperparameters for MASEV metrics (Table A.1 in paper)."""
    # Coordination
    redundancy_threshold: float = 0.85  # tau
    alpha_entropy: float = 0.40
    alpha_redundancy: float = 0.35
    alpha_parallelism: float = 0.25

    # Communication
    mur_threshold: float = 0.05  # epsilon
    beta_mur: float = 0.45
    beta_density: float = 0.30
    beta_overhead: float = 0.25
    expected_msgs_per_edge_per_step: float = 0.5  # beta scaling

    # Role adherence
    drift_penalty: float = 0.30  # lambda
    drift_window_size: int = 5

    # Emergent behavior
    free_riding_contrib_threshold: float = 0.15  # gamma_contrib
    free_riding_recv_threshold: float = 0.30  # gamma_recv

    # Embedding
    embedding_dim: int = 64  # for hash-based fallback embeddings


# ---------------------------------------------------------------------------
# Embedding helpers (lightweight fallback when sentence-transformers unavailable)
# ---------------------------------------------------------------------------

_encoder = None


def _get_encoder():
    global _encoder
    if _encoder is not None:
        return _encoder
    try:
        from sentence_transformers import SentenceTransformer
        _encoder = SentenceTransformer("all-MiniLM-L6-v2")
    except ImportError:
        _encoder = None
    return _encoder


def embed_texts(texts: list[str], dim: int = 64) -> np.ndarray:
    """Embed a list of texts. Uses sentence-transformers if available, else hash."""
    encoder = _get_encoder()
    if encoder is not None:
        return encoder.encode(texts, show_progress_bar=False)

    # Fallback: deterministic hash-based embedding
    result = np.zeros((len(texts), dim), dtype=np.float32)
    for i, text in enumerate(texts):
        tokens = text.lower().split()
        for j, tok in enumerate(tokens):
            h = hash(tok) & 0xFFFFFFFF
            idx = h % dim
            sign = 1.0 if (h // dim) % 2 == 0 else -1.0
            result[i, idx] += sign * (1.0 / (1.0 + j * 0.1))
        norm = np.linalg.norm(result[i])
        if norm > 0:
            result[i] /= norm
    return result


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity between two vectors."""
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


# ---------------------------------------------------------------------------
# C: Coordination Efficiency
# ---------------------------------------------------------------------------

def compute_coordination_entropy(trace: Trace, config: MetricConfig) -> float:
    """
    Coordination Entropy: measures action specialization across agents.
    Low entropy = agents are specialized. High entropy = diffuse behavior.
    Returns normalized score in [0, 1] where 1 = perfectly specialized.
    """
    agents = trace.agents
    if not agents:
        return 0.0

    # Build action-type distribution per agent
    agent_action_types: dict[str, list[str]] = defaultdict(list)
    for step in trace.steps:
        for action in step.actions:
            agent_action_types[action.agent_id].append(action.action_type.value)

    if not agent_action_types:
        return 0.0

    # Get all unique action types
    all_types = set()
    for types in agent_action_types.values():
        all_types.update(types)
    all_types_list = sorted(all_types)
    n_types = len(all_types_list)

    if n_types <= 1:
        return 1.0  # Only one action type = trivially specialized

    # Compute per-agent entropy
    total_entropy = 0.0
    for agent_id in agents:
        types = agent_action_types.get(agent_id, [])
        if not types:
            continue
        counts = Counter(types)
        probs = np.array([counts.get(t, 0) for t in all_types_list], dtype=float)
        total = probs.sum()
        if total > 0:
            probs /= total
            total_entropy += scipy_entropy(probs, base=2)

    max_entropy = len(agents) * math.log2(n_types) if n_types > 1 else 1.0
    if max_entropy == 0:
        return 1.0

    return max(0.0, min(1.0, 1.0 - total_entropy / max_entropy))


def compute_redundancy_ratio(trace: Trace, config: MetricConfig) -> float:
    """
    Redundancy Ratio: fraction of non-overlapping work.
    1.0 = no duplicate work. 0.0 = everything duplicated.
    """
    # Collect actions per timestep, grouped by step
    all_pairs = 0
    redundant_pairs = 0

    for step in trace.steps:
        if len(step.actions) < 2:
            continue

        # Embed action contents
        contents = [a.content for a in step.actions]
        embeddings = embed_texts(contents, config.embedding_dim)

        agent_ids = [a.agent_id for a in step.actions]
        for i in range(len(step.actions)):
            for j in range(i + 1, len(step.actions)):
                if agent_ids[i] == agent_ids[j]:
                    continue
                all_pairs += 1
                sim = cosine_similarity(embeddings[i], embeddings[j])
                if sim >= config.redundancy_threshold:
                    redundant_pairs += 1

    if all_pairs == 0:
        return 1.0

    return 1.0 - redundant_pairs / all_pairs


def compute_parallelism_index(trace: Trace, config: MetricConfig) -> float:
    """
    Parallelism Index: fraction of timesteps with concurrent agent activity.
    """
    if not trace.steps:
        return 0.0

    parallel_steps = 0
    for step in trace.steps:
        active_agents = set(a.agent_id for a in step.actions)
        if len(active_agents) > 1:
            parallel_steps += 1

    return parallel_steps / len(trace.steps)


def compute_coordination(trace: Trace, config: MetricConfig) -> tuple[float, float, float, float]:
    """
    Aggregate coordination efficiency score.
    Returns: (C, C_entropy, C_redundancy, C_parallelism)
    """
    c_ent = compute_coordination_entropy(trace, config)
    c_red = compute_redundancy_ratio(trace, config)
    c_par = compute_parallelism_index(trace, config)

    c = (config.alpha_entropy * c_ent
         + config.alpha_redundancy * c_red
         + config.alpha_parallelism * c_par)

    return c, c_ent, c_red, c_par


# ---------------------------------------------------------------------------
# Q: Communication Quality
# ---------------------------------------------------------------------------

def compute_message_utility_ratio(trace: Trace, config: MetricConfig) -> float:
    """
    MUR: fraction of messages that change the recipient's next action.
    Approximated by checking if the recipient's action type or content
    changes after receiving a message vs. their baseline behavior.
    """
    if not trace.steps:
        return 0.0

    # Build per-agent action history
    agent_actions_by_step: dict[str, dict[int, Action]] = defaultdict(dict)
    for step in trace.steps:
        for action in step.actions:
            agent_actions_by_step[action.agent_id][step.step_id] = action

    # Build baseline action-type distribution per agent
    agent_baseline: dict[str, Counter] = defaultdict(Counter)
    for step in trace.steps:
        for action in step.actions:
            agent_baseline[action.agent_id][action.action_type.value] += 1

    total_messages = 0
    useful_messages = 0

    for i, step in enumerate(trace.steps):
        for msg in step.messages:
            total_messages += 1
            receiver = msg.receiver

            # Check if receiver's next action differs from their baseline
            next_step_id = step.step_id + 1
            next_action = agent_actions_by_step.get(receiver, {}).get(next_step_id)
            prev_action = agent_actions_by_step.get(receiver, {}).get(step.step_id)

            if next_action is None:
                continue

            # Simple utility check: did the action type change, or
            # did the content become semantically related to the message?
            changed = False

            if prev_action is not None and next_action.action_type != prev_action.action_type:
                changed = True
            elif prev_action is None:
                changed = True  # Agent was idle, now active
            else:
                # Check semantic similarity between message and next action
                embs = embed_texts([msg.content, next_action.content], config.embedding_dim)
                sim = cosine_similarity(embs[0], embs[1])
                if sim > config.mur_threshold:
                    changed = True

            if changed:
                useful_messages += 1

    if total_messages == 0:
        return 1.0

    return useful_messages / total_messages


def compute_information_density(trace: Trace, config: MetricConfig) -> float:
    """
    Information Density: semantic entropy / message count.
    High density = concise, non-redundant messages.
    """
    all_messages = []
    for step in trace.steps:
        all_messages.extend(step.messages)

    if len(all_messages) <= 1:
        return 1.0

    contents = [m.content for m in all_messages]
    embeddings = embed_texts(contents, config.embedding_dim)

    # Compute pairwise similarities
    n = len(embeddings)
    sims = []
    for i in range(n):
        for j in range(i + 1, n):
            sims.append(cosine_similarity(embeddings[i], embeddings[j]))

    if not sims:
        return 1.0

    # High mean similarity = low density (redundant messages)
    mean_sim = np.mean(sims)
    return max(0.0, min(1.0, 1.0 - mean_sim))


def compute_communication_overhead(trace: Trace, config: MetricConfig) -> float:
    """
    Communication Overhead: 1 - actual_messages / expected_messages.
    Values near 1 = efficient. Values near 0 = excessive messaging.
    """
    total_messages = trace.total_messages
    n_agents = len(trace.agents)
    n_steps = len(trace.steps)

    if n_agents < 2 or n_steps == 0:
        return 1.0

    n_edges = n_agents * (n_agents - 1)  # directed edges
    expected = config.expected_msgs_per_edge_per_step * n_steps * n_edges

    if expected == 0:
        return 1.0

    ratio = total_messages / expected
    return max(0.0, min(1.0, 1.0 - max(0, ratio - 1.0)))


def compute_communication(trace: Trace, config: MetricConfig) -> tuple[float, float, float, float]:
    """
    Aggregate communication quality score.
    Returns: (Q, MUR, density, overhead)
    """
    mur = compute_message_utility_ratio(trace, config)
    density = compute_information_density(trace, config)
    overhead = compute_communication_overhead(trace, config)

    q = (config.beta_mur * mur
         + config.beta_density * density
         + config.beta_overhead * overhead)

    return q, mur, density, overhead


# ---------------------------------------------------------------------------
# R: Role Adherence
# ---------------------------------------------------------------------------

def compute_role_adherence(
    trace: Trace,
    role_specs: list[AgentSpec],
    config: MetricConfig,
) -> tuple[float, float, float]:
    """
    Role Adherence: how well agents follow their role specifications.
    Returns: (R, behavioral_divergence, drift_rate)
    """
    if not role_specs:
        return 1.0, 0.0, 0.0

    spec_map = {s.agent_id: s for s in role_specs}
    divergences = []
    drift_rates = []

    for agent_id in trace.agents:
        spec = spec_map.get(agent_id)
        if spec is None:
            continue

        actions = trace.actions_by_agent(agent_id)
        if not actions:
            divergences.append(1.0)  # No actions = max divergence
            continue

        # Behavioral divergence: compare action types to expected
        observed_types = Counter(a.action_type.value for a in actions)
        total = sum(observed_types.values())
        if total == 0:
            divergences.append(1.0)
            continue

        # Build expected distribution from spec
        if spec.expected_actions:
            expected_types = Counter(spec.expected_actions)
        else:
            # If no expected actions specified, use uniform
            all_types = list(observed_types.keys())
            expected_types = Counter({t: 1 for t in all_types})

        # Align distributions
        all_keys = sorted(set(list(observed_types.keys()) + list(expected_types.keys())))
        p = np.array([observed_types.get(k, 0) for k in all_keys], dtype=float)
        q = np.array([expected_types.get(k, 0) for k in all_keys], dtype=float)

        p_sum, q_sum = p.sum(), q.sum()
        if p_sum > 0:
            p /= p_sum
        if q_sum > 0:
            q /= q_sum

        # Jensen-Shannon divergence
        m = 0.5 * (p + q)
        js_div = 0.0
        for pi, qi, mi in zip(p, q, m):
            if mi > 0:
                if pi > 0:
                    js_div += 0.5 * pi * math.log2(pi / mi)
                if qi > 0:
                    js_div += 0.5 * qi * math.log2(qi / mi)

        divergences.append(min(1.0, js_div))

        # Role drift: sliding window divergence changes
        window = config.drift_window_size
        if len(actions) >= 2 * window:
            window_divs = []
            for w_start in range(0, len(actions) - window + 1, window):
                w_actions = actions[w_start:w_start + window]
                w_counts = Counter(a.action_type.value for a in w_actions)
                w_p = np.array([w_counts.get(k, 0) for k in all_keys], dtype=float)
                w_total = w_p.sum()
                if w_total > 0:
                    w_p /= w_total
                w_m = 0.5 * (w_p + q)
                w_js = 0.0
                for pi, qi, mi in zip(w_p, q, w_m):
                    if mi > 0:
                        if pi > 0:
                            w_js += 0.5 * pi * math.log2(pi / mi)
                        if qi > 0:
                            w_js += 0.5 * qi * math.log2(qi / mi)
                window_divs.append(min(1.0, w_js))

            if len(window_divs) >= 2:
                diffs = [abs(window_divs[i] - window_divs[i-1])
                         for i in range(1, len(window_divs))]
                drift_rates.append(np.mean(diffs))

    avg_div = np.mean(divergences) if divergences else 0.0
    avg_drift = np.mean(drift_rates) if drift_rates else 0.0

    r = max(0.0, 1.0 - avg_div - config.drift_penalty * avg_drift)
    return r, avg_div, avg_drift


# ---------------------------------------------------------------------------
# E: Emergent Behavior Detection
# ---------------------------------------------------------------------------

def detect_emergent_behaviors(
    trace: Trace, config: MetricConfig
) -> EmergentBehaviors:
    """Detect emergent multi-agent behaviors from a trace."""
    agents = trace.agents
    n_agents = len(agents)
    n_steps = len(trace.steps)

    if n_agents < 2 or n_steps == 0:
        return EmergentBehaviors()

    # Per-agent stats
    action_counts: dict[str, int] = defaultdict(int)
    msg_sent: dict[str, int] = defaultdict(int)
    msg_recv: dict[str, int] = defaultdict(int)
    msg_pairs: dict[tuple[str, str], int] = defaultdict(int)

    for step in trace.steps:
        for action in step.actions:
            action_counts[action.agent_id] += 1
        for msg in step.messages:
            msg_sent[msg.sender] += 1
            msg_recv[msg.receiver] += 1
            msg_pairs[(msg.sender, msg.receiver)] += 1

    total_actions = sum(action_counts.values()) or 1
    total_msgs = sum(msg_recv.values()) or 1

    # --- Free-Riding ---
    free_riders = []
    for agent_id in agents:
        contrib_ratio = action_counts.get(agent_id, 0) / (total_actions / n_agents) if total_actions > 0 else 0
        recv_ratio = msg_recv.get(agent_id, 0) / (total_msgs / n_agents) if total_msgs > 0 else 0

        # Normalized: agent contributes < threshold of fair share but receives > threshold
        if contrib_ratio < config.free_riding_contrib_threshold / (1.0 / n_agents) and recv_ratio > config.free_riding_recv_threshold / (1.0 / n_agents):
            free_riders.append(agent_id)

    free_riding_score = len(free_riders) / n_agents

    # --- Trust Polarization ---
    # Build adjacency and detect clustering
    adj = np.zeros((n_agents, n_agents))
    agent_idx = {a: i for i, a in enumerate(agents)}
    for (s, r), count in msg_pairs.items():
        if s in agent_idx and r in agent_idx:
            adj[agent_idx[s], agent_idx[r]] += count

    total_edges = adj.sum()
    if total_edges > 0 and n_agents > 2:
        # Simple polarization: ratio of edges within top-2 clusters vs total
        sym = adj + adj.T
        row_sums = sym.sum(axis=1)
        # Split agents into two groups by communication density
        sorted_agents = np.argsort(row_sums)
        mid = n_agents // 2
        group_a = set(sorted_agents[:mid])
        group_b = set(sorted_agents[mid:])

        inter_edges = 0
        for i in group_a:
            for j in group_b:
                inter_edges += sym[i, j]

        polarization = max(0.0, 1.0 - inter_edges / total_edges) if total_edges > 0 else 0.0
    else:
        polarization = 0.0

    # --- Spontaneous Specialization ---
    # Check if action entropy decreases over time
    specialization_scores = []
    for agent_id in agents:
        actions = trace.actions_by_agent(agent_id)
        if len(actions) < 6:
            continue

        mid = len(actions) // 2
        early = Counter(a.action_type.value for a in actions[:mid])
        late = Counter(a.action_type.value for a in actions[mid:])

        early_probs = np.array(list(early.values()), dtype=float)
        late_probs = np.array(list(late.values()), dtype=float)

        if early_probs.sum() > 0:
            early_probs /= early_probs.sum()
        if late_probs.sum() > 0:
            late_probs /= late_probs.sum()

        early_ent = scipy_entropy(early_probs, base=2) if len(early_probs) > 1 else 0
        late_ent = scipy_entropy(late_probs, base=2) if len(late_probs) > 1 else 0

        if early_ent > 0:
            specialization_scores.append(max(0, (early_ent - late_ent) / early_ent))

    specialization = np.mean(specialization_scores) if specialization_scores else 0.0

    # --- Leadership Emergence ---
    # Agent with disproportionately high message sending
    if total_msgs > 0:
        send_ratios = {a: msg_sent.get(a, 0) / total_msgs for a in agents}
        max_send = max(send_ratios.values())
        fair_share = 1.0 / n_agents
        leadership = max(0.0, min(1.0, (max_send - fair_share) / (1.0 - fair_share))) if fair_share < 1.0 else 0.0
    else:
        leadership = 0.0

    # --- Information Hoarding ---
    # Agents who receive but don't relay information
    hoarding_scores = []
    for agent_id in agents:
        received = msg_recv.get(agent_id, 0)
        sent = msg_sent.get(agent_id, 0)
        if received > 0:
            relay_ratio = sent / received
            if relay_ratio < 0.3:  # Receives but rarely relays
                hoarding_scores.append(1.0 - relay_ratio)

    hoarding = np.mean(hoarding_scores) if hoarding_scores else 0.0

    return EmergentBehaviors(
        free_riding=min(1.0, free_riding_score),
        trust_polarization=min(1.0, polarization),
        spontaneous_specialization=min(1.0, specialization),
        leadership_emergence=min(1.0, leadership),
        information_hoarding=min(1.0, hoarding),
        details={
            "free_riders": free_riders,
        },
    )
