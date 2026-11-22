# ClinRAG-Guard: Pre-Registration

> **Status:** DRAFT — update incrementally as implementation progresses.
> **OSF link:** [paste link here once submitted]

---

## 1. Title

Measuring Retraction and Staleness Detection Gaps in Clinical Retrieval-Augmented Generation Corpora

## 2. Authors

[Your name and affiliation]

## 3. Research Question

Can automated detection methods reliably identify retracted papers and outdated drug labels within a clinical RAG knowledge base, and what detection gaps remain when multiple sources are combined?

### 3.1 Hypotheses

**H1 (Retraction detection):** A combined detection approach (text analysis + PubMed status + Crossref retraction notices) will achieve higher recall than any individual source alone, but will still miss a non-trivial proportion of retracted papers (estimated recall < 0.90 for the combined source).

**H2 (Staleness detection):** Automated comparison of indexed drug label versions against the current DailyMed version will detect substantive clinical changes in ≥70% of cases, with detection varying by change type (warnings > dosing > indications > contraindications).

**H3 (Independence):** Detection sources that share provenance with the ground truth (PubMed publication-type, Crossref retraction notices) will show correlated true-positive rates, while text analysis will provide genuinely independent signal.

## 4. Study Design

### 4.1 Overview

A controlled evaluation (benchmark study) measuring how well automated checks detect retracted and outdated sources in a clinical retrieval corpus. Two study arms:

- **Arm 1 (Retraction Detection):** 300 retracted papers + 300 matched controls
- **Arm 2 (Staleness Detection):** 100+ drug label version pairs with substantive changes

### 4.2 Arm 1: Retraction Detection

**Corpus construction:**
- Sample 300 retracted papers from Retraction Watch database (pinned commit), filtered to: retraction nature = "Retraction" (not expressions of concern), PubMed ID exists, open-access CC BY full text available via Europe PMC
- Match 300 control papers: same journal + publication year, confirmed absent from Retraction Watch, open-access full text available
- Index the **pre-retraction version** (as originally published via Europe PMC) — NOT the current version which may carry "RETRACTED" watermarks

**Detection sources:**

| Source | Method | Independence from ground truth |
|--------|--------|-------------------------------|
| (a) Text analysis | Pattern-based scan for retraction signals in document text | Independent |
| (b) PubMed check | Query PubMed publication-type filter for "Retracted Publication" | Shares provenance with publisher notices |
| (c) Crossref check | Query Crossref API for retraction/correction notices via DOI | Shares provenance with Retraction Watch since Jan 2023 |
| (d) Combined (union) | Any of a, b, c flags the document | Composite |
| (e) Naive baseline | Exact DOI/title lookup against PubMed retracted-publication filter | Floor benchmark |

**Ground truth:** Retraction Watch database entry = retracted; absence from Retraction Watch + control matching = not retracted.

**Key caveat (ground truth independence):** Retraction Watch data has been distributed through Crossref since January 2023, so detection source (c) and the ground truth share provenance. PubMed markings also originate from publisher notices. We frame these as "signals a real pipeline could query at ingest time" and quantify the overlap explicitly.

### 4.3 Arm 2: Staleness Detection

**Corpus construction:**
- Collect 100+ drug label version pairs from DailyMed (US NLM) where the newer version has substantive changes in: indications, warnings, contraindications, or dosing
- "Substantive" operationally defined as: text similarity ratio < 0.95 in the relevant SPL XML section (not formatting-only or branding-only)
- Index the **older version**; newer version serves as ground truth for what changed

**Detection method:**
- Compare indexed (older) label text against current DailyMed version
- Section-level change detection using the same SPL LOINC codes
- Binary outcome per pair: detected as outdated or not

### 4.4 Retrieval Pipeline

Single configuration — the pipeline is NOT the variable under test. Detection operates on document metadata and text; the pipeline provides realistic retrieval context.

- **Framework:** LangChain
- **Vector store:** ChromaDB (persistent)
- **Embeddings:** sentence-transformers/all-MiniLM-L6-v2
- **Chunk size:** 512 tokens, 64-token overlap

## 5. Sampling Plan

### 5.1 Sample size justification

- **Arm 1 (n=300 retracted + 300 controls):** At n=300, recall of 0.70 gives a 95% Wilson score CI of approximately ±0.05, which is sufficient to distinguish between detection sources.
- **Arm 2 (n=100+ pairs):** At n=100, recall of 0.70 gives a 95% Wilson CI of approximately ±0.09, which is usable for characterising detection performance by change type.

### 5.2 Stopping rule

Data collection stops when N_RETRACTED (300) retracted papers with available full text have been sampled and N_DAILYMED_PAIRS (100) drug label pairs with substantive changes have been collected. If fewer are available after exhausting the eligible pool, the actual count is reported.

### 5.3 Random seed

All random operations use seed = 42 for reproducibility.

## 6. Variables

### 6.1 Independent variables
- Detection source (text analysis, PubMed, Crossref, combined, naive baseline)
- Document type (retracted paper, control paper, outdated label, current label)
- Change type for Arm 2 (indications, warnings, contraindications, dosing)

### 6.2 Dependent variables
- True positive, false positive, true negative, false negative counts
- Precision, recall, F1 per detection source
- Source overlap (flagged by 1, 2, or all 3 sources; flagged by none)

## 7. Analysis Plan

### 7.1 Primary metrics
- **Precision, Recall, F1** with 95% Wilson score confidence intervals per detection source
- Wilson score intervals (not normal approximation) because they are more accurate for proportions near 0 or 1
- F1 confidence intervals approximated from the Wilson bounds of precision and recall
- Confusion matrix (TP, FP, TN, FN) reported per source

### 7.2 Secondary analyses
- **Source overlap analysis:** For each document, record which combination of sources flagged it. Report: per-source flag counts, pairwise overlap between every pair, 3-way overlap (all sources flag), distribution by number of sources flagging (0, 1, 2, 3), and the coverage gap (positives flagged by no source). Documents uniquely flagged by exactly one source quantify each source's independent contribution.
- **Error analysis:** Every false negative categorised with a documented cause. Categories: `no_crossref_record` (retraction not in Crossref), `no_pubmed_update` (PubMed not updated), `no_text_signal` (pre-retraction text has no retraction language), `no_metadata` (document lacks DOI/PMID for the check), `api_error` (detection source returned an error), `subtle_change` (staleness change too subtle for patterns), `multiple_gaps` (missed by multiple sources for different reasons). Per-source FN cause breakdown reported alongside aggregate distribution.
- **Coverage gap:** Proportion of confirmed retractions that have no Crossref/PubMed record update. This quantifies the ground-truth independence problem.

### 7.3 Analysis not planned
- We do NOT perform statistical significance testing between detection sources because they operate on the same documents (not independent samples).
- We do NOT claim causal relationships between detection method and detection quality.

## 8. Data Availability

- **Retraction Watch database:** Cannot be redistributed. Users must obtain independently. We store only IDs, DOIs, and PubMed IDs.
- **Europe PMC full text:** Open-access CC BY articles. Downloaded XML archived with SHA-256 hashes in the data manifest.
- **DailyMed labels:** US NLM public data, freely available. Downloaded SPL XML archived with hashes.
- **Code and manifests:** Available in the project repository under [licence TBD].

## 9. Regulatory Context (Open Questions)

We deliberately present regulatory implications as open legal questions rather than asserting compliance mappings:

1. **Does a RAG corpus constitute "input data" under EU AI Act Article 10?** — Genuinely unresolved. We provide technical evidence any framing would require, without resolving which applies.
2. **What duty of care applies to corpus maintenance?** — The absence of automated detection in current systems is itself a finding, regardless of the regulatory classification.
3. **How should retraction lag be treated?** — The delay between paper retraction and corpus update is measurable; whether it constitutes a regulatory breach depends on unresolved questions of interpretation.

See `OPEN_LEGAL_QUESTIONS.md` for expanded discussion.

## 10. Timeline

- **November 2026:** Pre-registration, data collection, detection implementation
- **Target submission:** CDT Responsible NLP at Edinburgh (Stage 1 deadline: November 30, 2026)

---

*Last updated: 2026-11-16 — Phase 4 (evaluation) implementation complete*
