"""
One-off repair of the Arm 2 DailyMed pairs collected on 16 Nov 2026.

Problem: pairs were ordered using version numbers scraped from the DailyMed
web page. The scrape returned version 0 for every archive, so the sort did
nothing and the page's newest-first order was used. Every pair was reversed:
the file labelled "older" was the newer label, and vice versa.

Fix: read each label's own <versionNumber> and <effectiveTime> from its SPL
XML (the authoritative source), put every pair in true chronological order,
recompute the clinical-section comparison in the correct direction, check
file hashes, and rebuild both manifests. No files are re-downloaded.

Usage (from the project root):
    python -m scripts.repair_dailymed_pairs --dry-run   # report only
    python -m scripts.repair_dailymed_pairs             # write manifests
"""

import argparse
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data.dailymed_versions import DailyMedVersionCollector, DrugLabelPair
from src.data.manifest import DataManifest

PAIRS_PATH = Path("data/manifests/dailymed_pairs.json")


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--dry-run", action="store_true", help="report only, write nothing")
    args = ap.parse_args()

    data = json.loads(PAIRS_PATH.read_text(encoding="utf-8"))
    raw_pairs = data["pairs"]
    collector = DailyMedVersionCollector()

    repaired, problems = [], []
    swapped = unchanged = 0
    sections_changed = 0

    for p in raw_pairs:
        # 1. Integrity: files must be exactly what was collected.
        for side in ("older", "newer"):
            if sha256(p[f"{side}_path"]) != p[f"{side}_hash"]:
                problems.append(f"{p['pair_id']}: {side} file hash mismatch")

        # 2. True metadata from inside each label.
        meta_o = collector.read_spl_metadata(p["older_path"])
        meta_n = collector.read_spl_metadata(p["newer_path"])
        if 0 in (meta_o[0], meta_n[0]) or "" in (meta_o[1], meta_n[1]):
            problems.append(f"{p['pair_id']}: missing metadata {meta_o} / {meta_n}")
            continue
        if meta_o == meta_n:
            problems.append(f"{p['pair_id']}: both files have the same version {meta_o}")
            continue

        # 3. Put the pair in true chronological order.
        if meta_o > meta_n:
            swapped += 1
            old = {k: p[f"newer_{k}"] for k in ("spl_id", "path", "hash")}
            new = {k: p[f"older_{k}"] for k in ("spl_id", "path", "hash")}
            (old_ver, old_date), (new_ver, new_date) = meta_n, meta_o
        else:
            unchanged += 1
            old = {k: p[f"older_{k}"] for k in ("spl_id", "path", "hash")}
            new = {k: p[f"newer_{k}"] for k in ("spl_id", "path", "hash")}
            (old_ver, old_date), (new_ver, new_date) = meta_o, meta_n

        # 4. Recompute the clinical comparison in the correct direction.
        changed, summary = collector.compare_versions(
            collector.extract_sections(old["path"]),
            collector.extract_sections(new["path"]),
        )
        if sorted(changed) != sorted(p.get("changed_sections") or []):
            sections_changed += 1
        if not changed:
            problems.append(f"{p['pair_id']}: no substantive change after reordering")
            continue

        repaired.append(DrugLabelPair(
            pair_id=f"DM-{p['set_id']}-v{old_ver}-v{new_ver}",
            drug_name=p["drug_name"],
            set_id=p["set_id"],
            older_spl_id=old["spl_id"], older_version=old_ver, older_date=old_date,
            older_path=old["path"], older_hash=old["hash"],
            newer_spl_id=new["spl_id"], newer_version=new_ver, newer_date=new_date,
            newer_path=new["path"], newer_hash=new["hash"],
            changed_sections=changed, change_summary=summary,
        ))

    print(f"pairs in file:          {len(raw_pairs)}")
    print(f"swapped (were reversed): {swapped}")
    print(f"already correct:         {unchanged}")
    print(f"changed-section sets differ after recompute: {sections_changed}")
    print(f"valid repaired pairs:    {len(repaired)}")
    print(f"problems:                {len(problems)}")
    for msg in problems[:20]:
        print("  -", msg)
    if repaired:
        r = repaired[0]
        print(f"example: {r.drug_name[:40]} | v{r.older_version} ({r.older_date})"
              f" -> v{r.newer_version} ({r.newer_date}) | {r.change_summary}")

    if args.dry_run:
        print("\nDry run: nothing written.")
        return

    from dataclasses import asdict
    data.update({
        "n_pairs": len(repaired),
        "repaired_at": datetime.now().isoformat(),
        "repair_note": (
            "Pairs re-ordered by SPL versionNumber/effectiveTime read from each XML; "
            f"{swapped} of {len(raw_pairs)} were reversed in the 16 Nov 2026 collection. "
            "File names ending _old/_new reflect the original (incorrect) labels; "
            "the older_*/newer_* fields here are authoritative."
        ),
        "pairs": [asdict(r) for r in repaired],
    })
    PAIRS_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")

    manifest = DataManifest()
    manifest.add_dailymed_pairs(repaired)
    out = manifest.save()
    print(f"\nWrote {PAIRS_PATH} and {out}")
    print("Summary:", manifest.summary())


if __name__ == "__main__":
    main()
