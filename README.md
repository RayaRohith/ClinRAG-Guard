# ClinRAG-Guard

A pre-registered benchmark of how well automated checks detect retracted papers and outdated drug labels in a clinical retrieval (RAG) corpus.

**Pre-registration:** https://osf.io/p84jm (16 Nov 2026)
**Status:** Arm 2 (staleness) complete. Arm 1 (retraction) in data collection.

## Arm 2 results

98 DailyMed drug-label version pairs (196 documents). The older label in each pair is outdated; ground truth is a substantive change (similarity below 0.95) in indications, warnings, contraindications or dosing.

| Method | Precision [95% CI] | Recall [95% CI] | F1 |
|---|---|---|---|
| Version API | 0.990 [0.945, 0.998] | 1.000 [0.962, 1.000] | 0.995 |
| Date recency (365 days) | 1.000 [0.951, 1.000] | 0.765 [0.672, 0.838] | 0.867 |
| Text diff (vs live label) | 1.000 [0.962, 1.000] | 1.000 [0.962, 1.000] | 1.000 |

Wilson score intervals. Figures in `results/figures/`.

- A one-year date rule missed 23% of outdated labels; all were superseded within a year (median 53 days).
- Version checks missed none. Their one false positive was a label updated again after collection.
- Text diff uses the same criterion as the ground truth, so its score is a consistency check, not independent evidence. Manual validation is under way.

## Design

- **Arm 1:** 300 retracted papers (Retraction Watch) and 300 matched controls, indexed as originally published; five detection sources (text, PubMed, Crossref, combined, naive baseline).
- **Arm 2:** label pairs ordered by each label's own version and date; three detection sources.
- Detectors see only what a real pipeline would: the indexed document and its identifier, never its label.

## Corrections

The first Arm 2 run was invalid: pairs were reversed, version and date metadata were missing, and text diff read the label from document IDs. These were fixed on 24 Nov 2026 before results were finalised (n reduced from 100 to 98). See `DEVIATIONS.md` and the commit history.

## Reproduce

```bash
pip install -r requirements.txt
python -m scripts.run_sampling --arm 2
python -m scripts.run_detection --manifest data/manifests/corpus_manifest.json --arm 2
python -m scripts.run_evaluation --manifest data/manifests/corpus_manifest.json --detection results/evaluation/detection_arm2.json --arm 2
python -m scripts.generate_figures --arm 2
```

Arm 1 requires the Retraction Watch database, which must be obtained independently. Version API and text diff query DailyMed live, so results can change as labels are updated.

## Limitations

- The 0.95 similarity threshold is direction-sensitive and fragile.
- The sample includes repackager and homeopathic labels, not only prescription drugs.
- Results reflect DailyMed as queried on 24 Nov 2026.

## Data

Retraction Watch data is not redistributed; only IDs and DOIs are stored. DailyMed labels are US NLM public data. Document provenance and SHA-256 hashes are in `data/manifests/`. See `DATASHEET.md`.

Development used AI coding assistance (Claude). The research design, methodology, analysis and interpretation are my own.
