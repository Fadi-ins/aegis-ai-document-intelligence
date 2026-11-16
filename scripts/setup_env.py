"""Create local-only credentials on first run. Preserve existing configuration."""
import json
import os
from pathlib import Path
from secrets import token_urlsafe

path = Path(".env")
if path.exists():
    print("Using existing .env")
else:
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as config:
        keys = json.dumps({"local": token_urlsafe(36)}, separators=(",", ":"))
        config.write(f"AEGIS_KEYS='{keys}'\n")
        config.write(f"AEGIS_DB_PASSWORD={token_urlsafe(36)}\n")
        config.write(f"POSTGRES_PASSWORD={token_urlsafe(36)}\n")
    print("Created .env with fresh local credentials")
