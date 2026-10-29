"""
build_intent_dataset.py
-----------------------
Build a combined ML training dataset from:
  1. Kaggle dataset (questionsv4.csv) – keyword-mapped to intents
  2. Existing hand-crafted intent_training_data.json

Output: data/intent_dataset_ml.json
"""

from __future__ import annotations
import json
import os
import random
import sys

import pandas as pd

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
KAGGLE_CSV = r"C:\Users\ADMIN\.cache\kagglehub\datasets\daskoushik\farmers-call-query-data-qa\versions\5\questionsv4.csv"
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HAND_CRAFTED_PATH = os.path.join(PROJECT_ROOT, "data", "intent_training_data.json")
OUTPUT_PATH = os.path.join(PROJECT_ROOT, "data", "intent_dataset_ml.json")

# ---------------------------------------------------------------------------
# Intent keyword definitions — MUST mirror services/intent_service.py exactly
# ---------------------------------------------------------------------------
_INTENT_KEYWORDS: list[tuple[str, list[str]]] = [
    (
        "weather",
        [
            "weather", "rain", "temperature", "forecast", "climate", "humidity",
            "\u0cae\u0cb3\u0cc6",
            "\u0cb9\u0cb5\u0cbe\u0cae\u0cbe\u0ca8",
            "\u0ca4\u0cbe\u0caa\u0cae\u0cbe\u0ca8",
            "\u0cae\u0cb3\u0cc6\u0caf\u0cbe\u0ccd\u0c97",
            "\u092e\u094c\u0938\u092e",
            "\u092c\u093e\u0930\u093f\u0936",
            "\u0924\u093e\u092a\u092e\u093e\u0928",
            "\u092a\u0942\u0930\u094d\u0935\u093e\u0928\u0941\u092e\u093e\u0928",
            "\u0d2e\u0d34\u0d2f\u0d4d\u200c",
            "\u0d15\u0d3e\u0d32\u0d3e\u0d35\u0d38\u0d4d\u0d25",
            "\u0d24\u0d3e\u0d2a\u0d28\u0d3f\u0d32",
            "\u0d06\u0d30\u0d4d\u0d26\u0d4d\u0d30\u0d24",
        ],
    ),
    (
        "market_price",
        [
            "price", "rate", "market", "mandi", "sell", "cost",
            "selling", "trade", "commodity", "crop price",
            "\u0cac\u0cc6\u0cb2\u0cc6",
            "\u0cae\u0cbe\u0cb0\u0cc1\u0c95\u0c9f\u0ccd\u0c9f\u0cc6",
            "\u0cae\u0cbe\u0cb0\u0cbe\u0c9f",
            "\u0ca6\u0cb0",
            "\u0926\u093e\u092e",
            "\u092c\u093e\u091c\u093e\u0930",
            "\u092e\u0902\u0921\u0940",
            "\u0915\u0940\u092e\u0924",
            "\u0d35\u0d3f\u0d32",
            "\u0d15\u0d2e\u0d4d \u092a\u0d31",
            "\u0d35\u0d3f\u0d31\u0d4d\u0d31\u0d32",
            "\u0d15\u0d23\u0d15\u0d4d\u0d15\u0d4d",
        ],
    ),
    (
        "government_scheme",
        [
            "scheme", "yojana", "subsidy", "loan", "insurance",
            "government", "benefit", "kisan", "pmfby", "fasal bima",
            "pm kisan", "rkvy", "eligibility", "grant",
            "\u0caf\u0ccb\u0c9c\u0ca8\u0cc6",
            "\u0cb8\u0cbe\u0cb2",
            "\u0cb8\u0cb9\u0cbe\u0caf",
            "\u0cb5\u0cbf\u0cae\u0cc6",
            "\u092f\u094b\u091c\u0928\u093e",
            "\u0938\u093e\u0932",
            "\u0938\u092c\u094d\u0938\u093f\u0921\u0940",
            "\u092c\u0940\u092e\u093e",
            "\u0d2a\u0d26\u0d4d\u0d27\u0d24\u0d3f",
            "\u0d35\u0d3e\u0d2f\u0d4d\u0d2a",
            "\u0d38\u0d39\u0d3e\u0d2f\u0d02",
            "\u0d07\u0d33\u0d35\u0d4d",
        ],
    ),
    (
        "disease_symptoms",
        [
            "disease", "pest", "fungus", "blight", "wilt",
            "rot", "insect", "spray", "infection", "symptom",
            "yellow", "brown", "spot", "mold", "bug", "aphid",
            "\u0cb0\u0ccb\u0c97",
            "\u0c95\u0cc0\u0c9f",
            "\u0cb6\u0cbf\u0cb2\u0cc0\u0cb2\u0cc7",
            "\u0cb8\u0cbf\u0c82\u0caa\u0ca1\u0cbf",
            "\u0930\u094b\u0917",
            "\u0915\u0940\u091f",
            "\u0915\u0935\u0915",
            "\u0926\u0935\u093e\u0908",
            "\u0d30\u0d4b\u0d17\u0d02",
            "\u0d15\u0d40\u0d1f\u0d02",
            "\u0d15\u0d41\u0d2e\u0d3f\u0d33\u0d4d",
            "\u0d24\u0d33\u0d3f\u0d2f\u0d4d\u0d15\u0d4d\u0d15\u0d32\u0d4d",
        ],
    ),
    (
        "fertilizer_guidance",
        [
            "fertilizer", "manure", "urea", "npk", "compost",
            "nutrient", "dap", "potash", "nitrogen", "phosphorus",
            "\u0c97\u0cca\u0cac\u0ccd\u0cac\u0cb0",
            "\u0caf\u0cc2\u0cb0\u0cbf\u0caf\u0cbe",
            "\u0c97\u0cbd\u0ca8\u0cb0\u0cc1",
            "\u0cb8\u0ced\u0caf\u0cb5\u0cc6",
            "\u0916\u093e\u0926",
            "\u092f\u0942\u0930\u093f\u092f\u093e",
            "\u0915\u0902\u092a\u094b\u0938\u094d\u091f",
            "\u092a\u094b\u0937\u0915",
            "\u0d35\u0d33\u0d02",
            "\u0d2f\u0d42\u0d31\u0d3f\u0d2f",
            "\u0d15\u0d2e\u0d4d\u0d2a\u0d4b\u0d38\u0d4d\u0d31\u0d4d\u0d31\u0d4d",
            "\u0d2a\u0d4b\u0d37\u0d15\u0d02",
        ],
    ),
    (
        "crop_advisory",
        [
            "crop", "sow", "harvest", "planting", "irrigation",
            "seed", "paddy", "rice", "wheat", "cultivation", "grow",
            "\u0cac\u0cc6\u0cb3\u0cc6",
            "\u0cac\u0cbf\u0ca4\u0ccd\u0ca4\u0ca8\u0cc6",
            "\u0ca8\u0cc0\u0cb0\u0cbe\u0cb5\u0cb0\u0cbf",
            "\u0cb5\u0cbf\u0ca4\u0ccd\u0ca4\u0ca8\u0cc6",
            "\u092b\u0938\u0932",
            "\u0928\u0940",
            "\u0938\u093f\u0902\u091a\u093e\u0908",
            "\u092c\u0940\u091c",
            "\u0d35\u0d3f\u0d33",
            "\u0d15\u0d43\u0d37\u0d3f",
            "\u0d28\u0d28\u0d4d\u0d28\u0d4d",
            "\u0d35\u0d3f\u0d24\u0d4d\u0d24\u0d4d",
        ],
    ),
    (
        "selling_guidance",
        [
            "where to sell", "how to sell", "best price",
            "sell crops", "buyer", "trader", "transport",
            "\u0cce\u0c95\u0ccd\u0c95\u0ca1\u0cc6 \u0cae\u0cbe\u0cb0\u0cbe\u0c9f",
            "\u0cb9\u0cc7\u0c97\u0cc6 \u0cae\u0cbe\u0cb0\u0cbe\u0c9f",
            "\u0c96\u0cb0\u0cc0\u0ca6\u0cbf",
            "\u0cb5\u0ccd\u0caf\u0cbe\u0caa\u0cbe\u0cb0\u0cbf",
            "\u0915\u0939\u093e\u0901 \u092c\u0947\u091a\u0947\u0902",
            "\u0916\u0930\u0940\u0926\u093e\u0930",
            "\u0935\u094d\u092f\u093e\u092a\u093e\u0930\u0940",
            "\u092a\u0930\u093f\u0935\u0939\u0928",
            "\u0d35\u0d3f\u0d15\u0d4d\u0d15\u0d41\u0d28\u0d4d\u0d28",
            "\u0d35\u0d3e\u0d19\u0d4d\u0d19\u0d41\u0d28\u0d4d\u0d28",
            "\u0d35\u0d4d\u0d2f\u0d3e\u0d2a\u0d3e\u0d30\u0d3f",
            "\u0d15\u0d2f\u0d31\u0d4d\u0d31\u0d41\u0d2e\u0d24\u0d3f",
        ],
    ),
]


def count_keyword_matches(text: str) -> tuple[str, int]:
    """Return (best_intent, match_count) using the same logic as intent_service.py."""
    text_lower = text.lower()
    best_intent = "unknown"
    best_count = 0

    for intent_name, keywords in _INTENT_KEYWORDS:
        match_count = sum(
            1 for kw in keywords
            if kw in text_lower or kw in text
        )
        if match_count > best_count:
            best_count = match_count
            best_intent = intent_name

    return best_intent, best_count


def load_kaggle_data(csv_path: str) -> list[dict]:
    """Load Kaggle CSV and map questions to intents via keyword rules."""
    print(f"Loading Kaggle CSV: {csv_path}")
    df = pd.read_csv(csv_path)
    print(f"  Raw rows: {len(df)}")

    rows = []
    skipped = 0
    for text in df["questions"].dropna():
        text = str(text).strip()
        if not text:
            continue
        intent, match_count = count_keyword_matches(text)

        # Skip unknown or low-confidence (< 2 matches → confidence < 0.8)
        if intent == "unknown" or match_count < 2:
            skipped += 1
            continue

        rows.append({
            "text": text,
            "language": "en",   # dataset is English
            "intent": intent,
            "_match_count": match_count,
        })

    print(f"  After filtering (2+ matches): {len(rows)} rows, {skipped} skipped")
    return rows


def balance_dataset(rows: list[dict], max_per_intent: int = 200, seed: int = 42) -> list[dict]:
    """Cap each intent at max_per_intent samples (random sample with fixed seed)."""
    rng = random.Random(seed)
    by_intent: dict[str, list[dict]] = {}
    for row in rows:
        by_intent.setdefault(row["intent"], []).append(row)

    result = []
    for intent, samples in by_intent.items():
        if len(samples) > max_per_intent:
            samples = rng.sample(samples, max_per_intent)
        result.extend(samples)
    return result


def main() -> None:
    rng = random.Random(42)

    # --- Load Kaggle data ---
    kaggle_rows = load_kaggle_data(KAGGLE_CSV)
    kaggle_rows = balance_dataset(kaggle_rows, max_per_intent=200)

    # Strip internal _match_count before saving
    kaggle_clean = [{"text": r["text"], "language": r["language"], "intent": r["intent"]}
                    for r in kaggle_rows]

    # --- Load hand-crafted data ---
    print(f"\nLoading hand-crafted data: {HAND_CRAFTED_PATH}")
    with open(HAND_CRAFTED_PATH, "r", encoding="utf-8") as f:
        hand_crafted: list[dict] = json.load(f)
    print(f"  Hand-crafted rows: {len(hand_crafted)}")

    # --- Combine ---
    combined = hand_crafted + kaggle_clean

    # Shuffle combined list with fixed seed for reproducibility
    rng.shuffle(combined)

    # --- Print stats ---
    from collections import Counter
    intent_counts = Counter(r["intent"] for r in combined)
    print("\n=== Combined dataset per-intent counts ===")
    for intent, count in sorted(intent_counts.items()):
        print(f"  {intent:25s}: {count}")
    print(f"  {'TOTAL':25s}: {len(combined)}")

    # --- Save ---
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(combined, f, ensure_ascii=False, indent=2)
    print(f"\nSaved: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
