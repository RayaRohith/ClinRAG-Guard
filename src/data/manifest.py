"""
Provenance manifest for every document in the corpus. Tracks IDs, source,
version date, SHA-256 hash, and ground-truth label. A replicator can verify
they have the exact same corpus by checking hashes against this file.
"""

import hashlib
import json
import logging
from dataclasses import dataclass, asdict, field
from datetime import datetime
from enum import Enum
from pathlib import Path

from src.utils.config import to_relative, resolve_path
from typing import Optional

from src.utils.config import MANIFEST_DIR

logger = logging.getLogger(__name__)


class DocumentSource(Enum):
    EUROPE_PMC = "europe_pmc"
    DAILYMED = "dailymed"


class GroundTruthLabel(Enum):
    RETRACTED = "retracted"           # confirmed retracted paper
    CONTROL = "control"               # matched non-retracted control
    OUTDATED = "outdated"             # superseded drug label version
    CURRENT = "current"               # current drug label version


@dataclass
class ManifestEntry:
    """Provenance record for a single document."""
    doc_id: str
    source: DocumentSource
    ground_truth: GroundTruthLabel
    file_path: str
    file_hash: str                    # SHA-256
    title: str = ""
    pmid: Optional[str] = None
    doi: Optional[str] = None
    set_id: Optional[str] = None      # DailyMed SPL set ID
    spl_version: Optional[int] = None
    publication_date: str = ""
    collection_date: str = ""
    matched_to: Optional[str] = None  # for controls: which retracted paper
    extra: dict = field(default_factory=dict)


class DataManifest:
    """Tracks all documents in the study with their provenance metadata."""

    def __init__(self):
        self.entries: dict[str, ManifestEntry] = {}
        self.created_at = datetime.now().isoformat()
        self.last_modified = self.created_at

    def add_entry(self, entry: ManifestEntry):
        """Add or update a document entry."""
        if not entry.collection_date:
            entry.collection_date = datetime.now().isoformat()
        self.entries[entry.doc_id] = entry
        self.last_modified = datetime.now().isoformat()

    def add_retraction_records(self, retracted: list, controls: list):
        """
        Bulk-add from retraction_sampler output.
        Accepts RetractionRecord and ControlRecord dataclass instances.
        """
        for rec in retracted:
            if not rec.has_full_text:
                continue
            self.add_entry(ManifestEntry(
                doc_id=rec.record_id,
                source=DocumentSource.EUROPE_PMC,
                ground_truth=GroundTruthLabel.RETRACTED,
                file_path=rec.full_text_path or "",
                file_hash=rec.full_text_hash or "",
                title=rec.title,
                pmid=rec.pmid,
                doi=rec.doi,
                publication_date=str(rec.publication_year),
                extra={"retraction_date": rec.retraction_date},
            ))

        for rec in controls:
            if not rec.has_full_text:
                continue
            self.add_entry(ManifestEntry(
                doc_id=rec.record_id,
                source=DocumentSource.EUROPE_PMC,
                ground_truth=GroundTruthLabel.CONTROL,
                file_path=rec.full_text_path or "",
                file_hash=rec.full_text_hash or "",
                title=rec.title,
                pmid=rec.pmid,
                doi=rec.doi,
                publication_date=str(rec.publication_year),
                matched_to=rec.matched_to,
            ))

    def add_dailymed_pairs(self, pairs: list):
        """
        Bulk-add from dailymed_versions output.
        Accepts DrugLabelPair dataclass instances.
        For each pair, the OLDER version is labelled OUTDATED
        and the newer version is labelled CURRENT.
        """
        for pair in pairs:
            self.add_entry(ManifestEntry(
                doc_id=f"{pair.pair_id}-older",
                source=DocumentSource.DAILYMED,
                ground_truth=GroundTruthLabel.OUTDATED,
                file_path=pair.older_path or "",
                file_hash=pair.older_hash or "",
                title=pair.drug_name,
                set_id=pair.set_id,
                spl_version=pair.older_version,
                publication_date=pair.older_date,
                extra={
                    "changed_sections": pair.changed_sections,
                    "change_summary": pair.change_summary,
                },
            ))

            self.add_entry(ManifestEntry(
                doc_id=f"{pair.pair_id}-newer",
                source=DocumentSource.DAILYMED,
                ground_truth=GroundTruthLabel.CURRENT,
                file_path=pair.newer_path or "",
                file_hash=pair.newer_hash or "",
                title=pair.drug_name,
                set_id=pair.set_id,
                spl_version=pair.newer_version,
                publication_date=pair.newer_date,
                matched_to=f"{pair.pair_id}-older",
            ))

    # ── Queries ───────────────────────────────────────────────

    def get_by_label(self, label: GroundTruthLabel) -> list[ManifestEntry]:
        return [e for e in self.entries.values() if e.ground_truth == label]

    def get_by_source(self, source: DocumentSource) -> list[ManifestEntry]:
        return [e for e in self.entries.values() if e.source == source]

    def summary(self) -> dict:
        """Return counts by source and ground-truth label."""
        counts = {}
        for entry in self.entries.values():
            key = f"{entry.source.value}/{entry.ground_truth.value}"
            counts[key] = counts.get(key, 0) + 1
        return {
            "total_documents": len(self.entries),
            "counts": counts,
            "created_at": self.created_at,
            "last_modified": self.last_modified,
        }

    # ── Verification ──────────────────────────────────────────

    def verify_hashes(self) -> dict:
        """
        Re-hash all files and check against stored hashes.
        Returns dict with 'verified', 'mismatched', 'missing' lists.
        """
        verified, mismatched, missing = [], [], []

        for doc_id, entry in self.entries.items():
            path = resolve_path(entry.file_path)
            if not path.exists():
                missing.append(doc_id)
                continue

            current_hash = hashlib.sha256(path.read_bytes()).hexdigest()
            if current_hash == entry.file_hash:
                verified.append(doc_id)
            else:
                mismatched.append(doc_id)

        result = {
            "verified": len(verified),
            "mismatched": len(mismatched),
            "missing": len(missing),
            "mismatched_ids": mismatched,
            "missing_ids": missing,
        }

        if mismatched or missing:
            logger.warning(
                f"Manifest verification: {len(mismatched)} hash mismatches, "
                f"{len(missing)} missing files"
            )
        else:
            logger.info(f"Manifest verified: all {len(verified)} files match")

        return result

    # ── Persistence ───────────────────────────────────────────

    def save(self, path: Path = None) -> Path:
        """Save manifest to JSON."""
        if path is None:
            MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
            path = MANIFEST_DIR / "corpus_manifest.json"

        data = {
            "created_at": self.created_at,
            "last_modified": self.last_modified,
            "summary": self.summary(),
            "entries": {
                doc_id: self._entry_to_dict(entry)
                for doc_id, entry in self.entries.items()
            },
        }

        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

        logger.info(f"Manifest saved to {path} ({len(self.entries)} entries)")
        return path

    @classmethod
    def load(cls, path: Path = None) -> "DataManifest":
        """Load manifest from JSON."""
        if path is None:
            path = MANIFEST_DIR / "corpus_manifest.json"

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        manifest = cls()
        manifest.created_at = data.get("created_at", "")
        manifest.last_modified = data.get("last_modified", "")

        for doc_id, entry_data in data.get("entries", {}).items():
            entry = ManifestEntry(
                doc_id=doc_id,
                source=DocumentSource(entry_data["source"]),
                ground_truth=GroundTruthLabel(entry_data["ground_truth"]),
                file_path=entry_data["file_path"],
                file_hash=entry_data["file_hash"],
                title=entry_data.get("title", ""),
                pmid=entry_data.get("pmid"),
                doi=entry_data.get("doi"),
                set_id=entry_data.get("set_id"),
                spl_version=entry_data.get("spl_version"),
                publication_date=entry_data.get("publication_date", ""),
                collection_date=entry_data.get("collection_date", ""),
                matched_to=entry_data.get("matched_to"),
                extra=entry_data.get("extra", {}),
            )
            manifest.entries[doc_id] = entry

        return manifest

    @staticmethod
    def _entry_to_dict(entry: ManifestEntry) -> dict:
        d = asdict(entry)
        d["source"] = entry.source.value
        d["ground_truth"] = entry.ground_truth.value
        d["file_path"] = to_relative(entry.file_path)
        return d
