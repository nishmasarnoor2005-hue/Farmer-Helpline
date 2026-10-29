# Intent Classifier Report

## Dataset Summary

| Intent                    | Count   |
|---------------------------|---------|
| crop_advisory             | 218     |
| disease_symptoms          | 215     |
| fertilizer_guidance       | 215     |
| government_scheme         | 215     |
| market_price              | 105     |
| selling_guidance          | 16     |
| unknown                   | 15     |
| weather                   | 160     |
| **TOTAL**                 | **1159** |

Dataset source: Kaggle `daskoushik/farmers-call-query-data-qa` (questionsv4.csv,
keyword-filtered to 2+ matches) combined with hand-crafted `intent_training_data.json`.

## Model

- **Architecture**: Logistic Regression + TF-IDF
- **Vectorizer**: `TfidfVectorizer(max_features=5000, ngram_range=(1,2))`
- **Classifier**: `LogisticRegression(max_iter=1000, C=1.0)`

## Train/Test Split

- Method: First 80% → train, last 20% → test (time/index-based, **no random shuffle**)
- Train size: 927
- Test size: 232

## Evaluation Results

**Overall Accuracy: 0.9310 (93.10%)**

### Per-Class Metrics

| Intent                    | Precision | Recall | F1    | Support |
|---------------------------|-----------|--------|-------|---------|
| crop_advisory             | 0.746     | 1.000  | 0.854 | 44       |
| disease_symptoms          | 1.000     | 0.881  | 0.937 | 42       |
| fertilizer_guidance       | 1.000     | 0.946  | 0.972 | 37       |
| government_scheme         | 1.000     | 0.913  | 0.955 | 46       |
| market_price              | 0.955     | 1.000  | 0.977 | 21       |
| selling_guidance          | 0.000     | 0.000  | 0.000 | 3       |
| unknown                   | 0.000     | 0.000  | 0.000 | 1       |
| weather                   | 1.000     | 0.974  | 0.987 | 38       |

### Full Classification Report

```
                     precision    recall  f1-score   support

      crop_advisory       0.75      1.00      0.85        44
   disease_symptoms       1.00      0.88      0.94        42
fertilizer_guidance       1.00      0.95      0.97        37
  government_scheme       1.00      0.91      0.95        46
       market_price       0.95      1.00      0.98        21
   selling_guidance       0.00      0.00      0.00         3
            unknown       0.00      0.00      0.00         1
            weather       1.00      0.97      0.99        38

           accuracy                           0.93       232
          macro avg       0.71      0.71      0.71       232
       weighted avg       0.93      0.93      0.93       232

```

## Conclusion

The LogisticRegression + TF-IDF model achieves **93.1% accuracy** on the held-out
test set. The model is saved at `models/intent_classifier.joblib` and loaded at runtime by
`services/intent_service.py` as the primary classifier, with the existing rule-based keyword
matcher as a fallback when ML confidence is ≤ 0.6.

Training data covers 8 intent classes across English and several Indic languages.
The dataset was assembled from 1159 examples (hand-crafted + Kaggle, keyword-filtered).
