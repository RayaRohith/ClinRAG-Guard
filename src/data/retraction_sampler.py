"""
Samples retracted papers from Retraction Watch, matches each to a
control paper (same journal + publication year), and downloads
pre-retraction full text from Europe PMC.

We index pre-retraction versions because current versions often carry
"RETRACTED" watermarks that make detection trivially easy. Only IDs
and DOIs from Retraction Watch are stored — the database itself cannot
be redistributed.
"""

import csv
import json
import hashlib
import logging
import random
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests

from src.utils.config import (
    N_RETRACTED, N_CONTROLS, RETRACTION_WATCH_FILTERS,
    EUROPE_PMC_API, EUROPE_PMC_RPS, RETRACTION_DIR,
    MANIFEST_DIR, RANDOM_SEED,
)

logger = logging.getLogger(__name__)


@dataclass
class RetractionRecord:
    """A retracted paper identified from Retraction Watch."""
    record_id: str
    pmid: str
    doi: str
    title: str
    journal: str
    publication_year: int
    retraction_date: str
    retraction_nature: str
    has_full_text: bool = False
    full_text_path: Optional[str] = None
    full_text_hash: Optional[str] = None


@dataclass
class ControlRecord:
    """A non-retracted control paper matched to a retraction."""
    record_id: str
    pmid: str
    doi: str
    title: str
    journal: str
    publication_year: int
    matched_to: str          # record_id of the retracted paper
    has_full_text: bool = False
    full_text_path: Optional[str] = None
    full_text_hash: Optional[str] = None


class RetractionSampler:
    """Samples retracted + control papers for Arm 1."""

    def __init__(self, retraction_watch_path: str, output_dir: str = None):
        self.rw_path = Path(retraction_watch_path)
        self.output_dir = Path(output_dir) if output_dir else RETRACTION_DIR
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.rng = random.Random(RANDOM_SEED)
        self._last_request_time = 0.0

    def _rate_limit(self, rps: float):
        """Enforce rate limiting between API requests."""
        min_interval = 1.0 / rps
        elapsed = time.time() - self._last_request_time
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)
        self._last_request_time = time.time()

    # ── Step 1: Load and filter Retraction Watch ──────────────

    def load_retraction_watch(self) -> list[dict]:
        """
        Load Retraction Watch CSV and filter to eligible papers.

        Filters applied:
        - nature == "Retraction" (not "Expression of Concern" or "Correction")
        - Has a PubMed ID
        - Will check for open-access full text in a later step
        """
        if not self.rw_path.exists():
            raise FileNotFoundError(
                f"Retraction Watch database not found at {self.rw_path}. "
                "You must obtain this independently — it cannot be redistributed. "
                "See: https://retractionwatch.com/retraction-watch-database-user-guide/"
            )

        eligible = []
        with open(self.rw_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                nature = row.get("RetractionNature", "").strip()
                pmid = row.get("OriginalPaperPubMedID", "").strip()
                doi = row.get("OriginalPaperDOI", "").strip()

                if not RETRACTION_WATCH_FILTERS.get("nature") == nature:
                    continue
                if RETRACTION_WATCH_FILTERS.get("has_pmid") and not pmid:
                    continue

                try:
                    pub_year = int(row.get("OriginalPaperDate", "")[:4])
                except (ValueError, TypeError):
                    continue

                eligible.append({
                    "pmid": pmid,
                    "doi": doi,
                    "title": row.get("Title", "").strip(),
                    "journal": row.get("Journal", "").strip(),
                    "publication_year": pub_year,
                    "retraction_date": row.get("RetractionDate", "").strip(),
                    "retraction_nature": nature,
                })

        logger.info(f"Loaded {len(eligible)} eligible retracted papers from Retraction Watch")
        return eligible

    # ── Step 2: Check Europe PMC for open-access full text ────

    def check_full_text_availability(self, pmid: str) -> dict:
        """
        Query Europe PMC to check if open-access full text is available.

        Returns dict with 'available' bool and 'source' (e.g. 'PMC').
        We specifically need CC BY articles so we can legally index them.
        """
        self._rate_limit(EUROPE_PMC_RPS)

        url = f"{EUROPE_PMC_API}/search"
        params = {
            "query": f"EXT_ID:{pmid} SRC:MED",
            "resultType": "core",
            "format": "json",
        }

        try:
            resp = requests.get(url, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()

            results = data.get("resultList", {}).get("result", [])
            if not results:
                return {"available": False, "source": None, "pmcid": None}

            paper = results[0]
            is_oa = paper.get("isOpenAccess") == "Y"
            pmcid = paper.get("pmcid", "")

            return {
                "available": is_oa and bool(pmcid),
                "source": "PMC" if pmcid else None,
                "pmcid": pmcid,
            }

        except requests.RequestException as e:
            logger.warning(f"Europe PMC lookup failed for PMID {pmid}: {e}")
            return {"available": False, "source": None, "pmcid": None}

    # ── Step 3: Sample retracted papers ───────────────────────

    def sample_retracted(self, eligible: list[dict]) -> list[RetractionRecord]:
        """
        From the eligible pool, check full-text availability and sample
        N_RETRACTED papers. We over-query because not all will have OA text.
        """
        # Shuffle for random sampling
        self.rng.shuffle(eligible)

        sampled = []
        checked = 0

        for paper in eligible:
            if len(sampled) >= N_RETRACTED:
                break

            checked += 1
            if checked % 50 == 0:
                logger.info(f"Checked {checked} papers, sampled {len(sampled)} so far...")

            ft = self.check_full_text_availability(paper["pmid"])
            if not ft["available"]:
                continue

            record = RetractionRecord(
                record_id=f"RET-{paper['pmid']}",
                pmid=paper["pmid"],
                doi=paper["doi"],
                title=paper["title"],
                journal=paper["journal"],
                publication_year=paper["publication_year"],
                retraction_date=paper["retraction_date"],
                retraction_nature=paper["retraction_nature"],
            )
            sampled.append(record)

        logger.info(
            f"Sampled {len(sampled)} retracted papers "
            f"(checked {checked} for full-text availability)"
        )

        if len(sampled) < N_RETRACTED:
            logger.warning(
                f"Only found {len(sampled)}/{N_RETRACTED} retracted papers "
                f"with open-access full text. Consider relaxing filters."
            )

        return sampled

    # ── Step 4: Match controls ────────────────────────────────

    def find_control(self, retracted: RetractionRecord) -> Optional[ControlRecord]:
        """
        Find a non-retracted control paper from the same journal and year.

        Uses Europe PMC search with negative filter for retracted status.
        """
        self._rate_limit(EUROPE_PMC_RPS)

        query = (
            f'JOURNAL:"{retracted.journal}" '
            f"PUB_YEAR:{retracted.publication_year} "
            f"SRC:MED "
            f"OPEN_ACCESS:y "
            f"NOT EXT_ID:{retracted.pmid}"
        )

        url = f"{EUROPE_PMC_API}/search"
        params = {
            "query": query,
            "resultType": "core",
            "pageSize": 25,
            "format": "json",
        }

        try:
            resp = requests.get(url, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()

            results = data.get("resultList", {}).get("result", [])
            # Shuffle to avoid always picking the first result
            self.rng.shuffle(results)

            for paper in results:
                pmid = paper.get("pmid", "")
                pmcid = paper.get("pmcid", "")
                if not pmid or not pmcid:
                    continue
                if paper.get("isOpenAccess") != "Y":
                    continue

                return ControlRecord(
                    record_id=f"CTL-{pmid}",
                    pmid=pmid,
                    doi=paper.get("doi", ""),
                    title=paper.get("title", ""),
                    journal=retracted.journal,
                    publication_year=retracted.publication_year,
                    matched_to=retracted.record_id,
                )

            logger.warning(
                f"No control found for {retracted.record_id} "
                f"({retracted.journal}, {retracted.publication_year})"
            )
            return None

        except requests.RequestException as e:
            logger.warning(f"Control search failed for {retracted.record_id}: {e}")
            return None

    def match_controls(self, retracted: list[RetractionRecord]) -> list[ControlRecord]:
        """Match a control paper for each retracted paper."""
        controls = []
        for i, rec in enumerate(retracted):
            if (i + 1) % 25 == 0:
                logger.info(f"Matching controls: {i + 1}/{len(retracted)}")
            ctrl = self.find_control(rec)
            if ctrl:
                controls.append(ctrl)

        logger.info(f"Matched {len(controls)}/{len(retracted)} controls")
        return controls

    # ── Step 5: Download pre-retraction full text ─────────────

    def download_full_text(self, pmid: str, record_id: str) -> Optional[Path]:
        """
        Download full text XML from Europe PMC.

        Europe PMC serves the archived version — for papers retracted
        after archiving, this is the pre-retraction text. This is
        critical: we need the version as originally published, not
        the current version with RETRACTED watermarks.
        """
        self._rate_limit(EUROPE_PMC_RPS)

        # First get the PMCID
        ft_info = self.check_full_text_availability(pmid)
        if not ft_info["available"] or not ft_info["pmcid"]:
            return None

        pmcid = ft_info["pmcid"]
        url = f"{EUROPE_PMC_API}/{pmcid}/fullTextXML"

        try:
            resp = requests.get(url, timeout=60)
            resp.raise_for_status()

            out_path = self.output_dir / f"{record_id}.xml"
            out_path.write_text(resp.text, encoding="utf-8")

            return out_path

        except requests.RequestException as e:
            logger.warning(f"Full text download failed for {record_id} (PMC:{pmcid}): {e}")
            return None

    def download_all(
        self,
        retracted: list[RetractionRecord],
        controls: list[ControlRecord],
    ) -> tuple[list[RetractionRecord], list[ControlRecord]]:
        """Download full text for all retracted and control papers."""
        total = len(retracted) + len(controls)
        done = 0

        for rec in retracted:
            done += 1
            if done % 25 == 0:
                logger.info(f"Downloading full text: {done}/{total}")

            path = self.download_full_text(rec.pmid, rec.record_id)
            if path:
                rec.has_full_text = True
                rec.full_text_path = str(path)
                rec.full_text_hash = self._file_hash(path)

        for rec in controls:
            done += 1
            if done % 25 == 0:
                logger.info(f"Downloading full text: {done}/{total}")

            path = self.download_full_text(rec.pmid, rec.record_id)
            if path:
                rec.has_full_text = True
                rec.full_text_path = str(path)
                rec.full_text_hash = self._file_hash(path)

        ret_with_text = sum(1 for r in retracted if r.has_full_text)
        ctl_with_text = sum(1 for c in controls if c.has_full_text)
        logger.info(
            f"Downloaded full text: {ret_with_text}/{len(retracted)} retracted, "
            f"{ctl_with_text}/{len(controls)} controls"
        )

        return retracted, controls

    # ── Step 6: Save sample metadata ──────────────────────────

    def save_sample(
        self,
        retracted: list[RetractionRecord],
        controls: list[ControlRecord],
    ) -> Path:
        """
        Save sample metadata to JSON. Only IDs, DOIs, and metadata —
        NOT the Retraction Watch database itself (licence restriction).
        """
        MANIFEST_DIR.mkdir(parents=True, exist_ok=True)

        sample = {
            "study": "ClinRAG-Guard Arm 1: Retraction Detection",
            "sampled_at": datetime.now().isoformat(),
            "seed": RANDOM_SEED,
            "n_retracted": len(retracted),
            "n_controls": len(controls),
            "retracted": [asdict(r) for r in retracted],
            "controls": [asdict(c) for c in controls],
        }

        out_path = MANIFEST_DIR / "retraction_sample.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(sample, f, indent=2)

        logger.info(f"Sample manifest saved to {out_path}")
        return out_path

    # ── Orchestrator ──────────────────────────────────────────

    def run(self) -> tuple[list[RetractionRecord], list[ControlRecord]]:
        """
        Full sampling pipeline:
        1. Load and filter Retraction Watch
        2. Sample 300 retracted papers with OA full text
        3. Match 300 controls (same journal + year)
        4. Download pre-retraction full text for all
        5. Save manifest
        """
        logger.info("Starting retraction sampling pipeline...")

        eligible = self.load_retraction_watch()
        retracted = self.sample_retracted(eligible)
        controls = self.match_controls(retracted)
        retracted, controls = self.download_all(retracted, controls)
        self.save_sample(retracted, controls)

        return retracted, controls

    # ── Utilities ─────────────────────────────────────────────

    @staticmethod
    def _file_hash(path: Path) -> str:
        """SHA-256 hash of file contents for provenance tracking."""
        h = hashlib.sha256()
        h.update(path.read_bytes())
        return h.hexdigest()
