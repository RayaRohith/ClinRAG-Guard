"""
Detection sources for Arm 2 (staleness). Checks whether drug labels
in the corpus are outdated by querying DailyMed for the current version.

Three detection approaches:
  (a) Version API check — query DailyMed history endpoint; flag if
      indexed version < latest version
  (b) Date recency check — flag if indexed label is older than a
      threshold (default 365 days) relative to current version date
  (c) Text diff check — download current label XML, compare clinical
      sections for substantive change (same logic as data collection)

These parallel the retraction detection sources in Arm 1, giving us
a comparable set of precision/recall/F1 metrics.
"""

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from src.utils.config import to_relative, resolve_path
from typing import Optional

import requests

from src.data.manifest import DataManifest, DocumentSource, GroundTruthLabel
from src.data.dailymed_versions import DailyMedVersionCollector
from src.utils.config import DAILYMED_API, DAILYMED_RPS, DAILYMED_DIR

logger = logging.getLogger(__name__)


@dataclass
class StalenessResult:
    """Result of a staleness check for one document."""
    doc_id: str
    set_id: str
    flagged: bool
    method: str
    indexed_version: int = 0
    current_version: int = 0
    indexed_date: str = ""
    current_date: str = ""
    detail: str = ""
    error: Optional[str] = None


class StalenessChecker:
    """Checks whether indexed drug labels are outdated via DailyMed API."""

    def __init__(self, pairs_manifest_path: Optional[str] = None):
        self._last_request_time = 0.0
        self._version_collector = DailyMedVersionCollector(output_dir=str(DAILYMED_DIR))
        self._history_cache: dict[str, list[dict]] = {}
        self._live_cache: dict[str, Optional[Path]] = {}

        # Load pair mappings for text_diff (older -> newer path)
        self._pair_map: dict[str, tuple[str, str]] = {}
        if pairs_manifest_path:
            self._load_pairs(pairs_manifest_path)

    def _load_pairs(self, path: str):
        """Load pair mappings from dailymed_pairs.json."""
        import json
        from pathlib import Path

        pairs_path = Path(path)
        if not pairs_path.exists():
            logger.warning(f"Pairs manifest not found: {path}")
            return

        with open(pairs_path, encoding="utf-8") as f:
            data = json.load(f)

        for pair in data.get("pairs", []):
            pair_id = pair["pair_id"]
            older_path = pair.get("older_path", "")
            newer_path = pair.get("newer_path", "")
            if older_path and newer_path:
                self._pair_map[pair_id] = (older_path, newer_path)

    def _rate_limit(self):
        min_interval = 1.0 / DAILYMED_RPS
        elapsed = time.time() - self._last_request_time
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)
        self._last_request_time = time.time()

    def _get_history(self, set_id: str) -> list[dict]:
        """Get version history for a set_id, with caching."""
        if set_id in self._history_cache:
            return self._history_cache[set_id]

        self._rate_limit()
        url = f"{DAILYMED_API}/spls/{set_id}/history.json"
        try:
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            history = data.get("data", {}).get("history", [])
            self._history_cache[set_id] = history
            return history
        except (requests.RequestException, ValueError, KeyError) as e:
            logger.warning(f"History fetch failed for {set_id}: {e}")
            self._history_cache[set_id] = []
            return []

    # ── Source (a): Version number comparison ─────────────────

    def check_version(self, doc_id: str, set_id: str, indexed_version: int) -> StalenessResult:
        """Flag if DailyMed has a higher version number than what's indexed."""
        history = self._get_history(set_id)

        if not history:
            return StalenessResult(
                doc_id=doc_id, set_id=set_id, flagged=False,
                method="version_api",
                error="No history available",
            )

        versions = []
        for entry in history:
            try:
                v = int(entry.get("spl_version", entry.get("version", 0)))
                versions.append(v)
            except (ValueError, TypeError):
                continue

        if not versions:
            return StalenessResult(
                doc_id=doc_id, set_id=set_id, flagged=False,
                method="version_api",
                error="No parseable versions in history",
            )

        latest = max(versions)
        flagged = indexed_version < latest

        return StalenessResult(
            doc_id=doc_id, set_id=set_id,
            flagged=flagged,
            method="version_api",
            indexed_version=indexed_version,
            current_version=latest,
            detail=f"indexed v{indexed_version}, latest v{latest}",
        )

    # ── Source (b): Date recency check ────────────────────────

    def check_date(
        self, doc_id: str, set_id: str,
        indexed_date: str, threshold_days: int = 365,
    ) -> StalenessResult:
        """Flag if the current version date is significantly newer than indexed."""
        history = self._get_history(set_id)

        if not history:
            return StalenessResult(
                doc_id=doc_id, set_id=set_id, flagged=False,
                method="date_recency",
                error="No history available",
            )

        dates = []
        for entry in history:
            d = entry.get("published_date", entry.get("publishedDate", ""))
            if d:
                dates.append(d)

        if not dates:
            return StalenessResult(
                doc_id=doc_id, set_id=set_id, flagged=False,
                method="date_recency",
                error="No dates in history",
            )

        latest_date_str = sorted(dates)[-1]

        try:
            indexed_dt = self._parse_date(indexed_date)
            latest_dt = self._parse_date(latest_date_str)
        except ValueError as e:
            return StalenessResult(
                doc_id=doc_id, set_id=set_id, flagged=False,
                method="date_recency",
                error=f"Date parse error: {e}",
            )

        gap_days = (latest_dt - indexed_dt).days
        flagged = gap_days > threshold_days

        return StalenessResult(
            doc_id=doc_id, set_id=set_id,
            flagged=flagged,
            method="date_recency",
            indexed_date=indexed_date,
            current_date=latest_date_str,
            detail=f"{gap_days} days between indexed and latest",
        )

    # ── Source (c): Text diff against current version ─────────

    def _get_live_label(self, set_id: str) -> Optional[Path]:
        """
        Download the label DailyMed currently serves for this set_id, once per
        run. Saved to data/dailymed/live_snapshot/ so every comparison can be
        audited later.
        """
        if set_id in self._live_cache:
            return self._live_cache[set_id]
        snap_dir = DAILYMED_DIR / "live_snapshot"
        snap_dir.mkdir(parents=True, exist_ok=True)
        fetcher = DailyMedVersionCollector(output_dir=str(snap_dir))
        path = fetcher.download_current_xml(set_id, f"{set_id}_live")
        self._live_cache[set_id] = path
        return path

    def check_text_diff(self, doc_id: str, set_id: str, indexed_xml_path: str) -> StalenessResult:
        """
        Compare the indexed label with the label DailyMed serves today.

        This mirrors what a real ingestion-time check can do: it knows only the
        document it indexed and its set ID. It never reads the doc_id, file name
        or ground-truth label to decide.
        """
        indexed = resolve_path(indexed_xml_path)
        if not indexed.exists():
            return StalenessResult(
                doc_id=doc_id, set_id=set_id, flagged=False,
                method="text_diff",
                error=f"Indexed file not found: {indexed}",
            )

        live = self._get_live_label(set_id)
        if live is None:
            return StalenessResult(
                doc_id=doc_id, set_id=set_id, flagged=False,
                method="text_diff",
                error="Live label unavailable",
            )

        changed, summary = self._version_collector.compare_versions(
            self._version_collector.extract_sections(indexed),
            self._version_collector.extract_sections(live),
        )
        live_ver, live_date = self._version_collector.read_spl_metadata(live)

        return StalenessResult(
            doc_id=doc_id, set_id=set_id,
            flagged=len(changed) > 0,
            method="text_diff",
            current_version=live_ver,
            current_date=live_date,
            detail=f"vs live v{live_ver} ({live_date}): {summary}",
        )

    # ── Corpus-level runners ──────────────────────────────────

    def check_corpus_version(self, manifest: DataManifest) -> list[StalenessResult]:
        """Run version check on all DailyMed documents."""
        entries = [
            e for e in manifest.entries.values()
            if e.source == DocumentSource.DAILYMED
        ]
        logger.info(f"Running version API check on {len(entries)} drug labels")

        results = []
        for i, entry in enumerate(entries):
            if (i + 1) % 25 == 0:
                flagged_so_far = sum(1 for r in results if r.flagged)
                logger.info(f"  Version check: {i+1}/{len(entries)}, {flagged_so_far} flagged")

            result = self.check_version(
                entry.doc_id,
                entry.set_id or "",
                entry.spl_version or 0,
            )
            results.append(result)

        flagged = sum(1 for r in results if r.flagged)
        logger.info(f"Version API check: {flagged}/{len(results)} flagged as outdated")
        return results

    def check_corpus_date(self, manifest: DataManifest) -> list[StalenessResult]:
        """Run date recency check on all DailyMed documents."""
        entries = [
            e for e in manifest.entries.values()
            if e.source == DocumentSource.DAILYMED
        ]
        logger.info(f"Running date recency check on {len(entries)} drug labels")

        results = []
        for i, entry in enumerate(entries):
            if (i + 1) % 25 == 0:
                flagged_so_far = sum(1 for r in results if r.flagged)
                logger.info(f"  Date check: {i+1}/{len(entries)}, {flagged_so_far} flagged")

            result = self.check_date(
                entry.doc_id,
                entry.set_id or "",
                entry.publication_date,
            )
            results.append(result)

        flagged = sum(1 for r in results if r.flagged)
        logger.info(f"Date recency check: {flagged}/{len(results)} flagged as outdated")
        return results

    def check_corpus_text_diff(self, manifest: DataManifest) -> list[StalenessResult]:
        """Run text diff check on all DailyMed documents."""
        entries = [
            e for e in manifest.entries.values()
            if e.source == DocumentSource.DAILYMED
        ]
        logger.info(f"Running text diff check on {len(entries)} drug labels")

        results = []
        for i, entry in enumerate(entries):
            if (i + 1) % 10 == 0:
                flagged_so_far = sum(1 for r in results if r.flagged)
                logger.info(f"  Text diff: {i+1}/{len(entries)}, {flagged_so_far} flagged")

            result = self.check_text_diff(
                entry.doc_id,
                entry.set_id or "",
                entry.file_path,
            )
            results.append(result)

        flagged = sum(1 for r in results if r.flagged)
        logger.info(f"Text diff check: {flagged}/{len(results)} flagged as outdated")
        return results

    # ── Utilities ─────────────────────────────────────────────

    @staticmethod
    def _parse_date(date_str: str) -> datetime:
        for fmt in ("%Y-%m-%d", "%b %d, %Y", "%B %d, %Y", "%m/%d/%Y", "%Y%m%d"):
            try:
                return datetime.strptime(date_str.strip(), fmt)
            except ValueError:
                continue
        raise ValueError(f"Cannot parse date: {date_str}")
