"""
Detection source (c): queries the Crossref API for retraction or
correction notices linked to a DOI.

Crossref records "update-to" relationships between works (retraction,
correction, withdrawal, etc.). Since January 2023, Retraction Watch
data has been distributed through Crossref, so this source and our
ground truth share provenance. We quantify the overlap rather than
treating them as independent.
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

import requests

from src.utils.config import CROSSREF_API, CROSSREF_RPS
from src.data.manifest import DataManifest, DocumentSource

logger = logging.getLogger(__name__)

RETRACTION_UPDATE_TYPES = {"retraction", "withdrawal"}
CONCERN_UPDATE_TYPES = {"expression-of-concern"}
CORRECTION_UPDATE_TYPES = {"correction", "corrigendum", "erratum"}


@dataclass
class CrossrefCheckResult:
    """Result of Crossref retraction/update check."""
    doc_id: str
    doi: str
    flagged: bool
    has_retraction: bool = False
    has_concern: bool = False
    has_correction: bool = False
    update_types_found: list[str] = field(default_factory=list)
    update_dois: list[str] = field(default_factory=list)
    error: Optional[str] = None


class CrossrefChecker:
    """Checks Crossref for retraction and update notices linked to a DOI."""

    def __init__(self, mailto: str = "clinrag-guard@study.example"):
        self.mailto = mailto
        self._last_request_time = 0.0

    def _rate_limit(self):
        min_interval = 1.0 / CROSSREF_RPS
        elapsed = time.time() - self._last_request_time
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)
        self._last_request_time = time.time()

    def check_single(self, doc_id: str, doi: str) -> CrossrefCheckResult:
        """
        Check a single DOI for retraction/update notices in Crossref.

        Queries the Crossref works endpoint and inspects the "update-to"
        field for retraction-type relationships.
        """
        if not doi:
            return CrossrefCheckResult(
                doc_id=doc_id, doi="", flagged=False,
                error="No DOI provided",
            )

        self._rate_limit()

        url = f"{CROSSREF_API}/{doi}"
        headers = {"User-Agent": f"ClinRAG-Guard/1.0 (mailto:{self.mailto})"}

        try:
            resp = requests.get(url, headers=headers, timeout=30)

            if resp.status_code == 404:
                return CrossrefCheckResult(
                    doc_id=doc_id, doi=doi, flagged=False,
                    error="DOI not found in Crossref",
                )

            resp.raise_for_status()
            data = resp.json()
            return self._parse_response(doc_id, doi, data)

        except requests.RequestException as e:
            logger.warning(f"Crossref fetch failed for DOI {doi}: {e}")
            return CrossrefCheckResult(
                doc_id=doc_id, doi=doi, flagged=False,
                error=str(e),
            )

    def _parse_response(self, doc_id: str, doi: str, data: dict) -> CrossrefCheckResult:
        """Parse Crossref API response to find retraction/update notices."""
        message = data.get("message", {})

        update_to = message.get("update-to", [])

        has_retraction = False
        has_concern = False
        has_correction = False
        update_types = []
        update_dois = []

        for update in update_to:
            utype = update.get("type", "").lower()
            udoi = update.get("DOI", "")

            update_types.append(utype)
            if udoi:
                update_dois.append(udoi)

            if utype in RETRACTION_UPDATE_TYPES:
                has_retraction = True
            elif utype in CONCERN_UPDATE_TYPES:
                has_concern = True
            elif utype in CORRECTION_UPDATE_TYPES:
                has_correction = True

        flagged = has_retraction or has_concern

        return CrossrefCheckResult(
            doc_id=doc_id,
            doi=doi,
            flagged=flagged,
            has_retraction=has_retraction,
            has_concern=has_concern,
            has_correction=has_correction,
            update_types_found=update_types,
            update_dois=update_dois,
        )

    def check_corpus(self, manifest: DataManifest) -> list[CrossrefCheckResult]:
        """
        Check all papers in the manifest against Crossref.

        Only checks Europe PMC documents that have a DOI.
        """
        results = []
        entries = [
            e for e in manifest.entries.values()
            if e.source == DocumentSource.EUROPE_PMC and e.doi
        ]

        logger.info(f"Checking {len(entries)} papers against Crossref")

        for i, entry in enumerate(entries):
            if (i + 1) % 50 == 0:
                logger.info(f"Crossref check progress: {i + 1}/{len(entries)}")

            result = self.check_single(entry.doc_id, entry.doi)
            results.append(result)

            if result.flagged:
                logger.info(
                    f"Crossref flags {entry.doc_id} (DOI:{entry.doi}): "
                    f"retraction={result.has_retraction}, "
                    f"concern={result.has_concern}, "
                    f"types={result.update_types_found}"
                )

        flagged_count = sum(1 for r in results if r.flagged)
        logger.info(
            f"Crossref check complete: {flagged_count}/{len(results)} papers flagged"
        )

        return results
