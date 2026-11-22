"""
Detection source (d): combines text analysis, PubMed, and Crossref
results into union (any source flags it) and intersection (all agree).

Union maximises recall at the cost of precision; intersection trades
recall for higher confidence. Comparing the two shows how much the
individual sources overlap in practice.
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class CombinedResult:
    """Combined detection result for a single document."""
    doc_id: str
    union_flagged: bool
    intersection_flagged: bool
    sources_flagging: list[str] = field(default_factory=list)
    n_sources_flagging: int = 0
    text_flagged: bool = False
    pubmed_flagged: bool = False
    crossref_flagged: bool = False


def combine_results(
    text_results: list,
    pubmed_results: list,
    crossref_results: list,
) -> list[CombinedResult]:
    """
    Combine detection results from all three sources.

    Builds a lookup by doc_id and computes union/intersection
    for each document that appears in at least one source.
    """
    text_map = {r.doc_id: r.flagged for r in text_results}
    pubmed_map = {r.doc_id: r.flagged for r in pubmed_results}
    crossref_map = {r.doc_id: r.flagged for r in crossref_results}

    all_doc_ids = set(text_map) | set(pubmed_map) | set(crossref_map)

    results = []
    for doc_id in sorted(all_doc_ids):
        t = text_map.get(doc_id, False)
        p = pubmed_map.get(doc_id, False)
        c = crossref_map.get(doc_id, False)

        sources = []
        if t:
            sources.append("text_analysis")
        if p:
            sources.append("pubmed")
        if c:
            sources.append("crossref")

        # Union: any source flags it
        union = t or p or c

        # Intersection: all three must flag it (only if all three checked it)
        all_checked = doc_id in text_map and doc_id in pubmed_map and doc_id in crossref_map
        intersection = t and p and c if all_checked else False

        results.append(CombinedResult(
            doc_id=doc_id,
            union_flagged=union,
            intersection_flagged=intersection,
            sources_flagging=sources,
            n_sources_flagging=len(sources),
            text_flagged=t,
            pubmed_flagged=p,
            crossref_flagged=c,
        ))

    union_count = sum(1 for r in results if r.union_flagged)
    intersection_count = sum(1 for r in results if r.intersection_flagged)
    logger.info(
        f"Combined detection: {union_count}/{len(results)} union-flagged, "
        f"{intersection_count}/{len(results)} intersection-flagged"
    )

    return results
