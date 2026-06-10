import os
import json
from mongo_client import get_db, upsert_jurisdiction

JURISDICTIONS_DIR = os.path.join(os.path.dirname(__file__), "jurisdictions")


def load_jurisdictions():
    try:
        db = get_db()
        count = db.jurisdictions.count_documents({})
    except Exception as e:
        print(f"[jurisdictions] MongoDB connection error: {e}")
        return
    if count >= 6:
        print(f"[jurisdictions] already seeded ({count} records), skipping")
        return

    loaded = 0
    for fname in os.listdir(JURISDICTIONS_DIR):
        if not fname.endswith(".json"):
            continue
        fpath = os.path.join(JURISDICTIONS_DIR, fname)
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                data = json.load(f)
            country_code = data.get("country_code")
            if not country_code:
                print(f"[jurisdictions] skipping {fname}: no country_code")
                continue
            upsert_jurisdiction(country_code, data)
            loaded += 1
            print(f"[jurisdictions] loaded {country_code} from {fname}")
        except Exception as e:
            print(f"[jurisdictions] error loading {fname}: {e}")

    print(f"[jurisdictions] seeded {loaded} jurisdictions")
