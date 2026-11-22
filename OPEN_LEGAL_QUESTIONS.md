# Open Legal Questions

This document frames the regulatory implications of our findings as open questions, not compliance claims. We provide technical evidence that any future regulatory framing would need, without resolving which interpretation applies.

## Why We Frame These as Open Questions

Whether a RAG corpus counts as "input data" under EU AI Act Article 10 is genuinely unresolved. Asserting a specific compliance mapping would overstate what anyone currently knows. Instead, we identify three questions that our technical findings speak to, and leave their legal resolution to the people qualified to resolve them.

## 1. Does a RAG Corpus Fall Under Article 10?

EU AI Act Article 10 imposes quality requirements on "training, validation and testing datasets." A RAG knowledge base is not training data in the traditional ML sense — it is queried at inference time. So does Article 10 apply to it?

Our study does not answer this, but the findings are relevant regardless of the classification. We show that clinical RAG corpora can contain retracted papers and outdated drug labels without any automated detection catching them, and that the detection sources available today have measurable gaps. Even if Article 10 ends up not applying to RAG corpora, the finding that retracted content silently persists in clinical knowledge bases raises obvious questions about the duty of care expected of system operators.

## 2. Who Is Responsible When a RAG System Serves a Retracted Paper?

If a clinician receives a retracted paper from a RAG system, the chain of responsibility is unclear. The system operator chose (or failed to choose) detection checks. The corpus curator decided which sources to index. The original publisher may have been slow to issue the retraction notice. The database aggregators (Crossref, PubMed) may not have propagated the notice yet.

Our overlap analysis is directly relevant here. We show that different detection sources catch different subsets of problematic documents, and that some retracted papers have no Crossref record *and* no PubMed update — making them invisible to API-based checks. Text analysis provides an independent signal, but cannot catch papers whose pre-retraction text contains no warning language. The coverage gap (documents missed by *all* detection sources) is a measurable quantity, which means "we ran checks" is not the same as "we caught everything." Any duty-of-care framework would need to specify which checks are considered reasonable, and our data quantifies what each combination achieves.

## 3. What Should Happen During the Retraction Lag?

There is always a delay between when a paper is retracted by its publisher and when that retraction shows up in databases and downstream corpora. During this lag, a RAG system may serve the retracted paper and no detection source can flag it.

Our data shows this lag is not uniform. Some retractions appear in all databases within days; others take months or longer. The lag varies by publisher, by database, and by the specific paper. If a regulatory framework requires corpus content to be "current," it would need to define what "current" means in terms of acceptable lag — and our coverage gap analysis provides the empirical basis for that conversation.

---

**What we do not claim:** We do not resolve whether Article 10 applies to RAG corpora. We do not propose a regulatory classification. We do not say any particular detection configuration is "compliant." This is technical evidence, not legal advice.

**What we do provide:** Empirical measurements of detection gaps in a controlled setting; a reproducible benchmark others can build on; and quantified coverage data showing what each detection source catches and misses — the kind of evidence any regulatory framing would eventually need to draw on.
