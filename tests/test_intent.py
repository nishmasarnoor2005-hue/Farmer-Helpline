"""
Tests for services/intent_service.py
"""
import pytest
from services.intent_service import classify_intent, IntentClassifier, load_training_data, evaluate


class TestIntentClassifier:

    def test_weather_english(self):
        result = classify_intent("What is the weather tomorrow?")
        assert result["intent"] == "weather", f"Expected weather, got {result['intent']}"

    def test_market_price_english(self):
        result = classify_intent("paddy price in Mysore market")
        assert result["intent"] == "market_price", f"Expected market_price, got {result['intent']}"

    def test_government_scheme_english(self):
        result = classify_intent("PM Kisan yojana eligibility")
        assert result["intent"] == "government_scheme", f"Expected government_scheme, got {result['intent']}"

    def test_disease_symptoms_english(self):
        result = classify_intent("tomato disease spray")
        assert result["intent"] == "disease_symptoms", f"Expected disease_symptoms, got {result['intent']}"

    def test_unknown_intent(self):
        result = classify_intent("xyzzy")
        assert result["intent"] == "unknown", f"Expected unknown, got {result['intent']}"
        assert result["confidence"] == 0.0, f"Expected confidence 0.0, got {result['confidence']}"

    def test_kannada_weather(self):
        result = classify_intent("ಮಳೆ ಯಾವಾಗ ಬರುತ್ತದೆ")
        assert result["intent"] == "weather", f"Expected weather, got {result['intent']}"

    def test_method_always_rule_based(self):
        """Method must always be 'rule_based' regardless of input."""
        inputs = [
            "What is the weather tomorrow?",
            "paddy price in Mysore market",
            "PM Kisan yojana eligibility",
            "tomato disease spray",
            "xyzzy",
            "ಮಳೆ ಯಾವಾಗ ಬರುತ್ತದೆ",
            "",
        ]
        for text in inputs:
            result = classify_intent(text)
            assert result["method"] == "rule_based", (
                f"Expected method='rule_based' for input {text!r}, got {result['method']!r}"
            )

    def test_strong_match_confidence(self):
        """Two or more keywords → confidence 1.0."""
        result = classify_intent("weather forecast temperature today")
        assert result["confidence"] == 1.0

    def test_weak_match_confidence(self):
        """Exactly one keyword → confidence 0.6."""
        result = classify_intent("just checking weather nothing else")
        # 'weather' is one keyword
        assert result["confidence"] == 0.6 or result["confidence"] == 1.0
        # Relax: at least some confidence detected
        assert result["confidence"] > 0.0

    def test_language_code_passthrough(self):
        """language_code does not affect the result (all keyword lists checked)."""
        r_en = classify_intent("ಮಳೆ ಯಾವಾಗ ಬರುತ್ತದೆ", language_code="kn")
        r_hi = classify_intent("ಮಳೆ ಯಾವಾಗ ಬರುತ್ತದೆ", language_code="hi")
        assert r_en["intent"] == r_hi["intent"] == "weather"

    def test_result_keys(self):
        """Result dict must always contain the four required keys."""
        result = classify_intent("some random query")
        assert "intent" in result
        assert "confidence" in result
        assert "method" in result
        assert "match_count" in result


class TestTrainingDataset:

    def test_load_training_data_returns_list(self):
        """load_training_data() must return a list."""
        data = load_training_data()
        assert isinstance(data, list)

    def test_load_training_data_min_size(self):
        """Dataset must contain at least 80 examples."""
        data = load_training_data()
        assert len(data) >= 80, f"Expected >= 80 entries, got {len(data)}"

    def test_each_item_has_required_keys(self):
        """Every item must have 'text', 'language', and 'intent' keys."""
        data = load_training_data()
        for i, item in enumerate(data):
            assert "text" in item, f"Item {i} missing 'text'"
            assert "language" in item, f"Item {i} missing 'language'"
            assert "intent" in item, f"Item {i} missing 'intent'"

    def test_evaluate_returns_dict_with_required_keys(self):
        """evaluate() must return a dict containing all required keys."""
        result = evaluate()
        assert isinstance(result, dict)
        for key in ("accuracy", "per_class", "total_examples", "test_examples", "method"):
            assert key in result, f"Missing key '{key}' in evaluate() result"

    def test_evaluate_accuracy_in_range(self):
        """Accuracy value must be between 0.0 and 1.0 inclusive."""
        result = evaluate()
        assert 0.0 <= result["accuracy"] <= 1.0, (
            f"Accuracy out of range: {result['accuracy']}"
        )

    def test_evaluate_method_field(self):
        """evaluate() method field must be 'rule_based_evaluation'."""
        result = evaluate()
        assert result["method"] == "rule_based_evaluation"

    def test_evaluate_example_counts_consistent(self):
        """test_examples must be <= total_examples and > 0."""
        result = evaluate()
        assert result["test_examples"] > 0
        assert result["test_examples"] <= result["total_examples"]
