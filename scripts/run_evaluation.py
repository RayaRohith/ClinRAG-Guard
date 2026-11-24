"""
Compute metrics and generate evaluation reports.

Usage:
    python -m scripts.run_evaluation --manifest data/manifest.json --detection data/results/detection_arm1.json --arm 1
    python -m scripts.run_evaluation --manifest data/manifest.json --detection data/results/detection_arm2.json --arm 2
"""

import argparse
import json
import logging
import sys
from pathlib import Path

from src.data.manifest import DataManifest
from src.evaluation.metrics import (
    evaluate_all_sources, save_metrics, build_ground_truth,
)
from src.evaluation.overlap_analysis import (
    compute_overlap, save_overlap, format_overlap_summary,
)
from src.evaluation.error_analysis import (
    analyze_false_negatives, save_error_analysis, format_error_summary,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="Run evaluation metrics")
    parser.add_argument(
        "--manifest", required=True, help="Path to manifest JSON file",
    )
    parser.add_argument(
        "--detection", required=True,
        help="Path to detection results JSON (from run_detection.py)",
    )
    parser.add_argument(
        "--arm", type=int, choices=[1, 2], required=True,
        help="Study arm (1=retraction, 2=staleness)",
    )
    args = parser.parse_args()

    manifest_path = Path(args.manifest)
    detection_path = Path(args.detection)

    if not manifest_path.exists():
        logger.error(f"Manifest not found: {manifest_path}")
        sys.exit(1)
    if not detection_path.exists():
        logger.error(f"Detection results not found: {detection_path}")
        sys.exit(1)

    manifest = DataManifest.load(manifest_path)
    logger.info(f"Loaded manifest with {len(manifest.entries)} entries")

    with open(detection_path, "r", encoding="utf-8") as f:
        detection_results = json.load(f)
    logger.info(f"Loaded detection results for {len(detection_results)} sources")

    # --- Primary metrics ---
    logger.info("Computing primary metrics (P, R, F1 with Wilson CIs)...")
    metrics = evaluate_all_sources(manifest, detection_results, args.arm)
    metrics_path = save_metrics(metrics, f"metrics_arm{args.arm}.json")

    # --- Overlap analysis ---
    logger.info("Computing source overlap analysis...")
    gt = build_ground_truth(manifest, args.arm)
    overlap = compute_overlap(detection_results, gt, args.arm)
    overlap_path = save_overlap(overlap, f"overlap_arm{args.arm}.json")

    print("\n" + format_overlap_summary(overlap))

    # --- Error analysis ---
    logger.info("Categorising false negatives...")

    # Build metadata from manifest for error categorisation
    metadata = {}
    for doc_id, entry in manifest.entries.items():
        metadata[doc_id] = {
            "doi": entry.doi,
            "pmid": entry.pmid,
            "source": entry.source.value if entry.source else None,
        }

    # Per-document evidence saved by run_detection.py alongside the results.
    det_path = Path(args.detection)
    details_path = det_path.with_name(f"{det_path.stem}_details.json")
    if details_path.exists():
        source_details = json.loads(details_path.read_text(encoding="utf-8"))
    else:
        logger.warning(f"No evidence file at {details_path}; FN causes will be 'unexplained'")
        source_details = {}

    error_analysis = analyze_false_negatives(
        detection_results, gt, source_details, metadata, args.arm,
    )
    error_path = save_error_analysis(error_analysis, f"error_analysis_arm{args.arm}.json")

    print("\n" + format_error_summary(error_analysis))

    # --- Summary ---
    print(f"\n=== Evaluation Complete (Arm {args.arm}) ===")
    print(f"Metrics:        {metrics_path}")
    print(f"Overlap:        {overlap_path}")
    print(f"Error analysis: {error_path}")


if __name__ == "__main__":
    main()
