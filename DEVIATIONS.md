# Deviations from the pre-registration

Pre-registration: https://osf.io/p84jm (registered 16 Nov 2026).
All changes below were made on 24 Nov 2026, before any results were reported. Results produced before these changes are superseded and are not reported. Commit hashes refer to this repository.

## D1. Arm 2 sample size: 100 pairs planned, 98 analysed
- **Change:** two pairs were excluded.
- **Reason:** after the ordering correction (D2), the clinical-section comparison was recomputed in the correct direction. For two pairs, no section fell below the 0.95 similarity threshold, so they no longer met the definition of a substantive change.
- **Effect:** n = 98 pairs (196 documents). Confidence intervals widen negligibly.
- **Commit:** ac4235c

## D2. Arm 2 pair ordering corrected
- **Planned:** the older label in each pair is outdated, the newer is current.
- **Problem:** version numbers scraped from the DailyMed web page were 0 for every archive, so pairs were left in the page's newest-first order. All 100 pairs were reversed.
- **Change:** pairs re-ordered using each label's own `versionNumber` and `effectiveTime` from its SPL XML. All 200 files were verified against their SHA-256 hashes; no file changed.
- **Effect:** ground truth now matches the plan. Earlier Arm 2 results are invalid.
- **Commits:** fd8e161 (collection code), ac4235c (data repair)

## D3. Version and date metadata recovered
- **Planned:** version-API and date-recency checks compare the indexed label's version and date with DailyMed's latest.
- **Problem:** indexed version and date were missing for every document (see D2), so these checks were not testing what was planned.
- **Change:** values taken from each SPL XML.
- **Effect:** earlier results (version API precision 0.50; date recency flagging nothing) were artefacts.
- **Commit:** ac4235c

## D4. Text diff operationalised without access to labels
- **Planned:** compare clinical sections of an indexed label with the current version.
- **Problem:** the implementation marked any document whose ID ended in "-newer" as current without examining it, and compared outdated documents only with their chosen pair partner. This leaked the ground truth.
- **Change:** each indexed label is compared with the label DailyMed serves at run time; the detector does not see document IDs, file names or labels. Live labels are saved for audit.
- **Effect:** leakage removed. Text diff still uses the same similarity criterion as the ground truth and is reported as a consistency check, not independent evidence.
- **Commit:** b833bb8

## D5. Error analysis based on evidence
- **Planned:** a documented cause for every false negative.
- **Problem:** per-document evidence was not saved, so causes defaulted to a generic category ("subtle_change").
- **Change:** detection now saves per-document evidence; causes are derived from it (for example, the update gap in days for date recency).
- **Commits:** a3384ff (code), 3afd1c1 (results)

## D6. Figures
- **Change:** the figure script did not read the metrics format and produced empty charts. It was corrected to read the actual format, report asymmetric Wilson intervals and include all three methods. The source-overlap Venn diagram was replaced with a bar chart of method combinations, because nested sets made the Venn unreadable.
- **Commits:** baabaf2, 4edb24f

## D7. Manifest paths
- **Change:** file paths are stored relative to the project root instead of as absolute local paths, for portability. All 196 hashes were re-verified.
- **Commits:** 241a0d1, e0f019b

## Not deviations, recorded for transparency
- **Arm 1** has not yet been run; data collection is in progress.
- **October 2026 pilot** (`results/exploratory/october_pilot/`) predates the registration, used a different design and is exploratory only.
- **Additional validation planned:** manual annotation of a random sample of Arm 2 pairs, to provide ground truth independent of the similarity threshold. This was not pre-registered and will be reported as additional analysis.
