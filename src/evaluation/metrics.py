"""
Precision, recall, and F1 with 95% Wilson score confidence intervals.

Wilson intervals rather than normal approximation because some detection
sources will likely have recall near 0 or 1, where the normal CI breaks
down. F1 intervals are approximated from the Wilson bounds of P and R.
"""

import json
import logging
import math
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

from src.utils.config import CONFIDENCE_LEVEL, EVALUATION_RESULTS_DIR
from src.data.manifest import DataManifest, GroundTruthLabel

logger = logging.getLogger(__name__)


@dataclass
class ConfusionMatrix:
    """Standard 2x2 confusion matrix."""
    tp: int = 0  # true positives (correctly flagged as problematic)
    fp: int = 0  # false positives (incorrectly flagged)
    tn: int = 0  # true negatives (correctly not flagged)
    fn: int = 0  # false negatives (missed — the critical failure mode)

    @property
    def total(self) -> int:
        return self.tp + self.fp + self.tn + self.fn


@dataclass
class WilsonInterval:
    """A proportion with Wilson score confidence interval."""
    value: float
    lower: float
    upper: float
    n: int

    def __str__(self) -> str:
        return f"{self.value:.3f} [{self.lower:.3f}, {self.upper:.3f}] (n={self.n})"


@dataclass
class DetectionMetrics:
    """Full evaluation metrics for one detection source."""
    source_name: str
    confusion: ConfusionMatrix
    precision: WilsonInterval
    recall: WilsonInterval
    f1: float
    f1_lower: float
    f1_upper: float


def wilson_score_interval(
    successes: int, total: int, confidence: float = CONFIDENCE_LEVEL
) -> WilsonInterval:
    """
    Compute Wilson score confidence interval for a proportion.

    More accurate than normal approximation for proportions near 0 or 1,
    and for small sample sizes. Uses the formula from Wilson (1927).
    """
    if total == 0:
        return WilsonInterval(value=0.0, lower=0.0, upper=0.0, n=0)

    p_hat = successes / total
    z = _z_score(confidence)
    z2 = z * z

    denominator = 1 + z2 / total
    centre = p_hat + z2 / (2 * total)
    spread = z * math.sqrt((p_hat * (1 - p_hat) + z2 / (4 * total)) / total)

    lower = max(0.0, (centre - spread) / denominator)
    upper = min(1.0, (centre + spread) / denominator)

    return WilsonInterval(
        value=p_hat,
        lower=lower,
        upper=upper,
        n=total,
    )


def _z_score(confidence: float) -> float:
    """Z-score for a given confidence level (two-tailed)."""
    z_table = {
        0.90: 1.645,
        0.95: 1.960,
        0.99: 2.576,
    }
    if confidence in z_table:
        return z_table[confidence]
    from statistics import NormalDist
    return NormalDist().inv_cdf((1 + confidence) / 2)


def compute_metrics(
    source_name: str,
    predictions: dict[str, bool],
    ground_truth: dict[str, bool],
) -> DetectionMetrics:
    """
    Compute precision, recall, F1 with Wilson CIs for a detection source.

    Args:
        source_name: Name of the detection source.
        predictions: {doc_id: flagged} from the detection source.
        ground_truth: {doc_id: is_positive} from the manifest.

    Returns:
        DetectionMetrics with confusion matrix and Wilson intervals.
    """
    cm = ConfusionMatrix()

    for doc_id in ground_truth:
        actual = ground_truth[doc_id]
        predicted = predictions.get(doc_id, False)

        if actual and predicted:
            cm.tp += 1
        elif actual and not predicted:
            cm.fn += 1
        elif not actual and predicted:
            cm.fp += 1
        else:
            cm.tn += 1

    precision_n = cm.tp + cm.fp
    precision = wilson_score_interval(cm.tp, precision_n)

    recall_n = cm.tp + cm.fn
    recall = wilson_score_interval(cm.tp, recall_n)

    if precision.value + recall.value > 0:
        f1 = 2 * (precision.value * recall.value) / (precision.value + recall.value)
    else:
        f1 = 0.0

    # F1 CI approximation using the lower/upper bounds of P and R
    if precision.lower + recall.lower > 0:
        f1_lower = 2 * (precision.lower * recall.lower) / (precision.lower + recall.lower)
    else:
        f1_lower = 0.0

    if precision.upper + recall.upper > 0:
        f1_upper = 2 * (precision.upper * recall.upper) / (precision.upper + recall.upper)
    else:
        f1_upper = 0.0

    return DetectionMetrics(
        source_name=source_name,
        confusion=cm,
        precision=precision,
        recall=recall,
        f1=f1,
        f1_lower=f1_lower,
        f1_upper=f1_upper,
    )


def build_ground_truth(manifest: DataManifest, arm: int = 1) -> dict[str, bool]:
    """
    Build ground truth dict from manifest labels.

    Arm 1: RETRACTED = positive, CONTROL = negative
    Arm 2: OUTDATED = positive, CURRENT = negative
    """
    gt = {}
    for doc_id, entry in manifest.entries.items():
        if arm == 1:
            if entry.ground_truth == GroundTruthLabel.RETRACTED:
                gt[doc_id] = True
            elif entry.ground_truth == GroundTruthLabel.CONTROL:
                gt[doc_id] = False
        elif arm == 2:
            if entry.ground_truth == GroundTruthLabel.OUTDATED:
                gt[doc_id] = True
            elif entry.ground_truth == GroundTruthLabel.CURRENT:
                gt[doc_id] = False
    return gt


def evaluate_all_sources(
    manifest: DataManifest,
    detection_results: dict[str, dict[str, bool]],
    arm: int = 1,
) -> list[DetectionMetrics]:
    """
    Evaluate all detection sources against the manifest ground truth.

    Args:
        manifest: Data manifest with ground truth labels.
        detection_results: {source_name: {doc_id: flagged}} for each source.
        arm: Study arm (1 = retraction, 2 = staleness).

    Returns:
        List of DetectionMetrics, one per source.
    """
    gt = build_ground_truth(manifest, arm)

    all_metrics = []
    for source_name, predictions in detection_results.items():
        metrics = compute_metrics(source_name, predictions, gt)
        all_metrics.append(metrics)

        logger.info(
            f"{source_name}: P={metrics.precision} R={metrics.recall} "
            f"F1={metrics.f1:.3f} [{metrics.f1_lower:.3f}, {metrics.f1_upper:.3f}]"
        )

    return all_metrics


def save_metrics(metrics: list[DetectionMetrics], filename: str = "metrics.json") -> Path:
    """Save evaluation metrics to JSON."""
    EVALUATION_RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = EVALUATION_RESULTS_DIR / filename

    data = {
        "confidence_level": CONFIDENCE_LEVEL,
        "sources": [],
    }

    for m in metrics:
        data["sources"].append({
            "source_name": m.source_name,
            "confusion_matrix": {
                "tp": m.confusion.tp,
                "fp": m.confusion.fp,
                "tn": m.confusion.tn,
                "fn": m.confusion.fn,
                "total": m.confusion.total,
            },
            "precision": {
                "value": m.precision.value,
                "lower": m.precision.lower,
                "upper": m.precision.upper,
                "n": m.precision.n,
            },
            "recall": {
                "value": m.recall.value,
                "lower": m.recall.lower,
                "upper": m.recall.upper,
                "n": m.recall.n,
            },
            "f1": m.f1,
            "f1_lower": m.f1_lower,
            "f1_upper": m.f1_upper,
        })

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    logger.info(f"Metrics saved to {out_path}")
    return out_path
