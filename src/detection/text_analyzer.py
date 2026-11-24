"""
Detection source (a): pattern-based scan of document text for retraction
and staleness signals.

This is the only source genuinely independent of the ground truth, since
it looks at the document text itself rather than querying external databases.
Expect low recall on pre-retraction versions — that is by design. The
documents were indexed as originally published, so they mostly won't contain
retraction language. Anything this source picks up (expressions of concern,
editorial notices) is information the other sources can't provide.
"""

import re
import logging
from dataclasses import dataclass, field
from pathlib import Path

from src.utils.config import to_relative, resolve_path

from src.data.manifest import DataManifest, ManifestEntry, DocumentSource

logger = logging.getLogger(__name__)


@dataclass
class TextAnalysisResult:
    """Result of text-based retraction/staleness signal detection."""
    doc_id: str
    flagged: bool
    signals_found: list[str] = field(default_factory=list)
    matched_patterns: list[str] = field(default_factory=list)
    confidence: str = "none"  # none, low, medium, high


# Patterns ordered roughly by specificity / signal strength
RETRACTION_PATTERNS = [
    # High confidence: explicit retraction language
    (r"\bretracted\b", "high", "retracted"),
    (r"\bretraction\b", "high", "retraction"),
    (r"\bthis\s+article\s+has\s+been\s+retracted\b", "high", "explicit_retraction_notice"),
    (r"\bthis\s+paper\s+has\s+been\s+retracted\b", "high", "explicit_retraction_notice"),
    (r"\bretraction\s+notice\b", "high", "retraction_notice"),
    (r"\bretracted\s+article\b", "high", "retracted_article"),
    (r"\bretracted\s+paper\b", "high", "retracted_paper"),
    (r"\bretracted\s+publication\b", "high", "retracted_publication"),

    # Medium confidence: related editorial actions
    (r"\bexpression\s+of\s+concern\b", "medium", "expression_of_concern"),
    (r"\berratum\b", "medium", "erratum"),
    (r"\bcorrigendum\b", "medium", "corrigendum"),
    (r"\bcorrection\s+notice\b", "medium", "correction_notice"),
    (r"\bwithdraw(?:n|al)\b", "medium", "withdrawal"),
    (r"\beditor(?:ial)?\s+concern\b", "medium", "editorial_concern"),

    # Low confidence: may appear in legitimate papers discussing retractions
    (r"\bdata\s+fabricat(?:ion|ed)\b", "low", "data_fabrication"),
    (r"\bdata\s+falsificat(?:ion|ed)\b", "low", "data_falsification"),
    (r"\bscientific\s+misconduct\b", "low", "scientific_misconduct"),
    (r"\bplagiari(?:sm|zed|sed)\b", "low", "plagiarism"),
    (r"\bduplicate\s+publication\b", "low", "duplicate_publication"),
]

STALENESS_PATTERNS = [
    (r"\bsuperseded\b", "medium", "superseded"),
    (r"\bthis\s+label\s+has\s+been\s+updated\b", "high", "label_updated_notice"),
    (r"\bobsolete\b", "medium", "obsolete"),
    (r"\bno\s+longer\s+current\b", "high", "no_longer_current"),
    (r"\brevised\s+label(?:ing)?\b", "medium", "revised_labeling"),
    (r"\bprevious\s+version\b", "medium", "previous_version"),
]


CONFIDENCE_RANK = {"none": 0, "low": 1, "medium": 2, "high": 3}


class TextAnalyzer:
    """Scans document text for retraction and staleness signals."""

    def __init__(self):
        self._compiled_retraction = [
            (re.compile(pattern, re.IGNORECASE), conf, name)
            for pattern, conf, name in RETRACTION_PATTERNS
        ]
        self._compiled_staleness = [
            (re.compile(pattern, re.IGNORECASE), conf, name)
            for pattern, conf, name in STALENESS_PATTERNS
        ]

    def analyze_document(self, doc_id: str, text: str, source: DocumentSource) -> TextAnalysisResult:
        """
        Scan a single document's text for retraction/staleness signals.

        Uses retraction patterns for Europe PMC papers (Arm 1) and
        staleness patterns for DailyMed labels (Arm 2).
        """
        if source == DocumentSource.EUROPE_PMC:
            patterns = self._compiled_retraction
        elif source == DocumentSource.DAILYMED:
            patterns = self._compiled_staleness
        else:
            patterns = self._compiled_retraction + self._compiled_staleness

        signals = []
        matched = []
        max_confidence = "none"

        for regex, confidence, name in patterns:
            if regex.search(text):
                signals.append(f"{name} ({confidence})")
                matched.append(name)
                if CONFIDENCE_RANK[confidence] > CONFIDENCE_RANK[max_confidence]:
                    max_confidence = confidence

        flagged = len(signals) > 0

        return TextAnalysisResult(
            doc_id=doc_id,
            flagged=flagged,
            signals_found=signals,
            matched_patterns=matched,
            confidence=max_confidence,
        )

    def analyze_corpus(self, manifest: DataManifest) -> list[TextAnalysisResult]:
        """
        Run text analysis on all documents in the manifest.

        Reads each document file, extracts text, and scans for signals.
        """
        from src.indexing.pipeline import extract_text_from_xml

        results = []
        for doc_id, entry in manifest.entries.items():
            path = resolve_path(entry.file_path)
            if not path.exists():
                logger.warning(f"File not found: {doc_id} -> {path}")
                results.append(TextAnalysisResult(doc_id=doc_id, flagged=False))
                continue

            text = extract_text_from_xml(path)
            if not text:
                results.append(TextAnalysisResult(doc_id=doc_id, flagged=False))
                continue

            result = self.analyze_document(doc_id, text, entry.source)
            results.append(result)

            if result.flagged:
                logger.info(
                    f"Text signals in {doc_id}: {result.signals_found} "
                    f"(confidence: {result.confidence})"
                )

        flagged_count = sum(1 for r in results if r.flagged)
        logger.info(
            f"Text analysis complete: {flagged_count}/{len(results)} documents flagged"
        )

        return results
