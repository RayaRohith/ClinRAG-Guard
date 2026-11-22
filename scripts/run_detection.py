"""
Run all detection sources against the indexed corpus.

Usage:
    python -m scripts.run_detection --manifest data/manifest.json --arm 1
    python -m scripts.run_detection --manifest data/manifest.json --arm 2
"""

import argparse
import json
import logging
import sys
from pathlib import Path

from src.data.manifest import DataManifest
from src.detection.text_analyzer import TextAnalyzer
from src.detection.pubmed_checker import PubMedChecker
from src.detection.crossref_checker import CrossrefChecker
from src.detection.naive_baseline import NaiveBaseline
from src.detection.combined import combine_results
from src.detection.staleness_checker import StalenessChecker
from src.utils.config import EVALUATION_RESULTS_DIR

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def run_arm1_detection(manifest: DataManifest) -> dict:
    """Run all detection sources for Arm 1 (retraction detection)."""
    logger.info("=== Arm 1: Retraction Detection ===")

    logger.info("Running (a) text analysis...")
    text_analyzer = TextAnalyzer()
    text_results = text_analyzer.analyze_corpus(manifest)

    logger.info("Running (b) PubMed check...")
    pubmed_checker = PubMedChecker()
    pubmed_results = pubmed_checker.check_corpus(manifest)

    logger.info("Running (c) Crossref check...")
    crossref_checker = CrossrefChecker()
    crossref_results = crossref_checker.check_corpus(manifest)

    logger.info("Running (e) naive baseline...")
    naive = NaiveBaseline()
    naive_results = naive.check_corpus(manifest)

    logger.info("Computing (d) combined results...")
    combined_results = combine_results(text_results, pubmed_results, crossref_results)

    # Build detection_results dict: {source_name: {doc_id: flagged}}
    detection_results = {
        "text_analysis": {r.doc_id: r.flagged for r in text_results},
        "pubmed": {r.doc_id: r.flagged for r in pubmed_results},
        "crossref": {r.doc_id: r.flagged for r in crossref_results},
        "combined_union": {r.doc_id: r.union_flagged for r in combined_results},
        "combined_intersection": {r.doc_id: r.intersection_flagged for r in combined_results},
        "naive_baseline": {r.doc_id: r.flagged for r in naive_results},
    }

    # Build source_details for error analysis
    source_details = {
        "text_analysis": {r.doc_id: r for r in text_results},
        "pubmed": {r.doc_id: r for r in pubmed_results},
        "crossref": {r.doc_id: r for r in crossref_results},
        "naive_baseline": {r.doc_id: r for r in naive_results},
    }

    return {
        "detection_results": detection_results,
        "source_details": source_details,
    }


def run_arm2_detection(manifest: DataManifest) -> dict:
    """
    Run detection for Arm 2 (staleness detection).

    Three detection sources:
      (a) Version API check — does DailyMed list a newer version?
      (b) Date recency check — is the indexed version significantly older?
      (c) Text diff check — do clinical sections differ from current?
      (d) Combined — union and intersection of a+b+c
    """
    logger.info("=== Arm 2: Staleness Detection ===")

    # Load pairs manifest for text_diff to use local file comparisons
    pairs_manifest_path = "data/manifests/dailymed_pairs.json"
    checker = StalenessChecker(pairs_manifest_path=pairs_manifest_path)

    logger.info("Running (a) version API check...")
    version_results = checker.check_corpus_version(manifest)

    logger.info("Running (b) date recency check...")
    date_results = checker.check_corpus_date(manifest)

    logger.info("Running (c) text diff check...")
    text_diff_results = checker.check_corpus_text_diff(manifest)

    # Build combined union/intersection
    version_map = {r.doc_id: r.flagged for r in version_results}
    date_map = {r.doc_id: r.flagged for r in date_results}
    text_diff_map = {r.doc_id: r.flagged for r in text_diff_results}

    all_doc_ids = set(version_map) | set(date_map) | set(text_diff_map)
    combined_union = {}
    combined_intersection = {}
    for doc_id in all_doc_ids:
        v = version_map.get(doc_id, False)
        d = date_map.get(doc_id, False)
        t = text_diff_map.get(doc_id, False)
        combined_union[doc_id] = v or d or t
        combined_intersection[doc_id] = v and d and t

    union_flagged = sum(1 for f in combined_union.values() if f)
    inter_flagged = sum(1 for f in combined_intersection.values() if f)
    logger.info(f"Combined union: {union_flagged} flagged, intersection: {inter_flagged} flagged")

    detection_results = {
        "version_api": version_map,
        "date_recency": date_map,
        "text_diff": text_diff_map,
        "combined_union": combined_union,
        "combined_intersection": combined_intersection,
    }

    source_details = {
        "version_api": {r.doc_id: vars(r) if hasattr(r, '__dict__') else r for r in version_results},
        "date_recency": {r.doc_id: vars(r) if hasattr(r, '__dict__') else r for r in date_results},
        "text_diff": {r.doc_id: vars(r) if hasattr(r, '__dict__') else r for r in text_diff_results},
    }

    return {
        "detection_results": detection_results,
        "source_details": source_details,
    }


def save_detection_results(results: dict, arm: int) -> Path:
    """Save raw detection results to JSON."""
    EVALUATION_RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = EVALUATION_RESULTS_DIR / f"detection_arm{arm}.json"

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results["detection_results"], f, indent=2)

    logger.info(f"Detection results saved to {out_path}")
    return out_path


def main():
    parser = argparse.ArgumentParser(description="Run detection sources")
    parser.add_argument(
        "--manifest", required=True, help="Path to manifest JSON file"
    )
    parser.add_argument(
        "--arm", type=int, choices=[1, 2], required=True,
        help="Study arm (1=retraction, 2=staleness)",
    )
    args = parser.parse_args()

    manifest_path = Path(args.manifest)
    if not manifest_path.exists():
        logger.error(f"Manifest not found: {manifest_path}")
        sys.exit(1)

    manifest = DataManifest.load(manifest_path)
    logger.info(f"Loaded manifest with {len(manifest.entries)} entries")

    if args.arm == 1:
        results = run_arm1_detection(manifest)
    else:
        results = run_arm2_detection(manifest)

    save_detection_results(results, args.arm)
    logger.info("Detection complete.")


if __name__ == "__main__":
    main()
