"""
Orchestrates data collection for both study arms:
  Arm 1: Retraction detection (Retraction Watch + Europe PMC)
  Arm 2: Staleness detection (DailyMed version pairs)

Usage:
    python -m scripts.run_sampling --rw-path path/to/retraction_watch.csv
    python -m scripts.run_sampling --arm 1 --rw-path path/to/retraction_watch.csv
    python -m scripts.run_sampling --arm 2

The Retraction Watch database must be obtained independently:
    https://retractionwatch.com/retraction-watch-database-user-guide/
"""

import argparse
import logging
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.utils.config import ensure_dirs
from src.data.retraction_sampler import RetractionSampler
from src.data.dailymed_versions import DailyMedVersionCollector
from src.data.manifest import DataManifest

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("results/sampling.log"),
    ],
)
logger = logging.getLogger(__name__)


def run_arm1(rw_path: str) -> tuple:
    """Arm 1: Retraction detection sampling."""
    logger.info("=" * 60)
    logger.info("ARM 1: Retraction Detection")
    logger.info("=" * 60)

    sampler = RetractionSampler(rw_path)
    retracted, controls = sampler.run()

    logger.info(
        f"Arm 1 complete: {len(retracted)} retracted, {len(controls)} controls"
    )
    return retracted, controls


def run_arm2() -> list:
    """Arm 2: Staleness detection collection."""
    logger.info("=" * 60)
    logger.info("ARM 2: Staleness Detection")
    logger.info("=" * 60)

    collector = DailyMedVersionCollector()
    pairs = collector.run()

    logger.info(f"Arm 2 complete: {len(pairs)} drug label pairs")
    return pairs


def main():
    parser = argparse.ArgumentParser(
        description="ClinRAG-Guard data collection"
    )
    parser.add_argument(
        "--arm", type=int, choices=[1, 2],
        help="Run only one arm (default: both)"
    )
    parser.add_argument(
        "--rw-path", type=str,
        default="data/raw/retraction_watch.csv",
        help="Path to Retraction Watch CSV (required for Arm 1)"
    )
    args = parser.parse_args()

    ensure_dirs()
    manifest = DataManifest()

    if args.arm is None or args.arm == 1:
        retracted, controls = run_arm1(args.rw_path)
        manifest.add_retraction_records(retracted, controls)

    if args.arm is None or args.arm == 2:
        pairs = run_arm2()
        manifest.add_dailymed_pairs(pairs)

    manifest_path = manifest.save()
    summary = manifest.summary()

    logger.info("=" * 60)
    logger.info("DATA COLLECTION COMPLETE")
    logger.info(f"Total documents: {summary['total_documents']}")
    for key, count in summary["counts"].items():
        logger.info(f"  {key}: {count}")
    logger.info(f"Manifest saved to: {manifest_path}")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
