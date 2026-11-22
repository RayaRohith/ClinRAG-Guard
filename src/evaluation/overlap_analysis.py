"""
Source overlap analysis — the "Venn diagram" part of the evaluation.

For each document, records which combination of sources flagged it.
The interesting numbers: how many documents each source catches uniquely,
pairwise and 3-way overlap between sources, and the coverage gap
(positives that no source flagged at all).
"""

import json
import logging
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from src.utils.config import EVALUATION_RESULTS_DIR

logger = logging.getLogger(__name__)


@dataclass
class OverlapResult:
    """Complete overlap analysis for one study arm."""
    arm: int
    total_documents: int
    total_positives: int

    # Per-source counts
    source_counts: dict[str, int] = field(default_factory=dict)

    # Pairwise overlap: {("a", "b"): count}
    pairwise_overlap: dict[tuple[str, str], int] = field(default_factory=dict)

    # 3-way: flagged by all sources
    all_sources_overlap: int = 0

    # By number of sources flagging
    by_n_sources: dict[int, int] = field(default_factory=dict)

    # Documents flagged by no source (among positives)
    unflagged_positives: list[str] = field(default_factory=list)

    # Documents flagged by exactly one source
    unique_flags: dict[str, list[str]] = field(default_factory=dict)


def compute_overlap(
    detection_results: dict[str, dict[str, bool]],
    ground_truth: dict[str, bool],
    arm: int = 1,
) -> OverlapResult:
    """
    Compute source overlap analysis.

    Args:
        detection_results: {source_name: {doc_id: flagged}} for each source.
        ground_truth: {doc_id: is_positive} from the manifest.
        arm: Study arm (1 or 2).

    Returns:
        OverlapResult with all overlap statistics.
    """
    source_names = sorted(detection_results.keys())
    positive_ids = {did for did, label in ground_truth.items() if label}

    result = OverlapResult(
        arm=arm,
        total_documents=len(ground_truth),
        total_positives=len(positive_ids),
    )

    # Build per-document flag sets (which sources flagged each doc)
    doc_flagged_by: dict[str, set[str]] = {did: set() for did in ground_truth}

    for source_name, predictions in detection_results.items():
        count = 0
        for doc_id in ground_truth:
            if predictions.get(doc_id, False):
                doc_flagged_by[doc_id].add(source_name)
                count += 1
        result.source_counts[source_name] = count

    # Count by number of sources flagging
    n_sources_counter = Counter()
    for doc_id, sources in doc_flagged_by.items():
        n_sources_counter[len(sources)] += 1
    result.by_n_sources = dict(sorted(n_sources_counter.items()))

    # Pairwise overlap
    for i, s1 in enumerate(source_names):
        for s2 in source_names[i + 1:]:
            overlap = sum(
                1 for did in ground_truth
                if s1 in doc_flagged_by[did] and s2 in doc_flagged_by[did]
            )
            result.pairwise_overlap[(s1, s2)] = overlap

    # 3-way overlap (all sources flag)
    if len(source_names) >= 3:
        result.all_sources_overlap = sum(
            1 for did in ground_truth
            if len(doc_flagged_by[did]) == len(source_names)
        )

    # Unflagged positives (ground truth positive, no source flags)
    result.unflagged_positives = sorted(
        did for did in positive_ids
        if len(doc_flagged_by[did]) == 0
    )

    # Unique flags (flagged by exactly one source, among positives)
    for source_name in source_names:
        unique = [
            did for did in positive_ids
            if doc_flagged_by[did] == {source_name}
        ]
        result.unique_flags[source_name] = sorted(unique)

    logger.info(
        f"Overlap analysis (Arm {arm}): "
        f"{len(result.unflagged_positives)}/{result.total_positives} positives unflagged"
    )

    return result


def save_overlap(overlap: OverlapResult, filename: str = "overlap.json") -> Path:
    """Save overlap analysis to JSON."""
    EVALUATION_RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = EVALUATION_RESULTS_DIR / filename

    data = {
        "arm": overlap.arm,
        "total_documents": overlap.total_documents,
        "total_positives": overlap.total_positives,
        "source_counts": overlap.source_counts,
        "pairwise_overlap": {
            f"{k[0]}+{k[1]}": v
            for k, v in overlap.pairwise_overlap.items()
        },
        "all_sources_overlap": overlap.all_sources_overlap,
        "by_n_sources": overlap.by_n_sources,
        "unflagged_positives_count": len(overlap.unflagged_positives),
        "unflagged_positives": overlap.unflagged_positives,
        "unique_flags": {
            source: {"count": len(docs), "doc_ids": docs}
            for source, docs in overlap.unique_flags.items()
        },
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    logger.info(f"Overlap analysis saved to {out_path}")
    return out_path


def format_overlap_summary(overlap: OverlapResult) -> str:
    """Format overlap analysis as a human-readable summary."""
    lines = [
        f"=== Source Overlap Analysis (Arm {overlap.arm}) ===",
        f"Total documents: {overlap.total_documents}",
        f"Total positives: {overlap.total_positives}",
        "",
        "Per-source flag counts:",
    ]

    for source, count in sorted(overlap.source_counts.items()):
        lines.append(f"  {source}: {count}")

    lines.append("")
    lines.append("Pairwise overlap:")
    for (s1, s2), count in sorted(overlap.pairwise_overlap.items()):
        lines.append(f"  {s1} ∩ {s2}: {count}")

    if overlap.all_sources_overlap > 0:
        lines.append(f"\nAll sources agree: {overlap.all_sources_overlap}")

    lines.append(f"\nBy number of sources flagging:")
    for n, count in sorted(overlap.by_n_sources.items()):
        lines.append(f"  {n} sources: {count} documents")

    lines.append(
        f"\nCoverage gap: {len(overlap.unflagged_positives)}/{overlap.total_positives} "
        f"positives missed by all sources"
    )

    for source, docs in overlap.unique_flags.items():
        if docs:
            lines.append(f"  Unique to {source}: {len(docs)} documents")

    return "\n".join(lines)
