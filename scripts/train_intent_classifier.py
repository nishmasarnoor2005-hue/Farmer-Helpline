"""
train_intent_classifier.py
---------------------------
Train a LogisticRegression + TF-IDF intent classifier on the combined dataset
produced by build_intent_dataset.py.

Saves the trained model to models/intent_classifier.joblib and writes a
report to docs/INTENT_CLASSIFIER_REPORT.md.
"""

from __future__ import annotations
import json
import os
import sys
from collections import Counter

import joblib
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATASET_PATH = os.path.join(PROJECT_ROOT, "data", "intent_dataset_ml.json")
MODELS_DIR = os.path.join(PROJECT_ROOT, "models")
MODEL_PATH = os.path.join(MODELS_DIR, "intent_classifier.joblib")
DOCS_DIR = os.path.join(PROJECT_ROOT, "docs")
REPORT_PATH = os.path.join(DOCS_DIR, "INTENT_CLASSIFIER_REPORT.md")


def load_dataset(path: str) -> tuple[list[str], list[str]]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    texts = [item["text"] for item in data]
    labels = [item["intent"] for item in data]
    return texts, labels


def main() -> None:
    # --- Load data ---
    print(f"Loading dataset: {DATASET_PATH}")
    texts, labels = load_dataset(DATASET_PATH)
    total = len(texts)
    print(f"Total examples: {total}")

    intent_counts = Counter(labels)
    print("\nPer-intent counts:")
    for intent, count in sorted(intent_counts.items()):
        print(f"  {intent:25s}: {count}")

    # --- Time-based split (NO random shuffle — prevents leakage) ---
    split_idx = int(total * 0.80)
    X_train, X_test = texts[:split_idx], texts[split_idx:]
    y_train, y_test = labels[:split_idx], labels[split_idx:]
    print(f"\nTrain size: {len(X_train)}, Test size: {len(X_test)}")

    # --- Features ---
    tfidf = TfidfVectorizer(max_features=5000, ngram_range=(1, 2))
    X_train_vec = tfidf.fit_transform(X_train)
    X_test_vec = tfidf.transform(X_test)

    # --- Model ---
    clf = LogisticRegression(max_iter=1000, C=1.0)
    clf.fit(X_train_vec, y_train)

    # --- Evaluate ---
    y_pred = clf.predict(X_test_vec)
    accuracy = accuracy_score(y_test, y_pred)
    report_str = classification_report(y_test, y_pred, zero_division=0)
    cm = confusion_matrix(y_test, y_pred, labels=sorted(set(labels)))

    print(f"\nAccuracy: {accuracy:.4f} ({accuracy * 100:.2f}%)")
    print("\nClassification Report:")
    print(report_str)
    print("Confusion Matrix (rows=true, cols=predicted):")
    print("Classes:", sorted(set(labels)))
    print(cm)

    # --- Save model ---
    os.makedirs(MODELS_DIR, exist_ok=True)
    payload = {
        "vectorizer": tfidf,
        "classifier": clf,
        "classes": list(clf.classes_),
    }
    joblib.dump(payload, MODEL_PATH)
    print(f"\nModel saved: {MODEL_PATH}")

    # --- Write report ---
    os.makedirs(DOCS_DIR, exist_ok=True)
    classes_sorted = sorted(set(labels))

    # Build per-class metrics table from classification_report dict
    from sklearn.metrics import classification_report as cr_dict_fn
    report_dict = cr_dict_fn(y_test, y_pred, output_dict=True, zero_division=0)

    per_class_rows = []
    for cls in classes_sorted:
        m = report_dict.get(cls, {"precision": 0, "recall": 0, "f1-score": 0, "support": 0})
        per_class_rows.append(
            f"| {cls:25s} | {m['precision']:.3f}     | {m['recall']:.3f}  | {m['f1-score']:.3f} | {int(m['support'])}       |"
        )

    per_class_table = "\n".join(per_class_rows)

    intent_count_rows = "\n".join(
        f"| {k:25s} | {v}     |" for k, v in sorted(intent_counts.items())
    )

    report_md = f"""# Intent Classifier Report

## Dataset Summary

| Intent                    | Count   |
|---------------------------|---------|
{intent_count_rows}
| **TOTAL**                 | **{total}** |

Dataset source: Kaggle `daskoushik/farmers-call-query-data-qa` (questionsv4.csv,
keyword-filtered to 2+ matches) combined with hand-crafted `intent_training_data.json`.

## Model

- **Architecture**: Logistic Regression + TF-IDF
- **Vectorizer**: `TfidfVectorizer(max_features=5000, ngram_range=(1,2))`
- **Classifier**: `LogisticRegression(max_iter=1000, C=1.0)`

## Train/Test Split

- Method: First 80% → train, last 20% → test (time/index-based, **no random shuffle**)
- Train size: {len(X_train)}
- Test size: {len(X_test)}

## Evaluation Results

**Overall Accuracy: {accuracy:.4f} ({accuracy * 100:.2f}%)**

### Per-Class Metrics

| Intent                    | Precision | Recall | F1    | Support |
|---------------------------|-----------|--------|-------|---------|
{per_class_table}

### Full Classification Report

```
{report_str}
```

## Conclusion

The LogisticRegression + TF-IDF model achieves **{accuracy * 100:.1f}% accuracy** on the held-out
test set. The model is saved at `models/intent_classifier.joblib` and loaded at runtime by
`services/intent_service.py` as the primary classifier, with the existing rule-based keyword
matcher as a fallback when ML confidence is ≤ 0.6.

Training data covers {len(classes_sorted)} intent classes across English and several Indic languages.
The dataset was assembled from {total} examples (hand-crafted + Kaggle, keyword-filtered).
"""

    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        f.write(report_md)
    print(f"Report written: {REPORT_PATH}")


if __name__ == "__main__":
    main()
