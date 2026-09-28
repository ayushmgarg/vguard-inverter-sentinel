"""nilm/library.py -- rule layer + per-home k-NN library (design 06 Sec 4).

Pipeline:
  1. Rule layer (Sec 4.1.1): classify each paired event into a physics type
     RESISTIVE / MOTOR / ELECTRONIC / VARIABLE from (phi, r_pk, h) alone.
  2. Leader clustering (Sec 4.2.2): online, within-type clustering of paired
     events into per-home prototypes, Welford mean/variance per feature.
  3. k-NN matching (Sec 4.1.2/3): once a cluster has >= 3 events it can be
     user-labelled (label_cluster / auto-label from factory priors); new
     events are then scored against labelled prototypes, d_best > d_open
     opens a new cluster instead of forcing a bad match.
  4. Overlap resolution (Sec 4.3): unresolved simultaneous events are paired
     against the top prototypes when a single match does not explain the
     residual step.
  5. Energy reconciliation (Sec 4.4): per-minute sum of assigned energy vs.
     measured aggregate; the gap is bucketed as "other/always-on".
"""
from __future__ import annotations

import dataclasses
import math
from typing import Dict, List, Optional, Tuple

import numpy as np

from nilm.event_detector import Event
from nilm.appliance_sim import APPLIANCES, ApplianceSpec, _pf_to_q_ratio

# ----------------------------------------------------------------------- #
# 1. Rule layer -- physics type (design 06 Sec 4.1.1)
# ----------------------------------------------------------------------- #
def classify_physics(ev: Event) -> str:
    phi = abs(ev.phi_deg)
    r_pk = ev.r_pk
    h = ev.h
    r_pk_ok = (not math.isnan(r_pk))
    h_ok = (not math.isnan(h))

    if r_pk_ok and phi < 10.0 and r_pk < 1.3 and (not h_ok or h < 0.05):
        return "RESISTIVE"
    if r_pk_ok and 25.0 <= phi <= 60.0 and r_pk > 3.0:
        return "MOTOR"
    if (h_ok and h > 0.15) or (r_pk_ok and 1.5 <= r_pk <= 3.0 and phi < 35.0):
        return "ELECTRONIC"
    if math.isnan(ev.t_settle_s) or ev.t_settle_s <= 0 or not r_pk_ok:
        return "VARIABLE"
    # no clean rule match: fall back on phi/r_pk proximity to RESISTIVE/MOTOR,
    # else VARIABLE (design 06 Sec 4.1: "no settle / slow ramp")
    if phi < 15.0:
        return "RESISTIVE"
    if r_pk_ok and r_pk > 2.0:
        return "MOTOR"
    return "VARIABLE"


# ----------------------------------------------------------------------- #
# Factory priors (design 06 Sec 3.2), as feature ranges, for auto-labelling
# ----------------------------------------------------------------------- #
def _factory_prior_ranges() -> Dict[str, dict]:
    ranges = {}
    for spec in APPLIANCES:
        phi_lo = math.degrees(math.atan2(spec.dP_range[0] * _pf_to_q_ratio(spec.pf_range[1]), spec.dP_range[0]))
        phi_hi = math.degrees(math.atan2(spec.dP_range[1] * _pf_to_q_ratio(spec.pf_range[0]), spec.dP_range[1]))
        ranges[spec.name] = dict(
            physics_class=spec.physics_class,
            dP=spec.dP_range,
            phi_deg=(min(phi_lo, phi_hi) - 5, max(phi_lo, phi_hi) + 5),
            r_pk=spec.r_pk_range,
            t_settle_s=spec.t_settle_range,
            h=spec.h_range,
            circuit=spec.circuit,
        )
    return ranges


FACTORY_PRIORS = _factory_prior_ranges()


def factory_prior_score(ev: Event) -> Tuple[Optional[str], float]:
    """Best-matching factory prior label and a 0-1 membership score
    (fraction of checked ranges the event falls inside)."""
    physics_class = classify_physics(ev)
    best_label, best_score = None, 0.0
    for name, rng in FACTORY_PRIORS.items():
        # physics type (Sec 4.1 rule layer) and dP (size class) are mandatory
        # gates -- an ELECTRONIC-shaped step cannot be a MOTOR appliance, and
        # a load 3x too small/large for this appliance cannot match it,
        # regardless of how well any single shape feature happens to align.
        if rng["physics_class"] != physics_class:
            continue
        dP_ok = rng["dP"][0] * 0.5 <= abs(ev.dP) <= rng["dP"][1] * 1.5
        if not dP_ok:
            continue
        checks = [True]  # the dP gate itself counts as a passed check
        checks.append(rng["phi_deg"][0] <= ev.phi_deg <= rng["phi_deg"][1])
        if not math.isnan(ev.r_pk):
            checks.append(rng["r_pk"][0] * 0.6 <= ev.r_pk <= rng["r_pk"][1] * 1.4)
        if not math.isnan(ev.t_settle_s):
            checks.append(rng["t_settle_s"][0] * 0.5 <= ev.t_settle_s <= rng["t_settle_s"][1] * 1.5)
        score = sum(checks) / len(checks)
        if score > best_score:
            best_label, best_score = name, score
    return best_label, best_score


# ----------------------------------------------------------------------- #
# 2/3. Welford stats + leader clustering + k-NN prototypes
# ----------------------------------------------------------------------- #
FEATURE_NAMES = ["logdP", "dQ_over_dP", "log_r_pk", "log_t_settle", "h", "log_dur", "tod"]
FEATURE_WEIGHTS = np.array([3.0, 2.0, 1.5, 1.0, 1.5, 1.0, 0.5])


def _feature_vec(ev: Event) -> np.ndarray:
    log_dP = math.log(max(abs(ev.dP), 1.0))
    dQ_over_dP = ev.dQ / ev.dP if abs(ev.dP) > 1e-6 else 0.0
    log_r_pk = math.log(ev.r_pk) if not math.isnan(ev.r_pk) and ev.r_pk > 0 else 0.0
    log_t_settle = math.log(max(ev.t_settle_s, 0.05))
    h = ev.h if not math.isnan(ev.h) else 0.0
    dur = ev.dur_s if not math.isnan(ev.dur_s) else 60.0
    log_dur = math.log(max(dur, 1.0))
    tod = math.atan2(ev.tod_sin, ev.tod_cos)
    return np.array([log_dP, dQ_over_dP, log_r_pk, log_t_settle, h, log_dur, tod])


@dataclasses.dataclass
class Cluster:
    cluster_id: int
    physics_class: str
    n: int = 0
    mean: np.ndarray = dataclasses.field(default_factory=lambda: np.zeros(len(FEATURE_NAMES)))
    m2: np.ndarray = dataclasses.field(default_factory=lambda: np.zeros(len(FEATURE_NAMES)))
    label: Optional[str] = None
    confidence_locked: bool = False
    last_t0: Optional[float] = None
    events: List[int] = dataclasses.field(default_factory=list)  # indices into library.events

    def update(self, x: np.ndarray):
        self.n += 1
        delta = x - self.mean
        self.mean = self.mean + delta / self.n
        delta2 = x - self.mean
        self.m2 = self.m2 + delta * delta2

    @property
    def var(self) -> np.ndarray:
        if self.n < 2:
            return np.maximum(MIN_VAR, 1e-6)
        return np.maximum(self.m2 / (self.n - 1), MIN_VAR)


D_JOIN = 1.5     # leader-clustering join threshold (design 06 Sec 4.2.2)
D_OPEN = 2.5     # k-NN "open new cluster" threshold (design 06 Sec 4.1.3)

# Minimum per-feature variance floor. Welford variance from only 2-3 samples
# is statistically unstable (can collapse near zero) and would otherwise blow
# up the weighted distance for the next, perfectly ordinary, event of the
# same appliance. Floors are set to the expected natural cycle-to-cycle
# variability of each feature: log dP of a fixed appliance varies little,
# but run duration (log_dur) and time-of-day (tod) genuinely range over most
# of their domain for an all-day cyclic load like a fridge, so those two
# floors are set close to their full-range variance (tod is a soft prior,
# weight 0.5, by design -- it should never dominate the match decision).
MIN_VAR = np.array([0.02, 0.02, 0.02, 0.03, 0.01, 1.00, 2.50])


def weighted_distance(x: np.ndarray, mean: np.ndarray, var: np.ndarray) -> float:
    std = np.sqrt(np.maximum(var, 1e-6))
    z = (x - mean) / std
    return float(np.sqrt(np.sum(FEATURE_WEIGHTS * z ** 2)))


class ApplianceLibrary:
    """Per-home appliance library: rule layer + leader clustering + k-NN."""

    def __init__(self, k: int = 3, d_join: float = D_JOIN, d_open: float = D_OPEN):
        self.k = k
        self.d_join = d_join
        self.d_open = d_open
        self.clusters: Dict[int, Cluster] = {}
        self._next_id = 0
        self.events: List[Event] = []
        self.assignments: List[int] = []  # cluster id per event (parallel to self.events)

    def _new_cluster(self, physics_class: str) -> Cluster:
        c = Cluster(self._next_id, physics_class)
        self.clusters[self._next_id] = c
        self._next_id += 1
        return c

    def _same_type_clusters(self, physics_class: str) -> List[Cluster]:
        return [c for c in self.clusters.values() if c.physics_class == physics_class]

    def ingest(self, ev: Event) -> Cluster:
        """Leader-clustering ingestion of a (paired, ON) event: builds the
        per-home library from day 1 (design 06 Sec 4.2.2)."""
        pc = classify_physics(ev)
        x = _feature_vec(ev)
        candidates = self._same_type_clusters(pc)
        best, best_d = None, math.inf
        for c in candidates:
            if c.n == 0:
                continue
            d = weighted_distance(x, c.mean, c.var)
            if d < best_d:
                best, best_d = c, d

        if best is not None and best_d < self.d_join:
            cluster = best
        else:
            cluster = self._new_cluster(pc)

        if cluster.last_t0 is not None:
            ev.period_s = ev.t0 - cluster.last_t0
        cluster.last_t0 = ev.t0
        cluster.update(x)
        cluster.events.append(len(self.events))
        self.events.append(ev)
        self.assignments.append(cluster.cluster_id)
        ev.cluster_id = cluster.cluster_id

        # auto-label from factory priors once a cluster has enough support
        if cluster.label is None and cluster.n >= 3:
            label, score = factory_prior_score(ev)
            if label is not None and score >= 0.7:
                cluster.label = label
                cluster.confidence_locked = False
        return cluster

    # -- user labelling API (design 06 Sec 4.2.3) ------------------------ #
    def clusters_needing_label(self, n_min: int = 3) -> List[Cluster]:
        return [c for c in self.clusters.values() if c.label is None and c.n >= n_min]

    def label_cluster(self, cluster_id: int, label: str, lock: bool = True):
        c = self.clusters[cluster_id]
        c.label = label
        c.confidence_locked = lock

    # -- k-NN matching / classification (design 06 Sec 4.1.2/3) ---------- #
    def match(self, ev: Event) -> Tuple[Optional[str], float, bool]:
        """Score `ev` against labelled prototypes. Returns (label, confidence,
        opened_new_cluster)."""
        pc = classify_physics(ev)
        x = _feature_vec(ev)
        labelled = [c for c in self._same_type_clusters(pc) if c.label is not None and c.n > 0]
        if not labelled:
            return None, 0.0, True

        dists = sorted(((weighted_distance(x, c.mean, c.var), c) for c in labelled), key=lambda t: t[0])
        knn = dists[: self.k]
        if knn[0][0] > self.d_open:
            return None, 0.0, True

        scores: Dict[str, float] = {}
        for d, c in knn:
            prior = 1.0
            w = math.exp(-d * d / 2.0) * prior
            scores[c.label] = scores.get(c.label, 0.0) + w
        total = sum(scores.values())
        best_label = max(scores, key=scores.get)
        confidence = scores[best_label] / total if total > 0 else 0.0
        return best_label, confidence, False

    # -- overlap resolution (design 06 Sec 4.3) --------------------------- #
    def resolve_overlap(self, dP: float, dQ: float, physics_class_hint: Optional[str] = None) -> Optional[Tuple[str, str, float]]:
        """Try to explain a residual step as the sum of two known prototypes.
        Returns (label_i, label_j, confidence) at 0.6x confidence, or None."""
        labelled = [c for c in self.clusters.values() if c.label is not None and c.n > 0]
        if len(labelled) < 2:
            return None
        # rank prototypes by proximity in raw dP to shortlist top-8 (Sec 4.3)
        proto_dP = []
        for c in labelled:
            log_dP = c.mean[0]
            proto_dP.append((c, math.exp(log_dP)))
        proto_dP.sort(key=lambda t: abs(t[1] - abs(dP) / 2))
        shortlist = proto_dP[:8]
        best = None
        for i in range(len(shortlist)):
            for j in range(i, len(shortlist)):
                ci, pi = shortlist[i]
                cj, pj = shortlist[j]
                dP_est = pi + pj
                if abs(dP) < 1e-6:
                    continue
                if abs(abs(dP) - dP_est) / abs(dP) < 0.10:
                    best = (ci.label, cj.label, 0.6)
                    return best
        return best


# ----------------------------------------------------------------------- #
# 4. Energy reconciliation (design 06 Sec 4.4)
# ----------------------------------------------------------------------- #
def energy_reconciliation(stream_t: np.ndarray, stream_P: np.ndarray, paired_ons: List[Event],
                           bin_s: float = 60.0) -> dict:
    """Every `bin_s` seconds: assigned energy (sum of paired-ON dP * overlap
    duration with the bin) vs measured aggregate energy (integral of P)."""
    t0, t1 = stream_t[0], stream_t[-1]
    dt = float(np.median(np.diff(stream_t))) if len(stream_t) > 1 else 1.0
    n_bins = max(1, int(math.ceil((t1 - t0) / bin_s)))
    measured = np.zeros(n_bins)
    assigned = np.zeros(n_bins)

    edges = t0 + np.arange(n_bins + 1) * bin_s
    idx = np.clip(((stream_t - t0) / bin_s).astype(int), 0, n_bins - 1)
    for b in range(n_bins):
        mask = idx == b
        measured[b] = float(np.sum(stream_P[mask]) * dt) / 3600.0  # Wh

    for ev in paired_ons:
        if not ev.paired or ev.t_off is None:
            continue
        on_t, off_t = ev.t0, ev.t_off
        b0 = max(0, int((on_t - t0) // bin_s))
        b1 = min(n_bins - 1, int((off_t - t0) // bin_s))
        for b in range(b0, b1 + 1):
            seg0 = max(on_t, edges[b])
            seg1 = min(off_t, edges[b + 1])
            overlap = max(0.0, seg1 - seg0)
            assigned[b] += ev.dP * overlap / 3600.0  # Wh

    total_measured = float(np.sum(np.abs(measured)))
    total_assigned = float(np.sum(np.minimum(assigned, np.abs(measured))))
    frac = total_assigned / total_measured if total_measured > 1e-9 else 0.0
    return dict(measured_wh=measured, assigned_wh=assigned, total_measured_wh=total_measured,
                total_assigned_wh=total_assigned, fraction_assigned=frac)
