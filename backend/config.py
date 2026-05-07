from pathlib import Path

# All downloaded PDFs land here, organised by ticker subdirectory
OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)