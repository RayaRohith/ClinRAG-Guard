# Datasheet: ClinRAG-Guard Evaluation Corpus

Follows the Datasheets for Datasets framework (Gebru et al., 2021).

## Motivation

**Purpose:** We built this corpus to have a controlled test bed for measuring how well automated checks detect retracted papers and outdated drug labels sitting in a clinical retrieval system. There was no existing benchmark for this.

**Creators:** [Your name and affiliation]

**Funding:** [TBD]

## Composition

The corpus has two arms:

### Arm 1: Retraction Detection Corpus
- **300 retracted papers:** Sampled from Retraction Watch database, filtered to retraction nature = "Retraction", PubMed ID exists, open-access CC BY full text via Europe PMC
- **300 control papers:** Matched on journal + publication year, confirmed absent from Retraction Watch, open-access full text available
- **Format:** Pre-retraction versions of full-text XML from Europe PMC (JATS format)
- **Labels:** Binary (RETRACTED / CONTROL), derived from Retraction Watch ground truth

### Arm 2: Staleness Detection Corpus
- **100+ drug label version pairs** from DailyMed (US NLM)
- Each pair: an older version and a newer version with substantive changes in indications, warnings, contraindications, or dosing
- **Format:** SPL XML from DailyMed
- **Labels:** Binary (OUTDATED / CURRENT), where OUTDATED = the older version that has been superseded
- **"Substantive" defined as:** Text similarity ratio < 0.95 in the relevant SPL section (excludes formatting-only and branding-only changes)

### Not included
- NICE content (UK-only licence excludes AI purposes)
- Papers retracted for reasons other than "Retraction" (e.g., expressions of concern)
- Papers without open-access full text

## Collection Process

### Arm 1
1. Load Retraction Watch database (pinned commit, not redistributed)
2. Filter to: nature = "Retraction", PubMed ID exists
3. Check Europe PMC for open-access CC BY full text availability
4. Random sample of 300 (seed = 42) from eligible pool
5. Match each retracted paper to a control: same journal, same publication year, absent from Retraction Watch
6. Download pre-retraction XML from Europe PMC for all 600 papers
7. Record SHA-256 hash, download date, and version metadata in data manifest

### Arm 2
1. Query DailyMed API for drug labels with version history
2. For each drug with multiple versions, download SPL XML for the two most recent versions
3. Extract sections by LOINC code (indications: 34067-9, warnings: 34071-1, contraindications: 34070-3, dosing: 34068-7)
4. Compute text similarity ratio per section; keep pairs where any section has ratio < 0.95
5. Continue until 100+ qualifying pairs collected
6. Record all version metadata and hashes in data manifest

## Preprocessing

- XML text extraction strips all tags (both JATS and SPL formats)
- Text chunked at 512 words with 64-word overlap for indexing
- No tokenisation, stemming, or other NLP preprocessing applied to detection inputs

## Uses

**Intended use:** Benchmarking automated retraction and staleness detection methods for clinical retrieval corpora.

**Not intended for:**
- Training machine learning models
- Clinical decision-making
- Redistribution of Retraction Watch data

## Distribution

- **Code and manifests:** Available in this repository
- **Retraction Watch data:** NOT redistributed. Users must obtain the database independently. Only IDs, DOIs, and PubMed IDs are stored.
- **Europe PMC articles:** Open-access CC BY. Downloaded XML archived with SHA-256 hashes for verification.
- **DailyMed labels:** US NLM public data, freely available.

## Maintenance

- The corpus is a fixed snapshot for this evaluation. It is not updated.
- The Retraction Watch commit and all download dates are recorded in the data manifest.
- If replication is attempted, results may differ if papers have been further retracted/unretracted or labels further updated since the snapshot date.

## Ethical Considerations

Everything in this corpus is already public: open-access papers and public drug labels. There is no patient data, no personal health information, and no human subjects involvement — we are evaluating documents, not people. Retraction status is a matter of public record. We deliberately do not name individual authors of retracted papers in any of our analysis.
