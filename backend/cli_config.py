from pathlib import Path

# All downloaded documents land here, organised by ticker subdirectory, which
# test_scrapers.py creates when it saves a ticker's first document
OUTPUT_DIR = Path(__file__).parent / "output"
