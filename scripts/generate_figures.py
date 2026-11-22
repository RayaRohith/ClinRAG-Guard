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


def load_results(arm: int) -> dict:
    """Load all evaluation results for an arm."""
    base_path = EVALUATION_RESULTS_DIR

    with open(base_path / f"metrics_arm{arm}.json", encoding="utf-8") as f:
        metrics = json.load(f)

    with open(base_path / f"overlap_arm{arm}.json", encoding="utf-8") as f:
        overlap = json.load(f)

    with open(base_path / f"error_analysis_arm{arm}.json", encoding="utf-8") as f:
        error_analysis = json.load(f)

    return {
        "metrics": metrics,
        "overlap": overlap,
        "error_analysis": error_analysis,
    }


def plot_metrics_comparison(metrics: dict, arm: int, out_dir: Path):
    """
    Figure 1: Bar chart comparing P/R/F1 across methods with confidence intervals.
    """
    # Filter to main methods (exclude combined for clarity)
    methods = ["version_api", "text_diff", "date_recency"]
    method_labels = {
        "version_api": "Version API",
        "text_diff": "Text Diff",
        "date_recency": "Date Recency",
    }

    # Extract metrics
    data = {
        "Precision": [],
        "Recall": [],
        "F1": [],
    }
    errors = {
        "Precision": [],
        "Recall": [],
        "F1": [],
    }
    labels = []

    for method in methods:
        if method not in metrics:
            continue
        m = metrics[method]
        labels.append(method_labels[method])

        for metric_name in ["precision", "recall", "f1"]:
            value = m[metric_name]
            ci_lower = m[f"{metric_name}_ci_lower"]
            ci_upper = m[f"{metric_name}_ci_upper"]

            # Store value and error (half of CI range)
            data[metric_name.capitalize()].append(value)
            error = (ci_upper - ci_lower) / 2
            errors[metric_name.capitalize()].append(error)

    # Create grouped bar chart
    x = np.arange(len(labels))
    width = 0.25

    fig, ax = plt.subplots(figsize=(8, 5))

    colors = ['#4C72B0', '#55A868', '#C44E52']
    for i, (metric, color) in enumerate(zip(["Precision", "Recall", "F1"], colors)):
        offset = width * (i - 1)
        bars = ax.bar(
            x + offset,
            data[metric],
            width,
            label=metric,
            yerr=errors[metric],
            capsize=4,
            color=color,
            alpha=0.8,
        )

        # Add value labels on bars
        for bar in bars:
            height = bar.get_height()
            if height > 0:
                ax.text(
                    bar.get_x() + bar.get_width() / 2,
                    height + 0.02,
                    f'{height:.2f}',
                    ha='center',
                    va='bottom',
                    fontsize=8,
                )

    ax.set_xlabel('Detection Method')
    ax.set_ylabel('Score')
    ax.set_title(f'Detection Performance Comparison (Arm {arm})')
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.legend()
    ax.set_ylim(0, 1.15)
    ax.grid(axis='y', alpha=0.3)

    plt.tight_layout()
    out_path = out_dir / f"fig1_metrics_comparison_arm{arm}.png"
    plt.savefig(out_path, bbox_inches='tight')
    plt.close()
    logger.info(f"Saved {out_path}")


def plot_confusion_matrices(metrics: dict, arm: int, out_dir: Path):
    """
    Figure 2: Confusion matrices for each detection method.
    """
    methods = ["version_api", "text_diff"]
    method_labels = {
        "version_api": "Version API",
        "text_diff": "Text Diff",
    }

    fig, axes = plt.subplots(1, 2, figsize=(10, 4))

    for idx, method in enumerate(methods):
        if method not in metrics:
            continue

        m = metrics[method]
        tp = m["true_positives"]
        fp = m["false_positives"]
        tn = m["true_negatives"]
        fn = m["false_negatives"]

        cm = np.array([[tn, fp], [fn, tp]])

        ax = axes[idx]
        sns.heatmap(
            cm,
            annot=True,
            fmt='d',
            cmap='Blues',
            cbar=True,
            ax=ax,
            xticklabels=['Predicted\nNegative', 'Predicted\nPositive'],
            yticklabels=['Actual\nNegative', 'Actual\nPositive'],
            square=True,
            linewidths=1,
            linecolor='black',
        )
        ax.set_title(f'{method_labels[method]}\nP={m["precision"]:.2f} R={m["recall"]:.2f}')

    plt.tight_layout()
    out_path = out_dir / f"fig2_confusion_matrices_arm{arm}.png"
    plt.savefig(out_path, bbox_inches='tight')
    plt.close()
    logger.info(f"Saved {out_path}")


def plot_venn_overlap(overlap: dict, arm: int, out_dir: Path):
    """
    Figure 3: Venn diagram showing which documents were flagged by which methods.
    """
    # Get counts from overlap data
    version_api_count = overlap["source_counts"]["version_api"]
    text_diff_count = overlap["source_counts"]["text_diff"]
    both_count = overlap["pairwise_overlap"]["text_diff+version_api"]

    # Calculate unique counts (only flagged by one method)
    version_api_only = version_api_count - both_count
    text_diff_only = text_diff_count - both_count

    fig, ax = plt.subplots(figsize=(8, 6))

    # 2-circle Venn (skip date_recency as it flagged nothing)
    venn = venn2(
        subsets=(version_api_only, text_diff_only, both_count),
        set_labels=('Version API', 'Text Diff'),
        ax=ax,
    )

    # Style the diagram
    if venn.get_patch_by_id('10'):
        venn.get_patch_by_id('10').set_color('#4C72B0')
        venn.get_patch_by_id('10').set_alpha(0.5)
    if venn.get_patch_by_id('01'):
        venn.get_patch_by_id('01').set_color('#55A868')
        venn.get_patch_by_id('01').set_alpha(0.5)
    if venn.get_patch_by_id('11'):
        venn.get_patch_by_id('11').set_color('#8172B2')
        venn.get_patch_by_id('11').set_alpha(0.5)

    ax.set_title(f'Detection Source Overlap (Arm {arm})\nTotal Documents: {overlap["total_documents"]}')

    plt.tight_layout()
    out_path = out_dir / f"fig3_venn_overlap_arm{arm}.png"
    plt.savefig(out_path, bbox_inches='tight')
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
    plot_venn_overlap(results["overlap"], args.arm, out_dir)
    plot_change_distribution(args.arm, out_dir)

    logger.info(f"All figures saved to {out_dir}")
    logger.info("Done!")


if __name__ == "__main__":
    main()
