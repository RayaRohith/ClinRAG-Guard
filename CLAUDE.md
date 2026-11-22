# ClinRAG-Guard: Project Brief & Implementation Guide

## What This Project Is

A **controlled evaluation** (benchmark study) measuring how well automated checks detect retracted and outdated sources in clinical retrieval corpora. This is NOT a deployed guard or monitor -- it is an empirical study that produces evidence about detection gaps.

**One-line pitch:** "Healthcare RAG systems can silently serve retracted papers and outdated drug labels. We built a controlled test to measure what automated checks actually catch -- and what they miss."

## Why This Matters

- 1,330 retracted trials were cited in systematic reviews; 68 reviews whose conclusions changed were cited in 157 guideline documents (Xu et al., BMJ 2025)
- None of nine AI tools reliably flagged retracted articles (Labenbacher et al., JMIR 2026)
- No existing work provides a controlled evaluation of retraction AND staleness detection specifically within a clinical retrieval corpus

## What Changed From the Original Design (and Why)

The project was revised based on the CDT Responsible NLP Field Guide and expert feedback. These are the major changes:

### 1. Reframed from "guard system" to "controlled evaluation"
- **Before:** Building a deployable monitoring tool
- **After:** Building a benchmark study with controlled test corpus
- **Why:** A benchmark is publishable, reproducible, and more credible for a PhD application. A deployed tool without clinical users is vapourware.

### 2. Ground truth independence caveat added
- **Problem:** Retraction Watch data has been distributed through Crossref since January 2023. So our ground truth (Retraction Watch) and detection source (c) Crossref share provenance. PubMed markings also originate from publisher notices.
- **Solution:** Frame these as "signals a real pipeline could query at ingest time," NOT independent probes. Quantify the overlap explicitly. The absence of a signal (confirmed retraction with no Crossref record) is itself a finding.

### 3. Must index PRE-RETRACTION versions
- **Before:** Indexing current versions of papers
- **After:** Must index the version as originally published
- **Why:** Current versions may carry "RETRACTED" watermarks, making detection trivially easy. The realistic contamination scenario is a corpus that ingested the paper BEFORE the retraction was issued.

### 4. Staleness arm expanded from 20-30 to 100+
- **Before:** 20-30 drug label pairs (underpowered)
- **After:** 100+ pairs from DailyMed version history
- **Why:** At n=20, confidence intervals are too wide to draw any conclusion. At n=100, recall of 0.70 gives CI of ~plus/minus 0.09, which is usable.

### 5. Regulatory framing changed to "open legal questions"
- **Before:** Claiming direct compliance mapping to EU AI Act Article 10
- **After:** Presenting as open legal questions
- **Why:** Whether a RAG corpus is "input data" under Article 10 is genuinely unresolved. Overclaiming legal mappings undermines credibility. We provide technical evidence any framing would require, without resolving which applies.

### 6. Related work positioning sharpened
- compass-kb-validation: 73 generic checks, no clinical/retraction awareness
- VERIRAG: Audits statistical rigour, not retraction/staleness; evaluated on simulated perturbations
- HCF: Contradiction detection, no retraction focus
- Pub-Guard-LLM: Classifies retraction risk from abstract text at article level with 11K benchmark; does not evaluate corpus integrity in a deployed pipeline. We build on it, not duplicate it.

### 7. NICE content removed, DailyMed only
- **Why:** NICE has a UK-only licence that excludes AI purposes. DailyMed is US NLM public data, freely available.

## Study Design

### Arm 1: Retraction Detection
- 300 retracted papers from Retraction Watch (pinned commit), filtered to: nature="Retraction", PubMed ID exists, open-access CC BY full text in Europe PMC
- 300 control papers matched on journal + publication year, confirmed absent from Retraction Watch
- Index the **pre-retraction version** (as originally published)

### Arm 2: Staleness Detection
- 100+ drug label pairs from DailyMed version history
- Newer version has substantive change in indications, warnings, contraindications, or dosing
- NOT formatting-only or branding-only updates
- Index the older version; newer version = ground truth

## Detection Sources

| Source | What it does | Independence note |
|--------|-------------|-------------------|
| (a) Text analysis | Pattern-based scan of document text for retraction signals | Independent of ground truth |
| (b) PubMed check | Query PubMed publication-type filter for "Retracted Publication" | Shares provenance with publisher notices |
| (c) Crossref check | Query Crossref API for retraction/correction notices via DOI | Shares provenance with Retraction Watch since Jan 2023 |
| (d) Combined | Union (any flags) and intersection (all flag) of a+b+c | Composite |
| (e) Naive baseline | Exact DOI/title lookup against PubMed retracted-publication filter | Floor benchmark |

## Pipeline (NOT the variable under test)

Single configuration -- detection operates on document metadata/text, pipeline provides realistic context:
- **Framework:** LangChain
- **Vector store:** ChromaDB
- **Embeddings:** sentence-transformers/all-MiniLM-L6-v2

## Metrics

**Primary:** Precision, Recall, F1 with 95% Wilson score confidence intervals per detection source

**Secondary:**
- Source overlap analysis (Venn: flagged by 1, 2, or all 3 sources; flagged by none)
- Error analysis: documented cause category for every false negative
- Coverage gap: proportion of confirmed retractions with no Crossref/PubMed record update

## Target Repository Structure

```
ClinRAG-Guard/
  CLAUDE.md                    <-- this file
  README.md
  DATASHEET.md                 <-- dataset documentation
  OPEN_LEGAL_QUESTIONS.md      <-- regulatory framing
  osf_registration.md          <-- pre-registration text
  requirements.txt
  src/
    __init__.py
    data/
      __init__.py
      retraction_sampler.py    <-- sample 300 retracted + 300 controls from Retraction Watch + Europe PMC
      dailymed_versions.py     <-- collect 100+ drug label pairs with substantive changes
      manifest.py              <-- record document ID, source, version, date, hash for every document
    detection/
      __init__.py
      text_analyzer.py         <-- pattern-based retraction signal detection in document text
      pubmed_checker.py        <-- query PubMed for retracted-publication status
      crossref_checker.py      <-- query Crossref API for retraction notices
      combined.py              <-- union and intersection logic
      naive_baseline.py        <-- DOI/title lookup against PubMed filter
    indexing/
      __init__.py
      pipeline.py              <-- LangChain + ChromaDB + MiniLM indexing
    evaluation/
      __init__.py
      metrics.py               <-- precision, recall, F1, Wilson CIs
      overlap_analysis.py      <-- source overlap Venn analysis
      error_analysis.py        <-- false negative categorisation
    utils/
      __init__.py
      config.py                <-- paths, API keys, constants
  data/                        <-- generated CSVs (gitignored except samples)
  scripts/
    run_sampling.py            <-- orchestrate data collection
    run_detection.py           <-- run all detection sources
    run_evaluation.py          <-- compute metrics and generate reports
  tests/
    test_retraction_sampler.py
    test_pubmed_checker.py
    test_crossref_checker.py
    test_metrics.py
```

## Implementation Order (Build Sequence)

### Phase 1: Data Collection (build first)
1. `src/utils/config.py` -- paths, constants, API endpoints
2. `src/data/retraction_sampler.py` -- download Retraction Watch, filter, sample 300, match 300 controls
3. `src/data/dailymed_versions.py` -- query DailyMed API, find version pairs with substantive changes
4. `src/data/manifest.py` -- log every document with ID, source, version date, file hash
5. `scripts/run_sampling.py` -- orchestrate the above

### Phase 2: Indexing
6. `src/indexing/pipeline.py` -- index pre-retraction versions and older drug labels into ChromaDB

### Phase 3: Detection
7. `src/detection/text_analyzer.py` -- regex/pattern-based scan for retraction language
8. `src/detection/pubmed_checker.py` -- Entrez API query for retraction status
9. `src/detection/crossref_checker.py` -- Crossref works API for update-type:retraction
10. `src/detection/naive_baseline.py` -- simple DOI lookup
11. `src/detection/combined.py` -- union/intersection logic

### Phase 4: Evaluation
12. `src/evaluation/metrics.py` -- precision, recall, F1, Wilson score CIs
13. `src/evaluation/overlap_analysis.py` -- pairwise and 3-way source overlap
14. `src/evaluation/error_analysis.py` -- categorise every false negative
15. `scripts/run_detection.py` and `scripts/run_evaluation.py`

### Phase 5: Documentation
16. README.md, DATASHEET.md, OPEN_LEGAL_QUESTIONS.md

## Key Constraints to Remember

- **Retraction Watch DB cannot be redistributed** -- store only IDs, DOIs, PubMed IDs. Users must obtain the database independently.
- **Pre-retraction versions required** -- use Europe PMC for the version as originally published, NOT current versions with RETRACTED watermarks.
- **"Outdated" is operationally defined** -- superseded SPL version where indications, warnings, contraindications, or dosing changed in substance. NOT formatting-only.
- **Single pipeline config** -- we are not testing retrieval quality. The pipeline provides context; detection sources are the variable.
- **Wilson score intervals** -- not normal approximation. Wilson is more accurate for proportions near 0 or 1.

## What Exists vs What Needs Building

The existing codebase has modules from an earlier design (deployed monitor approach). When reviewing existing code:

**Likely reusable (check and adapt):**
- Any ChromaDB/LangChain indexing code
- Any PubMed API querying code
- Basic project structure and config

**Likely needs replacing:**
- Anything framed as "monitoring" or "real-time checking"
- Compliance scoring or dashboard code
- NICE-specific content handling
- Any code that indexes current (post-retraction) versions of papers

**New modules to build from scratch:**
- retraction_sampler.py (Retraction Watch sampling + control matching)
- dailymed_versions.py (DailyMed version pair collection)
- manifest.py (data provenance tracking)
- text_analyzer.py (pattern-based retraction signal detection)
- crossref_checker.py (Crossref API retraction notice check)
- naive_baseline.py (floor benchmark)
- overlap_analysis.py (Venn analysis of detection sources)
- error_analysis.py (false negative categorisation)
- metrics.py (Wilson score CIs)

## Application Context

- **Primary target:** CDT Responsible NLP at Edinburgh (Stage 1 deadline: November 30, 2026)
- **Supervisor targets:** Stuart Anderson (lead), Robin Williams (natural second), Lachlan Urquhart (law angle)
- **OSF pre-registration:** Submitted November 2026 [paste link here]
- **Career direction:** AI assurance for safety-critical systems; healthcare as proving ground, transferable to CERN/space/nuclear
