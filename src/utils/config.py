"""
Central configuration — paths, API endpoints, sampling parameters, and
constants. Everything tunable lives in this one file so the study stays
reproducible from a single point.
"""

from pathlib import Path

# ── Project root ──────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# ── Data directories ──────────────────────────────────────────
DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"                   # downloaded full-text PDFs / XML
PROCESSED_DIR = DATA_DIR / "processed"       # cleaned plain-text versions
RETRACTION_DIR = DATA_DIR / "retractions"    # retracted + control papers
DAILYMED_DIR = DATA_DIR / "dailymed"         # drug label version pairs
MANIFEST_DIR = DATA_DIR / "manifests"        # provenance manifests (JSON)
INDEX_DIR = DATA_DIR / "index"               # ChromaDB persistent store

# ── Results ───────────────────────────────────────────────────
RESULTS_DIR = PROJECT_ROOT / "results"
DETECTION_RESULTS_DIR = RESULTS_DIR / "detection"
EVALUATION_RESULTS_DIR = RESULTS_DIR / "evaluation"

# ── Sampling parameters ───────────────────────────────────────
# Arm 1: Retraction detection
N_RETRACTED = 300          # retracted papers to sample
N_CONTROLS = 300           # matched controls (same journal + year, not retracted)
RETRACTION_WATCH_FILTERS = {
    "nature": "Retraction",       # only full retractions, not corrections/concerns
    "has_pmid": True,             # must have PubMed ID for cross-referencing
    "open_access": True,          # CC BY full text available via Europe PMC
}

# Arm 2: Staleness detection
N_DAILYMED_PAIRS = 100     # minimum drug label version pairs
DAILYMED_CHANGE_SECTIONS = [
    "indications",
    "warnings",
    "contraindications",
    "dosing",
]

# ── API endpoints ─────────────────────────────────────────────
EUROPE_PMC_API = "https://www.ebi.ac.uk/europepmc/webservices/rest"
PUBMED_ENTREZ_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
CROSSREF_API = "https://api.crossref.org/works"
DAILYMED_API = "https://dailymed.nlm.nih.gov/dailymed/services/v2"

# Rate limiting (requests per second) — be a good API citizen
EUROPE_PMC_RPS = 3
PUBMED_RPS = 3       # 3/s without API key, 10/s with
CROSSREF_RPS = 10    # polite pool with mailto header
DAILYMED_RPS = 5

# ── Indexing (single pipeline — not the variable under test) ──
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
CHROMA_COLLECTION = "clinrag_guard"
CHUNK_SIZE = 512
CHUNK_OVERLAP = 64

# ── Detection sources ─────────────────────────────────────────
DETECTION_SOURCES = ["text_analysis", "pubmed", "crossref", "combined", "naive_baseline"]

# ── Evaluation ────────────────────────────────────────────────
CONFIDENCE_LEVEL = 0.95    # for Wilson score intervals
RANDOM_SEED = 42           # reproducibility

# ── Ensure directories exist ──────────────────────────────────
def to_relative(path) -> str:
    """Store paths relative to the project root (POSIX style) so manifests are portable."""
    if not path:
        return ""
    p = Path(path)
    if not p.is_absolute():
        return p.as_posix()
    try:
        return p.resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return p.as_posix()


def resolve_path(path) -> Path:
    """Turn a stored (possibly relative) path back into an absolute one."""
    p = Path(path)
    return p if p.is_absolute() else PROJECT_ROOT / p


def ensure_dirs():
    """Create all data/results directories if they don't exist."""
    for d in [
        RAW_DIR, PROCESSED_DIR, RETRACTION_DIR, DAILYMED_DIR,
        MANIFEST_DIR, INDEX_DIR, RESULTS_DIR, DETECTION_RESULTS_DIR,
        EVALUATION_RESULTS_DIR,
    ]:
        d.mkdir(parents=True, exist_ok=True)
