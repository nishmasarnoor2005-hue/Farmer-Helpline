#!/usr/bin/env python
import sys, json
sys.path.insert(0, 'd:\\Major_Project')
from services.intent_service import evaluate, DATASET_STATUS

print('Dataset status:', DATASET_STATUS)
result = evaluate()
print(f"Accuracy: {result['accuracy']:.1%}")
print(f"Total examples: {result['total_examples']}, Test examples: {result['test_examples']}")
for intent, metrics in result.get('per_class', {}).items():
    print(f"  {intent}: precision={metrics['precision']:.2f}, recall={metrics['recall']:.2f}")
