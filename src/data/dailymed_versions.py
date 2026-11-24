"""
Collects drug label version pairs from DailyMed where the newer version
has a substantive clinical change — indications, warnings, contraindications,
or dosing (not just formatting or branding). We index the older version
and use the newer one as ground truth for staleness detection.

"Substantive" is operationally defined as text similarity ratio < 0.95
in the relevant SPL section.

DailyMed's REST API only serves the current version of each SPL.
To get historical versions we use the /history.json endpoint (which lists
version numbers and dates) then scrape each drug's page for archive
download IDs, and fetch the actual ZIP packages via getArchivalFile.cfm.
"""

import hashlib
import io
import json
import logging
import re
import time
import zipfile
from dataclasses import dataclass, asdict
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path

from src.utils.config import to_relative, resolve_path
from typing import Optional
from xml.etree import ElementTree as ET

import requests
from lxml import html as lxml_html

from src.utils.config import (
    N_DAILYMED_PAIRS, DAILYMED_CHANGE_SECTIONS,
    DAILYMED_API, DAILYMED_RPS, DAILYMED_DIR,
    MANIFEST_DIR, RANDOM_SEED,
)

logger = logging.getLogger(__name__)

DAILYMED_BASE = "https://dailymed.nlm.nih.gov/dailymed"

# SPL XML section codes (LOINC) for clinical content
SPL_SECTION_CODES = {
    "indications": "34067-9",
    "warnings": "34071-1",
    "contraindications": "34070-3",
    "dosing": "34068-7",
    "boxed_warning": "34066-1",
    "warnings_precautions": "43685-7",
}


@dataclass
class DrugLabelPair:
    """A pair of drug label versions where the newer has substantive changes."""
    pair_id: str
    drug_name: str
    set_id: str
    older_spl_id: str
    older_version: int
    older_date: str
    older_path: Optional[str] = None
    older_hash: Optional[str] = None
    newer_spl_id: str = ""
    newer_version: int = 0
    newer_date: str = ""
    newer_path: Optional[str] = None
    newer_hash: Optional[str] = None
    changed_sections: list[str] = None
    change_summary: str = ""

    def __post_init__(self):
        if self.changed_sections is None:
            self.changed_sections = []


class DailyMedVersionCollector:
    """Finds drug label version pairs with substantive clinical changes."""

    def __init__(self, output_dir: str = None):
        self.output_dir = Path(output_dir) if output_dir else DAILYMED_DIR
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._last_request_time = 0.0

    def _rate_limit(self):
        min_interval = 1.0 / DAILYMED_RPS
        elapsed = time.time() - self._last_request_time
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)
        self._last_request_time = time.time()

    # ── Step 1: Find drugs with multiple SPL versions ─────────

    def search_drugs_with_versions(self, page_size: int = 100) -> list[dict]:
        """
        Search DailyMed for drugs, then filter to those with 2+ versions
        via the history endpoint. We over-fetch because most drugs have
        only one version.
        """
        candidates = []
        page = 1
        max_candidates = N_DAILYMED_PAIRS * 10

        logger.info("Searching DailyMed for drugs with version history...")

        while len(candidates) < max_candidates:
            self._rate_limit()

            url = f"{DAILYMED_API}/spls.json"
            params = {"page": page, "pagesize": page_size}

            try:
                resp = requests.get(url, params=params, timeout=30)
                resp.raise_for_status()
                data = resp.json()

                spls = data.get("data", [])
                if not spls:
                    break

                for spl in spls:
                    set_id = spl.get("setid", "")
                    if set_id:
                        candidates.append({
                            "set_id": set_id,
                            "drug_name": spl.get("title", "Unknown"),
                            "published_date": spl.get("published_date", ""),
                        })

                page += 1

            except requests.RequestException as e:
                logger.warning(f"DailyMed search failed on page {page}: {e}")
                break

        logger.info(f"Collected {len(candidates)} SPL entries, filtering for multi-version drugs...")

        # Filter to drugs with 2+ versions
        multi_version = []
        seen = set()
        for entry in candidates:
            sid = entry["set_id"]
            if sid in seen:
                continue
            seen.add(sid)

            n_versions = self._count_versions(sid)
            if n_versions >= 2:
                entry["n_versions"] = n_versions
                multi_version.append(entry)
                logger.debug(f"  {entry['drug_name'][:60]} — {n_versions} versions")

            if len(seen) % 100 == 0:
                logger.info(
                    f"  Checked {len(seen)} unique drugs, "
                    f"{len(multi_version)} have 2+ versions"
                )

        logger.info(
            f"Found {len(multi_version)} drugs with 2+ versions "
            f"out of {len(seen)} checked"
        )
        return multi_version

    def _count_versions(self, set_id: str) -> int:
        """Quick check: how many versions does this drug have?"""
        self._rate_limit()
        url = f"{DAILYMED_API}/spls/{set_id}/history.json"
        try:
            resp = requests.get(url, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            history = data.get("data", {}).get("history", [])
            return len(history)
        except (requests.RequestException, ValueError, KeyError):
            return 0

    # ── Step 2: Get archive download IDs from drug page ──────

    def get_archive_ids(self, set_id: str) -> list[dict]:
        """
        Scrape the drug's DailyMed page to find archive download IDs
        for each version. Returns list of {version, date, archive_id}
        sorted oldest-first.
        """
        self._rate_limit()
        url = f"{DAILYMED_BASE}/drugInfo.cfm?setid={set_id}"

        try:
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()
        except requests.RequestException as e:
            logger.warning(f"Failed to fetch drug page for {set_id}: {e}")
            return []

        tree = lxml_html.fromstring(resp.content)

        archives = []
        # Look for archive download links in the page
        for link in tree.xpath('//a[contains(@href, "getArchivalFile.cfm")]'):
            href = link.get("href", "")
            match = re.search(r'archive_id=(\d+)', href)
            if not match:
                continue

            archive_id = match.group(1)
            text = link.text_content().strip()

            # Try to extract version number and date from surrounding text
            parent_text = link.getparent().text_content() if link.getparent() is not None else text

            version_match = re.search(r'version\s*(\d+)', parent_text, re.IGNORECASE)
            version = int(version_match.group(1)) if version_match else 0

            date_match = re.search(
                r'((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2},?\s+\d{4})',
                parent_text,
            )
            date_str = date_match.group(1) if date_match else ""

            archives.append({
                "archive_id": archive_id,
                "version": version,
                "date": date_str,
            })

        # Deduplicate by archive_id
        seen_ids = set()
        unique = []
        for a in archives:
            if a["archive_id"] not in seen_ids:
                seen_ids.add(a["archive_id"])
                unique.append(a)

        unique.sort(key=lambda a: a["version"])
        return unique

    # ── Step 3: Download and extract SPL XML from archive ZIP ─

    def download_archive_xml(self, archive_id: str, label: str) -> Optional[Path]:
        """
        Download an archived SPL package (ZIP) and extract the XML file.
        """
        self._rate_limit()
        url = f"{DAILYMED_BASE}/getArchivalFile.cfm?archive_id={archive_id}"

        try:
            resp = requests.get(url, timeout=120)
            resp.raise_for_status()

            if len(resp.content) < 100:
                logger.warning(f"Archive {archive_id} returned tiny response, skipping")
                return None

            with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                xml_files = [n for n in zf.namelist() if n.lower().endswith('.xml')]
                if not xml_files:
                    logger.warning(f"No XML found in archive {archive_id}")
                    return None

                xml_name = xml_files[0]
                xml_content = zf.read(xml_name)

            out_path = self.output_dir / f"{label}.xml"
            out_path.write_bytes(xml_content)
            return out_path

        except (requests.RequestException, zipfile.BadZipFile) as e:
            logger.warning(f"Archive download failed for {archive_id}: {e}")
            return None

    # ── Step 4: Download current SPL XML via API ─────────────

    def download_current_xml(self, set_id: str, label: str) -> Optional[Path]:
        """Download the current version SPL XML from the API."""
        self._rate_limit()
        url = f"{DAILYMED_API}/spls/{set_id}.xml"
        try:
            resp = requests.get(url, timeout=60)
            resp.raise_for_status()
            out_path = self.output_dir / f"{label}.xml"
            out_path.write_text(resp.text, encoding="utf-8")
            return out_path
        except requests.RequestException as e:
            logger.warning(f"SPL download failed for {set_id}: {e}")
            return None

    # ── Step 5: Extract clinical sections from SPL XML ────────

    def extract_sections(self, xml_path: Path) -> dict[str, str]:
        """
        Extract clinical text sections from SPL XML by LOINC code.
        Returns dict mapping section name to plain text content.
        """
        try:
            tree = ET.parse(xml_path)
            root = tree.getroot()
        except ET.ParseError as e:
            logger.warning(f"XML parse error for {xml_path}: {e}")
            return {}

        NS = "{urn:hl7-org:v3}"
        sections = {}

        for section_name, loinc_code in SPL_SECTION_CODES.items():
            for elem in root.iter(f"{NS}section"):
                code_elem = elem.find(f"{NS}code")
                if code_elem is None:
                    code_elem = elem.find("code")
                if code_elem is not None and code_elem.get("code") == loinc_code:
                    text = self._extract_text(elem)
                    if text.strip():
                        sections[section_name] = text.strip()
                    break

        return sections

    @staticmethod
    def _extract_text(element) -> str:
        """Recursively extract all text content from an XML element."""
        texts = []
        if element.text:
            texts.append(element.text)
        for child in element:
            texts.append(DailyMedVersionCollector._extract_text(child))
            if child.tail:
                texts.append(child.tail)
        return " ".join(texts)

    # ── Step 5b: Read version and date from the label itself ──

    @staticmethod
    def read_spl_metadata(xml_path: Path) -> tuple[int, str]:
        """
        Read a label's own version number and effective date from its SPL XML.

        These fields are authoritative. The DailyMed web page scraped in
        get_archive_ids() does not reliably expose them, so ordering by the
        scraped values is unsafe. Returns (version, "YYYY-MM-DD"), or (0, "")
        if a field is missing.
        """
        text = Path(xml_path).read_text(encoding="utf-8", errors="ignore")
        v = re.search(r'<versionNumber\s+value="(\d+)"', text)
        d = re.search(r'<effectiveTime\s+value="(\d{4})(\d{2})(\d{2})', text)
        version = int(v.group(1)) if v else 0
        date = f"{d.group(1)}-{d.group(2)}-{d.group(3)}" if d else ""
        return version, date

    # ── Step 6: Compare versions for substantive changes ──────

    def compare_versions(
        self, older_sections: dict[str, str], newer_sections: dict[str, str]
    ) -> tuple[list[str], str]:
        """
        Compare two versions' clinical sections for substantive changes.

        Returns (changed_section_names, human_readable_summary).
        A change is "substantive" if the text similarity ratio is below 0.95
        for sections we care about (indications, warnings, contraindications, dosing).
        """
        changed = []
        summaries = []

        for section_name in DAILYMED_CHANGE_SECTIONS:
            older_text = older_sections.get(section_name, "")
            newer_text = newer_sections.get(section_name, "")

            if not older_text and not newer_text:
                continue

            if not older_text and newer_text:
                changed.append(section_name)
                summaries.append(f"{section_name}: new section added")
                continue

            if older_text and not newer_text:
                changed.append(section_name)
                summaries.append(f"{section_name}: section removed")
                continue

            older_norm = re.sub(r"\s+", " ", older_text).strip()
            newer_norm = re.sub(r"\s+", " ", newer_text).strip()

            ratio = SequenceMatcher(None, older_norm, newer_norm).ratio()
            if ratio < 0.95:
                changed.append(section_name)
                pct = round((1 - ratio) * 100, 1)
                summaries.append(f"{section_name}: {pct}% changed")

        summary = "; ".join(summaries) if summaries else "no substantive changes"
        return changed, summary

    # ── Step 7: Build version pairs ───────────────────────────

    def find_substantive_pairs(self, drug_entries: list[dict]) -> list[DrugLabelPair]:
        """
        For each multi-version drug, get archive IDs, download the oldest
        and newest versions, and check for substantive clinical changes.
        """
        pairs = []
        checked = 0

        for entry in drug_entries:
            if len(pairs) >= N_DAILYMED_PAIRS:
                break

            set_id = entry["set_id"]
            checked += 1
            if checked % 10 == 0:
                logger.info(f"Checked {checked} drugs, found {len(pairs)} pairs...")

            archives = self.get_archive_ids(set_id)
            if len(archives) < 2:
                logger.debug(f"  {set_id}: only {len(archives)} archive entries, skipping")
                continue

            first, last = archives[0], archives[-1]

            path_a = self.download_archive_xml(
                first["archive_id"], f"{set_id}_a{first['archive_id']}",
            )
            path_b = self.download_archive_xml(
                last["archive_id"], f"{set_id}_a{last['archive_id']}",
            )
            if not path_a or not path_b:
                continue

            # Order by each label's own version and date, never by page order.
            meta_a = self.read_spl_metadata(path_a)
            meta_b = self.read_spl_metadata(path_b)
            if meta_a == meta_b:
                logger.debug(f"  {set_id}: archives share version {meta_a}, skipping")
                continue
            if meta_a < meta_b:
                old_arc, old_path, (old_ver, old_date) = first, path_a, meta_a
                new_arc, new_path, (new_ver, new_date) = last, path_b, meta_b
            else:
                old_arc, old_path, (old_ver, old_date) = last, path_b, meta_b
                new_arc, new_path, (new_ver, new_date) = first, path_a, meta_a

            older_sections = self.extract_sections(old_path)
            newer_sections = self.extract_sections(new_path)

            if not older_sections and not newer_sections:
                logger.debug(f"  {set_id}: no clinical sections extracted")
                continue

            changed, summary = self.compare_versions(older_sections, newer_sections)

            if changed:
                pair = DrugLabelPair(
                    pair_id=f"DM-{set_id}-v{old_ver}-v{new_ver}",
                    drug_name=entry.get("drug_name", "Unknown"),
                    set_id=set_id,
                    older_spl_id=old_arc["archive_id"],
                    older_version=old_ver,
                    older_date=old_date,
                    older_path=str(old_path),
                    older_hash=self._file_hash(old_path),
                    newer_spl_id=new_arc["archive_id"],
                    newer_version=new_ver,
                    newer_date=new_date,
                    newer_path=str(new_path),
                    newer_hash=self._file_hash(new_path),
                    changed_sections=changed,
                    change_summary=summary,
                )
                pairs.append(pair)
                logger.info(
                    f"  PAIR #{len(pairs)}: {entry['drug_name'][:50]} "
                    f"v{old_ver} ({old_date}) → v{new_ver} ({new_date}) | {summary}"
                )

        logger.info(f"Found {len(pairs)} drug label pairs with substantive changes")
        return pairs

    # ── Step 8: Save manifest ─────────────────────────────────

    def save_manifest(self, pairs: list[DrugLabelPair]) -> Path:
        """Save the collected pairs as a JSON manifest."""
        MANIFEST_DIR.mkdir(parents=True, exist_ok=True)

        manifest = {
            "study": "ClinRAG-Guard Arm 2: Staleness Detection",
            "collected_at": datetime.now().isoformat(),
            "n_pairs": len(pairs),
            "change_sections_checked": DAILYMED_CHANGE_SECTIONS,
            "pairs": [
                {**asdict(p),
                 "older_path": to_relative(p.older_path),
                 "newer_path": to_relative(p.newer_path)}
                for p in pairs
            ],
        }

        out_path = MANIFEST_DIR / "dailymed_pairs.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)

        logger.info(f"DailyMed manifest saved to {out_path}")
        return out_path

    # ── Orchestrator ──────────────────────────────────────────

    def run(self) -> list[DrugLabelPair]:
        """
        Full collection pipeline:
        1. Search DailyMed for drugs with 2+ version history
        2. Scrape each drug's page for archive download IDs
        3. Download oldest and newest archived versions (ZIP → XML)
        4. Compare clinical sections for substantive changes
        5. Keep pairs where changes are real (not formatting-only)
        6. Save manifest
        """
        logger.info("Starting DailyMed version collection...")

        drug_entries = self.search_drugs_with_versions()

        if not drug_entries:
            logger.warning("No multi-version drugs found. Try increasing search pages.")
            self.save_manifest([])
            return []

        pairs = self.find_substantive_pairs(drug_entries)
        self.save_manifest(pairs)

        return pairs

    # ── Utilities ─────────────────────────────────────────────

    @staticmethod
    def _file_hash(path: Path) -> str:
        h = hashlib.sha256()
        h.update(path.read_bytes())
        return h.hexdigest()
