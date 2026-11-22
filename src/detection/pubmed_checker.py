"""
Detection source (b): queries PubMed's Entrez API for retraction status.

PubMed marks retracted papers with the publication type "Retracted Publication."
Note that these markings originate from publisher notices — the same upstream
source that feeds Retraction Watch. So this detection source shares provenance
with our ground truth and is not an independent probe. We report this overlap
rather than pretending the two are unrelated.
"""

import logging
import time
from dataclasses import dataclass
from typing import Optional
from xml.etree import ElementTree as ET

import requests

from src.utils.config import PUBMED_ENTREZ_BASE, PUBMED_RPS
from src.data.manifest import DataManifest, ManifestEntry, DocumentSource, GroundTruthLabel

logger = logging.getLogger(__name__)


@dataclass
class PubMedCheckResult:
    """Result of PubMed retraction status check."""
    doc_id: str
    pmid: str
    flagged: bool
    is_retracted_publication: bool = False
    has_retraction_notice: bool = False
    retraction_notice_pmid: Optional[str] = None
    publication_types: list[str] = None
    error: Optional[str] = None

    def __post_init__(self):
        if self.publication_types is None:
            self.publication_types = []


class PubMedChecker:
    """Checks PubMed for retraction status via the Entrez API."""

    def __init__(self, email: str = "clinrag-guard@study.example"):
        self.email = email
        self._last_request_time = 0.0

    def _rate_limit(self):
        min_interval = 1.0 / PUBMED_RPS
        elapsed = time.time() - self._last_request_time
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)
        self._last_request_time = time.time()

    def check_single(self, doc_id: str, pmid: str) -> PubMedCheckResult:
        """
        Check a single PMID for retraction status.

        Queries PubMed efetch to get the full record, then inspects:
        1. PublicationType for "Retracted Publication"
        2. CommentsCorrectionsList for retraction notices
        """
        if not pmid:
            return PubMedCheckResult(
                doc_id=doc_id, pmid="", flagged=False,
                error="No PMID provided",
            )

        self._rate_limit()

        url = f"{PUBMED_ENTREZ_BASE}/efetch.fcgi"
        params = {
            "db": "pubmed",
            "id": pmid,
            "rettype": "xml",
            "retmode": "xml",
            "email": self.email,
        }

        try:
            resp = requests.get(url, params=params, timeout=30)
            resp.raise_for_status()
            return self._parse_pubmed_xml(doc_id, pmid, resp.text)

        except requests.RequestException as e:
            logger.warning(f"PubMed fetch failed for PMID {pmid}: {e}")
            return PubMedCheckResult(
                doc_id=doc_id, pmid=pmid, flagged=False,
                error=str(e),
            )

    def _parse_pubmed_xml(self, doc_id: str, pmid: str, xml_text: str) -> PubMedCheckResult:
        """Parse PubMed XML to extract retraction status."""
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as e:
            return PubMedCheckResult(
                doc_id=doc_id, pmid=pmid, flagged=False,
                error=f"XML parse error: {e}",
            )

        article = root.find(".//PubmedArticle")
        if article is None:
            return PubMedCheckResult(
                doc_id=doc_id, pmid=pmid, flagged=False,
                error="No PubmedArticle element found",
            )

        pub_types = []
        for pt in article.findall(".//PublicationType"):
            if pt.text:
                pub_types.append(pt.text.strip())

        is_retracted = "Retracted Publication" in pub_types

        retraction_notice_pmid = None
        has_retraction_notice = False
        for cc in article.findall(".//CommentsCorrections"):
            ref_type = cc.get("RefType", "")
            if ref_type == "RetractionIn":
                has_retraction_notice = True
                pmid_elem = cc.find("PMID")
                if pmid_elem is not None and pmid_elem.text:
                    retraction_notice_pmid = pmid_elem.text.strip()
                break

        flagged = is_retracted or has_retraction_notice

        return PubMedCheckResult(
            doc_id=doc_id,
            pmid=pmid,
            flagged=flagged,
            is_retracted_publication=is_retracted,
            has_retraction_notice=has_retraction_notice,
            retraction_notice_pmid=retraction_notice_pmid,
            publication_types=pub_types,
        )

    def check_corpus(self, manifest: DataManifest) -> list[PubMedCheckResult]:
        """
        Check all Europe PMC documents in the manifest against PubMed.

        Only checks papers (not drug labels — DailyMed doesn't have PMIDs
        in PubMed's retraction system).
        """
        results = []
        entries = [
            e for e in manifest.entries.values()
            if e.source == DocumentSource.EUROPE_PMC and e.pmid
        ]

        logger.info(f"Checking {len(entries)} papers against PubMed")

        for i, entry in enumerate(entries):
            if (i + 1) % 50 == 0:
                logger.info(f"PubMed check progress: {i + 1}/{len(entries)}")

            result = self.check_single(entry.doc_id, entry.pmid)
            results.append(result)

            if result.flagged:
                logger.info(
                    f"PubMed flags {entry.doc_id} (PMID:{entry.pmid}): "
                    f"retracted={result.is_retracted_publication}, "
                    f"notice={result.has_retraction_notice}"
                )

        flagged_count = sum(1 for r in results if r.flagged)
        logger.info(
            f"PubMed check complete: {flagged_count}/{len(results)} papers flagged"
        )

        return results
