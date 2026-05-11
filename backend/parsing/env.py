import os
from pathlib import Path


# Just loads files from .env 
# Used for loading API key for groq
def load_env(path=None):
    env_path = Path(path) if path else Path(__file__).parent.parent / ".env"
    if not env_path.exists():
        return
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                key, _, value = line.partition("=")
                os.environ[key.strip()] = value.strip()

