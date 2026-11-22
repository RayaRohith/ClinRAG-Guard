"""
Categorises every false negative with a documented cause. Recall numbers
tell you what was missed; this module tells you why.

Retraction FN categories: no_crossref_record, no_pubmed_update,
no_text_signal, api_error, no_metadata.
Staleness FN categories: no_text_signal, subtle_change, api_error.
"""

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from src.utils.config import EVALUATION_RESULTS_DIR

logger = logging.getLogger(__name__)


@dataclass
class FalseNegativeEntry:
    """One false negative with its cause analysis."""
    doc_id: str
    arm: int
    sources_that_missed: list[str] = field(default_factory=list)
    sources_that_caught: list[str] = field(default_factory=list)
    cause_category: str = "unknown"
    cause_detail: str = ""
    has_doi: bool = False
    has_pmid: bool = False
    had_api_error: bool = False


@dataclass
class ErrorAnalysisResult:
    """Complete error analysis for one study arm."""
    arm: int
    total_positives: int
    total_false_negatives: int
    entries: list[FalseNegativeEntry] = field(default_factory=list)

    # Aggregate: {cause_category: count}
    cause_distribution: dict[str, int] = field(default_factory=dict)

    # Per-source FN breakdown
    per_source_fn_causes: dict[str, dict[str, int]] = field(default_factory=dict)


def analyze_false_negatives(
    detection_results: dict[str, dict[str, bool]],
    ground_truth: dict[str, bool],
    source_details: dict[str, dict[str, object]],
    metadata: dict[str, dict],
    arm: int = 1,
) -> ErrorAnalysisResult:
    """
    Categorise every false negative.

    Args:
        detection_results: {source_name: {doc_id: flagged}}.
        ground_truth: {doc_id: is_positive}.
        source_details: {source_name: {doc_id: result_object}} for
            inspecting error fields and metadata availability.
        metadata: {doc_id: {"doi": ..., "pmid": ..., ...}} from manifest.
        arm: Study arm.

    Returns:
        ErrorAnalysisResult with categorised false negatives.
    """
    source_names = sorted(detection_results.keys())
    positive_ids = {did for did, label in ground_truth.items() if label}

    result = ErrorAnalysisResult(
        arm=arm,
        total_positives=len(positive_ids),
        total_false_negatives=0,
    )

    for doc_id in sorted(positive_ids):
        missed_by = []
        caught_by = []

        for source in source_names:
            flagged = detection_results[source].get(doc_id, False)
            if flagged:
                caught_by.append(source)
            else:
                missed_by.append(source)

        if not missed_by:
            continue

        meta = metadata.get(doc_id, {})
        has_doi = bool(meta.get("doi"))
        has_pmid = bool(meta.get("pmid"))

        cause = _categorise_cause(
            doc_id, missed_by, source_details, has_doi, has_pmid, arm,
        )

        entry = FalseNegativeEntry(
            doc_id=doc_id,
            arm=arm,
            sources_that_missed=missed_by,
            sources_that_caught=caught_by,
            cause_category=cause[0],
            cause_detail=cause[1],
            has_doi=has_doi,
            has_pmid=has_pmid,
            had_api_error=cause[0] == "api_error",
        )

        result.entries.append(entry)
        result.total_false_negatives += 1

    # Aggregate cause distribution
    for entry in result.entries:
        result.cause_distribution[entry.cause_category] = (
            result.cause_distribution.get(entry.cause_category, 0) + 1
        )

    # Per-source FN cause breakdown
    for source in source_names:
        source_causes: dict[str, int] = {}
        for entry in result.entries:
            if source in entry.sources_that_missed:
                source_causes[entry.cause_category] = (
                    source_causes.get(entry.cause_category, 0) + 1
                )
        result.per_source_fn_causes[source] = source_causes

    logger.info(
        f"Error analysis (Arm {arm}): {result.total_false_negatives} FNs across "
        f"{len(result.cause_distribution)} cause categories"
    )

    return result


def _categorise_cause(
    doc_id: str,
    missed_by: list[str],
    source_details: dict[str, dict[str, object]],
    has_doi: bool,
    has_pmid: bool,
    arm: int,
) -> tuple[str, str]:
    """
    Determine the most likely cause category for a false negative.

    Returns (category, detail_string).
    """
    had_error = False
    for source in missed_by:
        detail = source_details.get(source, {}).get(doc_id)
        if detail and hasattr(detail, "error") and detail.error:
            had_error = True
            return ("api_error", f"{source}: {detail.error}")

    if arm == 1:
        if "crossref" in " ".join(missed_by).lower():
            if not has_doi:
                return ("no_metadata", "No DOI available for Crossref check")
        if "pubmed" in " ".join(missed_by).lower():
            if not has_pmid:
                return ("no_metadata", "No PMID available for PubMed check")

        only_text_missed = all("text" in s.lower() for s in missed_by)
        if only_text_missed:
            return ("no_text_signal", "Pre-retraction text has no retraction language")

        only_api_missed = all(
            "pubmed" in s.lower() or "crossref" in s.lower() or "naive" in s.lower()
            for s in missed_by
        )
        if only_api_missed:
            if "crossref" in " ".join(missed_by).lower():
                return ("no_crossref_record", "No retraction notice in Crossref")
            if "pubmed" in " ".join(missed_by).lower():
                return ("no_pubmed_update", "PubMed not updated with retraction status")

        return ("multiple_gaps", f"Missed by: {', '.join(missed_by)}")

    elif arm == 2:
        if all("text" in s.lower() for s in missed_by):
            return ("no_text_signal", "Older label has no staleness indicators")
        return ("subtle_change", "Change not detected by pattern matching")

    return ("unknown", f"Missed by: {', '.join(missed_by)}")


def save_error_analysis(
    analysis: ErrorAnalysisResult, filename: str = "error_analysis.json"
) -> Path:
    """Save error analysis to JSON."""
    EVALUATION_RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = EVALUATION_RESULTS_DIR / filename

    data = {
        "arm": analysis.arm,
        "total_positives": analysis.total_positives,
        "total_false_negatives": analysis.total_false_negatives,
        "cause_distribution": analysis.cause_distribution,
        "per_source_fn_causes": analysis.per_source_fn_causes,
        "entries": [
            {
                "doc_id": e.doc_id,
                "sources_that_missed": e.sources_that_missed,
                "sources_that_caught": e.sources_that_caught,
                "cause_category": e.cause_category,
                "cause_detail": e.cause_detail,
                "has_doi": e.has_doi,
                "has_pmid": e.has_pmid,
            }
            for e in analysis.entries
        ],
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    logger.info(f"Error analysis saved to {out_path}")
    return out_path


def format_error_summary(analysis: ErrorAnalysisResult) -> str:
    """Format error analysis as human-readable summary."""
    lines = [
        f"=== Error Analysis (Arm {analysis.arm}) ===",
        f"Total positives: {analysis.total_positives}",
        f"Total false negatives: {analysis.total_false_negatives}",
        "",
        "Cause distribution:",
    ]

    for cause, count in sorted(
        analysis.cause_distribution.items(), key=lambda x: -x[1]
    ):
        pct = 100 * count / max(analysis.total_false_negatives, 1)
        lines.append(f"  {cause}: {count} ({pct:.1f}%)")

    lines.append("")
    lines.append("Per-source FN breakdown:")
    for source, causes in sorted(analysis.per_source_fn_causes.items()):
        total_fn = sum(causes.values())
        lines.append(f"  {source} ({total_fn} FNs):")
        for cause, count in sorted(causes.items(), key=lambda x: -x[1]):
            lines.append(f"    {cause}: {count}")

    return "\n".join(lines)
