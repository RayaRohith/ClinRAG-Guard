# ClinRAG-Guard

**Measuring Retraction and Staleness Detection Gaps in Clinical RAG Corpora**

A benchmark study that tests how well automated checks actually catch retracted papers and outdated drug labels sitting in a clinical retrieval corpus.

## Motivation

Healthcare RAG systems can silently serve retracted papers and outdated drug labels — and the scale of the problem is not hypothetical. Xu et al. (BMJ 2025) found 1,330 retracted trials cited in systematic reviews, with 68 of those reviews (whose conclusions changed post-retraction) feeding into 157 guideline documents. Labenbacher et al. (JMIR 2026) tested nine AI tools and none reliably flagged retracted articles. Despite this, nobody has run a controlled evaluation of retraction *and* staleness detection together within a clinical retrieval corpus. That is what this project does.

## Key Findings (Arm 2: Staleness Detection)

| Method | Precision | Recall | F1 | n |
|--------|-----------|--------|-----|---|
| **Text diff** | **1.000** [0.963, 1.000] | **1.000** [0.963, 1.000] | **1.000** [0.963, 1.000] | 100 |
| Version API | 0.500 [0.431, 0.569] | 1.000 [0.963, 1.000] | 0.667 [0.596, 0.725] | 200 |
| Date recency | 0.000 | 0.000 | 0.000 | 0 |

**Finding:** Content-based text comparison (comparing clinical sections of old vs. new versions) achieves perfect precision and recall. Metadata-only version checks achieve 100% recall but produce high false positive rates (flags all current documents as outdated). Date recency checks fail entirely for recent version pairs.

## Study Design

### Arm 1: Retraction Detection
- 300 retracted papers from Retraction Watch + 300 matched controls
- Pre-retraction versions indexed (as originally published, no "RETRACTED" watermarks)
- Five detection sources: text analysis, PubMed check, Crossref check, combined (union/intersection), naive baseline

### Arm 2: Staleness Detection
- 100+ drug label version pairs from DailyMed
- Older version indexed; newer version with substantive clinical changes serves as ground truth
- Substantive = change in indications, warnings, contraindications, or dosing (not formatting-only)

### Metrics
- Precision, Recall, F1 with 95% Wilson score confidence intervals
- Source overlap analysis (Venn: flagged by 1, 2, or all 3 sources; flagged by none)
- Error analysis: documented cause category for every false negative
- Coverage gap: proportion of confirmed retractions with no Crossref/PubMed record update

## Setup

```bash
pip install -r requirements.txt
```

## Usage

### 1. Data Collection

Requires the Retraction Watch database (not redistributable — obtain independently):

```bash
# Arm 1: Sample retracted papers and controls
python -m scripts.run_sampling --arm 1 --rw-path path/to/retraction_watch.csv

# Arm 2: Collect drug label version pairs
python -m scripts.run_sampling --arm 2
```

### 2. Run Detection

```bash
# Arm 1: Run all detection sources on retraction corpus
python -m scripts.run_detection --manifest data/manifest.json --arm 1

# Arm 2: Run staleness detection
python -m scripts.run_detection --manifest data/manifest.json --arm 2
```

### 3. Evaluate

```bash
# Compute metrics, overlap analysis, error analysis
python -m scripts.run_evaluation --manifest data/manifest.json --detection data/results/detection_arm1.json --arm 1
python -m scripts.run_evaluation --manifest data/manifest.json --detection data/results/detection_arm2.json --arm 2
```

## Repository Structure

```
ClinRAG-Guard/
  src/
    data/                   # Data collection and provenance
      retraction_sampler.py   # Sample retracted papers + matched controls
      dailymed_versions.py    # Collect drug label version pairs
      manifest.py             # Data provenance tracking
    detection/              # Five detection sources
      text_analyzer.py        # (a) Pattern-based text scan
      pubmed_checker.py       # (b) PubMed retraction status
      crossref_checker.py     # (c) Crossref retraction notices
      combined.py             # (d) Union and intersection
      naive_baseline.py       # (e) Simple PubMed lookup
    indexing/
      pipeline.py             # LangChain + ChromaDB + MiniLM
    evaluation/
      metrics.py              # P, R, F1 with Wilson CIs
      overlap_analysis.py     # Source overlap Venn analysis
      error_analysis.py       # False negative categorisation
  scripts/
    run_sampling.py           # Orchestrate data collection
    run_detection.py          # Run all detection sources
    run_evaluation.py         # Compute metrics and reports
  osf_registration.md         # Pre-registration text
  DATASHEET.md                # Dataset documentation
  OPEN_LEGAL_QUESTIONS.md     # Regulatory framing
```

## Design Choices Worth Explaining

**We index pre-retraction versions.** If you index the current version of a retracted paper, it often has a "RETRACTED" watermark stamped across it — detection becomes trivially easy. The realistic contamination scenario is a corpus that ingested the paper *before* the retraction was issued, so that is what we test against.

**Ground truth and detection sources are not fully independent.** Retraction Watch data has been distributed through Crossref since January 2023, so our Crossref detection source and our ground truth share provenance. PubMed markings also trace back to publisher notices. We quantify this overlap explicitly rather than pretending the sources are independent probes.

**Single pipeline configuration.** The pipeline (LangChain + ChromaDB + MiniLM) exists to give detection a realistic context, not as a variable under test. We deliberately hold it fixed.

**Wilson score CIs over normal approximation.** Some detection sources will likely have recall near 0 or 1, where the normal approximation breaks down. Wilson intervals behave properly across the full range.

## Related Work

| Project | What it does | Gap we address |
|---------|-------------|----------------|
| compass-kb-validation | 73 generic data quality checks | No clinical or retraction awareness |
| VERIRAG | Audits statistical rigour | Evaluated on simulated perturbations, not retraction/staleness |
| HCF | Contradiction detection | No retraction focus |
| Pub-Guard-LLM | Classifies retraction risk from abstracts (11K benchmark) | Article-level classification, not corpus integrity in a deployed pipeline |

## Data Availability

The Retraction Watch database cannot be redistributed — we store only IDs, DOIs, and PubMed IDs. Users must obtain the database independently. Europe PMC articles are open-access CC BY; we archive the downloaded XML with SHA-256 hashes. DailyMed labels are US NLM public data, freely available.

## Licence

[TBD]
