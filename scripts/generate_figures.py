"""
Generate publication-quality figures for the ClinRAG-Guard benchmark results.

Creates:
  - Fig 1: Precision/Recall/F1 comparison with confidence intervals
  - Fig 2: Confusion matrices for each detection method
  - Fig 3: Venn diagram showing source overlap
  - Fig 4: Distribution of changed clinical sections

Usage:
    python -m scripts.generate_figures --arm 2
"""

import argparse
import json
import logging
from pathlib import Path
from typing import Optional

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib_venn import venn2, venn3
import numpy as np
import seaborn as sns

from src.utils.config import EVALUATION_RESULTS_DIR

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Set publication-quality style
plt.rcParams['figure.dpi'] = 300
plt.rcParams['savefig.dpi'] = 300
plt.rcParams['font.size'] = 10
plt.rcParams['font.family'] = 'sans-serif'
plt.rcParams['axes.labelsize'] = 11
plt.rcParams['axes.titlesize'] = 12
plt.rcParams['xtick.labelsize'] = 9
plt.rcParams['ytick.labelsize'] = 9
plt.rcParams['legend.fontsize'] = 9
sns.set_palette("husl")


BASE_METHODS = ["version_api", "date_recency", "text_diff"]
METHOD_LABELS = {
    "version_api": "Version API",
    "date_recency": "Date Recency",
    "text_diff": "Text Diff",
}


def _normalise_metrics(raw: dict) -> dict:
    """
    Convert metrics_arm{N}.json (a list under "sources", each with nested
    value/lower/upper) into {method: flat dict}. Fails loudly if the format
    is not recognised, so an empty figure can never be produced silently.
    """
    out = {}
    for src in raw.get("sources", []):
        cm = src["confusion_matrix"]
        out[src["source_name"]] = {
            "precision": src["precision"]["value"],
            "precision_lo": src["precision"]["lower"],
            "precision_hi": src["precision"]["upper"],
            "recall": src["recall"]["value"],
            "recall_lo": src["recall"]["lower"],
            "recall_hi": src["recall"]["upper"],
            "f1": src["f1"],
            "f1_lo": src["f1_lower"],
            "f1_hi": src["f1_upper"],
            "tp": cm["tp"], "fp": cm["fp"], "tn": cm["tn"], "fn": cm["fn"],
        }
    missing = [m for m in BASE_METHODS if m not in out]
    if missing:
        raise ValueError(f"Metrics file has no entry for {missing}; found {list(out)}")
    return out


def load_results(arm: int) -> dict:
    """Load evaluation results and raw detection flags for an arm."""
    base = EVALUATION_RESULTS_DIR
    with open(base / f"metrics_arm{arm}.json", encoding="utf-8") as f:
        metrics = _normalise_metrics(json.load(f))
    with open(base / f"detection_arm{arm}.json", encoding="utf-8") as f:
        detection = json.load(f)
    return {"metrics": metrics, "detection": detection}


def plot_metrics_comparison(metrics: dict, arm: int, out_dir: Path):
    """Figure 1: P/R/F1 per method with asymmetric 95% Wilson intervals."""
    labels = [METHOD_LABELS[m] for m in BASE_METHODS]
    x = np.arange(len(BASE_METHODS))
    width = 0.25
    colors = ["#4C72B0", "#55A868", "#C44E52"]

    fig, ax = plt.subplots(figsize=(8, 5))
    for i, (key, name, color) in enumerate(
        zip(["precision", "recall", "f1"], ["Precision", "Recall", "F1"], colors)
    ):
        vals = [metrics[m][key] for m in BASE_METHODS]
        # max(0, .) guards against floating-point noise (e.g. upper 0.9999999 vs 1.0)
        lo = [max(0.0, metrics[m][key] - metrics[m][f"{key}_lo"]) for m in BASE_METHODS]
        hi = [max(0.0, metrics[m][f"{key}_hi"] - metrics[m][key]) for m in BASE_METHODS]
        bars = ax.bar(x + width * (i - 1), vals, width, label=name,
                      yerr=[lo, hi], capsize=4, color=color, alpha=0.85)
        for bar, v, h in zip(bars, vals, hi):
            ax.text(bar.get_x() + bar.get_width() / 2, v + h + 0.015, f"{v:.2f}",
                    ha="center", va="bottom", fontsize=8)

    ax.set_xlabel("Detection method")
    ax.set_ylabel("Score")
    n_pos = metrics[BASE_METHODS[0]]["tp"] + metrics[BASE_METHODS[0]]["fn"]
    ax.set_title(f"Staleness detection performance (Arm {arm}, {n_pos} outdated labels)\n"
                 "Error bars: 95% Wilson score intervals")
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.legend(loc="lower left")
    ax.set_ylim(0, 1.15)
    ax.grid(axis="y", alpha=0.3)

    plt.tight_layout()
    out_path = out_dir / f"fig1_metrics_comparison_arm{arm}.png"
    plt.savefig(out_path, bbox_inches="tight")
    plt.close()
    logger.info(f"Saved {out_path}")


def plot_confusion_matrices(metrics: dict, arm: int, out_dir: Path):
    """Figure 2: one confusion matrix per base detection method."""
    fig, axes = plt.subplots(1, len(BASE_METHODS), figsize=(14, 4))
    for ax, method in zip(axes, BASE_METHODS):
        m = metrics[method]
        cm = np.array([[m["tn"], m["fp"]], [m["fn"], m["tp"]]])
        sns.heatmap(
            cm, annot=True, fmt="d", cmap="Blues", cbar=False, ax=ax,
            xticklabels=["Predicted\ncurrent", "Predicted\noutdated"],
            yticklabels=["Actually\ncurrent", "Actually\noutdated"],
            square=True, linewidths=1, linecolor="black",
        )
        ax.set_title(f"{METHOD_LABELS[method]}\nP={m['precision']:.2f}  R={m['recall']:.2f}")

    plt.tight_layout()
    out_path = out_dir / f"fig2_confusion_matrices_arm{arm}.png"
    plt.savefig(out_path, bbox_inches="tight")
    plt.close()
    logger.info(f"Saved {out_path}")


def plot_source_overlap(detection: dict, arm: int, out_dir: Path):
    """
    Figure 3: exact combinations of methods that flagged each document,
    computed from raw flags. A bar chart replaces the Venn diagram, which is
    unreadable when one method's flags are a subset of another's.
    """
    from collections import Counter

    docs = detection[BASE_METHODS[0]].keys()
    combos = Counter()
    for doc in docs:
        hit = tuple(METHOD_LABELS[m] for m in BASE_METHODS if detection[m].get(doc))
        if hit:
            combos[" + ".join(hit)] += 1
    items = sorted(combos.items(), key=lambda kv: kv[1])

    fig, ax = plt.subplots(figsize=(8, 3.5))
    bars = ax.barh([k for k, _ in items], [v for _, v in items], color="#4C72B0", alpha=0.85)
    for bar, (_, v) in zip(bars, items):
        ax.text(bar.get_width() + 1, bar.get_y() + bar.get_height() / 2, str(v),
                va="center", fontsize=9)
    ax.set_xlabel("Documents flagged")
    ax.set_title(f"Which methods flagged each document (Arm {arm}, "
                 f"{len(docs)} documents; {len(docs) - sum(combos.values())} flagged by none)")
    ax.set_xlim(0, max(combos.values()) * 1.15)
    ax.grid(axis="x", alpha=0.3)

    plt.tight_layout()
    out_path = out_dir / f"fig3_source_overlap_arm{arm}.png"
    plt.savefig(out_path, bbox_inches="tight")
    plt.close()
    logger.info(f"Saved {out_path}")


def plot_change_distribution(arm: int, out_dir: Path):
    """
    Figure 4: Distribution of changed clinical sections in the dataset.
    """
    # Load dailymed_pairs.json to get change details
    pairs_path = Path("data/manifests/dailymed_pairs.json")
    if not pairs_path.exists():
        logger.warning(f"Pairs manifest not found: {pairs_path}")
        return

    with open(pairs_path, encoding="utf-8") as f:
        pairs_data = json.load(f)

    # Count which sections changed
    section_counts = {
        "indications": 0,
        "warnings": 0,
        "contraindications": 0,
        "dosing": 0,
    }

    for pair in pairs_data.get("pairs", []):
        for section in pair.get("changed_sections", []):
            if section in section_counts:
                section_counts[section] += 1

    # Create bar chart
    sections = list(section_counts.keys())
    counts = list(section_counts.values())

    fig, ax = plt.subplots(figsize=(8, 5))

    bars = ax.bar(
        sections,
        counts,
        color='#4C72B0',
        alpha=0.8,
        edgecolor='black',
    )

    # Add value labels
    for bar in bars:
        height = bar.get_height()
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            height + 1,
            f'{int(height)}',
            ha='center',
            va='bottom',
        )

    ax.set_xlabel('Clinical Section')
    ax.set_ylabel('Number of Pairs with Changes')
    ax.set_title(f'Distribution of Substantive Changes by Section (Arm {arm})\nn={len(pairs_data.get("pairs", []))} drug label pairs')
    ax.set_xticklabels([s.capitalize() for s in sections])
    ax.grid(axis='y', alpha=0.3)
    ax.set_ylim(0, max(counts) * 1.15)

    plt.tight_layout()
    out_path = out_dir / f"fig4_change_distribution_arm{arm}.png"
    plt.savefig(out_path, bbox_inches='tight')
    plt.close()
    logger.info(f"Saved {out_path}")


def main():
    parser = argparse.ArgumentParser(description="Generate benchmark figures")
    parser.add_argument(
        "--arm", type=int, choices=[1, 2], required=True,
        help="Study arm (1=retraction, 2=staleness)",
    )
    args = parser.parse_args()

    # Create output directory
    out_dir = Path("results/figures")
    out_dir.mkdir(parents=True, exist_ok=True)

    logger.info(f"Generating figures for Arm {args.arm}...")

    # Load results
    results = load_results(args.arm)

    # Generate figures
    plot_metrics_comparison(results["metrics"], args.arm, out_dir)
    plot_confusion_matrices(results["metrics"], args.arm, out_dir)
    plot_source_overlap(results["detection"], args.arm, out_dir)
    plot_change_distribution(args.arm, out_dir)

    logger.info(f"All figures saved to {out_dir}")
    logger.info("Done!")


if __name__ == "__main__":
    main()
