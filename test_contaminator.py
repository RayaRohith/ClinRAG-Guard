from src.corpus.contaminator import Contaminator

contaminator = Contaminator(
    clean_dir="data/corpus/clean",
    output_dir="data/corpus/contaminated",
)
records = contaminator.contaminate_all()