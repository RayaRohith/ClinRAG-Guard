"""
Detection source (e): naive baseline. Looks up each paper by DOI or
title in PubMed's retracted-publication filter — the simplest possible
check, no text analysis, no Crossref integration. Acts as the floor
benchmark: if the other methods can't beat this, they aren't adding value.
"""

import logging
import time
from dataclasses import dataclass
from typing import Optional

import requests

from src.utils.config import PUBMED_ENTREZ_BASE, PUBMED_RPS
from src.data.manifest import DataManifest, DocumentSource

logger = logging.getLogger(__name__)


@dataclass
class NaiveBaselineResult:
    """Result of naive PubMed retraction lookup."""
    doc_id: str
    flagged: bool
    method: str = ""  # "doi", "title", or "none"
    match_count: int = 0
    error: Optional[str] = None


class NaiveBaseline:
    """Floor benchmark: simple PubMed search for retracted publications."""

    def __init__(self, email: str = "clinrag-guard@study.example"):
        self.email = email
        self._last_request_time = 0.0

    def _rate_limit(self):
        min_interval = 1.0 / PUBMED_RPS
        elapsed = time.time() - self._last_request_time
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)
        self._last_request_time = time.time()

    def _search_pubmed_retracted(self, query: str) -> tuple[bool, int]:
        """
        Search PubMed for retracted publications matching a query.
        Returns (found, count).
        """
        self._rate_limit()

        url = f"{PUBMED_ENTREZ_BASE}/esearch.fcgi"
        params = {
            "db": "pubmed",
            "term": f'{query} AND "Retracted Publication"[pt]',
            "rettype": "count",
            "retmode": "json",
            "email": self.email,
        }

        try:
            resp = requests.get(url, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()

            count = int(data.get("esearchresult", {}).get("count", 0))
            return count > 0, count

        except (requests.RequestException, ValueError, KeyError) as e:
            logger.warning(f"PubMed search failed: {e}")
            return False, 0

    def check_single(
        self, doc_id: str, doi: str = "", title: str = ""
    ) -> NaiveBaselineResult:
        """
        Check a single paper by DOI first, then by title if DOI fails.
        """
        if doi:
            found, count = self._search_pubmed_retracted(doi)
            if found:
                return NaiveBaselineResult(
                    doc_id=doc_id, flagged=True,
                    method="doi", match_count=count,
                )

        if title:
            safe_title = title[:200]
            found, count = self._search_pubmed_retracted(f'"{safe_title}"')
            if found:
                return NaiveBaselineResult(
                    doc_id=doc_id, flagged=True,
                    method="title", match_count=count,
                )

        return NaiveBaselineResult(doc_id=doc_id, flagged=False, method="none")

    def check_corpus(self, manifest: DataManifest) -> list[NaiveBaselineResult]:
        """
        Run naive baseline on all Europe PMC papers in the manifest.
        """
        results = []
        entries = [
            e for e in manifest.entries.values()
            if e.source == DocumentSource.EUROPE_PMC
        ]

        logger.info(f"Running naive baseline on {len(entries)} papers")

        for i, entry in enumerate(entries):
            if (i + 1) % 50 == 0:
                logger.info(f"Naive baseline progress: {i + 1}/{len(entries)}")

            result = self.check_single(entry.doc_id, entry.doi or "", entry.title or "")
            results.append(result)

        flagged_count = sum(1 for r in results if r.flagged)
        logger.info(
            f"Naive baseline complete: {flagged_count}/{len(results)} papers flagged"
        )

        return results
