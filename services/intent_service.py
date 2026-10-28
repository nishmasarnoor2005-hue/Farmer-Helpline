"""
Intent Classifier Service
--------------------------
Rule-based intent detection for farmer voice queries.

DATASET_STATUS: No labeled dataset is available for ML training.
All classification is rule-based (keyword matching) until a labeled
dataset with 'intent'/'label' columns is provided.
"""

from __future__ import annotations

# ---------------------------------------------------------------
# Dataset status — checked by tests and the forecast service
# ---------------------------------------------------------------
DATASET_STATUS = "No labeled dataset available. Rule-based fallback only."

# ---------------------------------------------------------------
# Intent keyword definitions
# Each entry: (intent_name, [keyword_list])
# Matching is case-insensitive against lowercased input.
# Unicode keywords are matched as-is (no lowercasing needed).
# ---------------------------------------------------------------

_INTENT_KEYWORDS: list[tuple[str, list[str]]] = [
    (
        "weather",
        [
            # English
            "weather", "rain", "temperature", "forecast", "climate", "humidity",
            # Kannada
            "\u0cae\u0cb3\u0cc6",        # ಮಳೆ  (rain)
            "\u0cb9\u0cb5\u0cbe\u0cae\u0cbe\u0ca8",  # ಹವಾಮಾನ (weather/climate)
            "\u0ca4\u0cbe\u0caa\u0cae\u0cbe\u0ca8",  # ತಾಪಮಾನ (temperature)
            "\u0cae\u0cb3\u0cc6\u0caf\u0cbe\u0ccd\u0c97",  # ಮಳೆಯಾಗ (when will it rain)
            # Hindi
            "\u092e\u094c\u0938\u092e",   # मौसम (weather)
            "\u092c\u093e\u0930\u093f\u0936",  # बारिश (rain)
            "\u0924\u093e\u092a\u092e\u093e\u0928",  # तापमान (temperature)
            "\u092a\u0942\u0930\u094d\u0935\u093e\u0928\u0941\u092e\u093e\u0928",  # पूर्वानुमान (forecast)
            # Malayalam
            "\u0d2e\u0d34\u0d2f\u0d4d\u200c",  # മഴ (rain)
            "\u0d15\u0d3e\u0d32\u0d3e\u0d35\u0d38\u0d4d\u0d25",  # കാലാവസ്ഥ (climate)
            "\u0d24\u0d3e\u0d2a\u0d28\u0d3f\u0d32",  # താപനില (temperature)
            "\u0d06\u0d30\u0d4d\u0d26\u0d4d\u0d30\u0d24",  # ആർദ്രത (humidity)
        ],
    ),
    (
        "market_price",
        [
            # English
            "price", "rate", "market", "mandi", "sell", "cost",
            "selling", "trade", "commodity", "crop price",
            # Kannada
            "\u0cac\u0cc6\u0cb2\u0cc6",        # ಬೆಲೆ (price)
            "\u0cae\u0cbe\u0cb0\u0cc1\u0c95\u0c9f\u0ccd\u0c9f\u0cc6",  # ಮಾರುಕಟ್ಟೆ (market)
            "\u0cae\u0cbe\u0cb0\u0cbe\u0c9f",  # ಮಾರಾಟ (sale/sell)
            "\u0ca6\u0cb0",                     # ದರ (rate)
            # Hindi
            "\u0926\u093e\u092e",   # दाम (price)
            "\u092c\u093e\u091c\u093e\u0930",  # बाजार (market)
            "\u092e\u0902\u0921\u0940",  # मंडी (mandi)
            "\u0915\u0940\u092e\u0924",  # कीमत (price/cost)
            # Malayalam
            "\u0d35\u0d3f\u0d32",   # വില (price)
            "\u0d15\u0d2e\u0d4d പ\u0d31",  # കമ്പ്ര (market - approx)
            "\u0d35\u0d3f\u0d31\u0d4d\u0d31\u0d32",  # വിറ്റൽ (selling)
            "\u0d15\u0d23\u0d15\u0d4d\u0d15\u0d4d",  # കണക്ക് (rate/count)
        ],
    ),
    (
        "government_scheme",
        [
            # English
            "scheme", "yojana", "subsidy", "loan", "insurance",
            "government", "benefit", "kisan", "pmfby", "fasal bima",
            "pm kisan", "rkvy", "eligibility", "grant",
            # Kannada
            "\u0caf\u0ccb\u0c9c\u0ca8\u0cc6",  # ಯೋಜನೆ (scheme)
            "\u0cb8\u0cbe\u0cb2",               # ಸಾಲ (loan)
            "\u0cb8\u0cb9\u0cbe\u0caf",         # ಸಹಾಯ (help/benefit)
            "\u0cb5\u0cbf\u0cae\u0cc6",         # ವಿಮೆ (insurance)
            # Hindi
            "\u092f\u094b\u091c\u0928\u093e",   # योजना (scheme)
            "\u0938\u093e\u0932",               # साल → साल (not ideal, use subsidy)
            "\u0938\u092c\u094d\u0938\u093f\u0921\u0940",  # सब्सिडी (subsidy)
            "\u092c\u0940\u092e\u093e",         # बीमा (insurance)
            # Malayalam
            "\u0d2a\u0d26\u0d4d\u0d27\u0d24\u0d3f",  # പദ്ധതി (scheme)
            "\u0d35\u0d3e\u0d2f\u0d4d\u0d2a",        # വായ്പ (loan)
            "\u0d38\u0d39\u0d3e\u0d2f\u0d02",        # സഹായം (assistance/benefit)
            "\u0d07\u0d33\u0d35\u0d4d",              # ഇളവ് (subsidy/concession)
        ],
    ),
    (
        "disease_symptoms",
        [
            # English
            "disease", "pest", "fungus", "blight", "wilt",
            "rot", "insect", "spray", "infection", "symptom",
            "yellow", "brown", "spot", "mold", "bug", "aphid",
            # Kannada
            "\u0cb0\u0ccb\u0c97",   # ರೋಗ (disease)
            "\u0c95\u0cc0\u0c9f",   # ಕೀಟ (pest/insect)
            "\u0cb6\u0cbf\u0cb2\u0cc0\u0cb2\u0cc7",  # ಶಿಲೀಲೇ (fungus)
            "\u0cb8\u0cbf\u0c82\u0caa\u0ca1\u0cbf",  # ಸಿಂಪಡಿ (spray)
            # Hindi
            "\u0930\u094b\u0917",   # रोग (disease)
            "\u0915\u0940\u091f",   # कीट (pest/insect)
            "\u0915\u0935\u0915",   # कवक (fungus)
            "\u0926\u0935\u093e\u0908",  # दवाई (medicine/spray)
            # Malayalam
            "\u0d30\u0d4b\u0d17\u0d02",  # രോഗം (disease)
            "\u0d15\u0d40\u0d1f\u0d02",  # കീടം (pest/insect)
            "\u0d15\u0d41\u0d2e\u0d3f\u0d33\u0d4d",  # കുമിൾ (fungus)
            "\u0d24\u0d33\u0d3f\u0d2f\u0d4d\u0d15\u0d4d\u0d15\u0d32\u0d4d",  # തളിയ്ക്കൽ (spraying)
        ],
    ),
    (
        "fertilizer_guidance",
        [
            # English
            "fertilizer", "manure", "urea", "npk", "compost",
            "nutrient", "dap", "potash", "nitrogen", "phosphorus",
            # Kannada
            "\u0c97\u0cca\u0cac\u0ccd\u0cac\u0cb0",  # ಗೊಬ್ಬರ (manure/fertilizer)
            "\u0caf\u0cc2\u0cb0\u0cbf\u0caf\u0cbe",  # ಯೂರಿಯಾ (urea)
            "\u0c97\u0cbd\u0ca8\u0cb0\u0cc1",         # ಗೈನರು → ಖನಿಜ (nutrient approx)
            "\u0cb8\u0ced\u0caf\u0cb5\u0cc6",         # ಸಾವಯವ (organic)
            # Hindi
            "\u0916\u093e\u0926",   # खाद (manure/fertilizer)
            "\u092f\u0942\u0930\u093f\u092f\u093e",  # यूरिया (urea)
            "\u0915\u0902\u092a\u094b\u0938\u094d\u091f",  # कंपोस्ट (compost)
            "\u092a\u094b\u0937\u0915",  # पोषक (nutrient)
            # Malayalam
            "\u0d35\u0d33\u0d02",  # വളം (fertilizer)
            "\u0d2f\u0d42\u0d31\u0d3f\u0d2f",  # യൂറിയ (urea)
            "\u0d15\u0d2e\u0d4d\u0d2a\u0d4b\u0d38\u0d4d\u0d31\u0d4d\u0d31\u0d4d",  # കമ്പോസ്റ്റ് (compost)
            "\u0d2a\u0d4b\u0d37\u0d15\u0d02",  # പോഷകം (nutrient)
        ],
    ),
    (
        "crop_advisory",
        [
            # English
            "crop", "sow", "harvest", "planting", "irrigation",
            "seed", "paddy", "rice", "wheat", "cultivation", "grow",
            # Kannada
            "\u0cac\u0cc6\u0cb3\u0cc6",   # ಬೆಳೆ (crop)
            "\u0cac\u0cbf\u0ca4\u0ccd\u0ca4\u0ca8\u0cc6",  # ಬಿತ್ತನೆ (sowing)
            "\u0ca8\u0cc0\u0cb0\u0cbe\u0cb5\u0cb0\u0cbf",  # ನೀರಾವರಿ (irrigation)
            "\u0cb5\u0cbf\u0ca4\u0ccd\u0ca4\u0ca8\u0cc6",  # ವಿತ್ತನೆ (seeding)
            # Hindi
            "\u092b\u0938\u0932",   # फसल (crop)
            "\u0928\u0940",         # नी → बुआई (sowing approx)
            "\u0938\u093f\u0902\u091a\u093e\u0908",  # सिंचाई (irrigation)
            "\u092c\u0940\u091c",   # बीज (seed)
            # Malayalam
            "\u0d35\u0d3f\u0d33",   # വിള (crop)
            "\u0d15\u0d43\u0d37\u0d3f",  # കൃഷി (cultivation/farming)
            "\u0d28\u0d28\u0d4d\u0d28\u0d4d",  # നന്ന് (irrigation/watering approx)
            "\u0d35\u0d3f\u0d24\u0d4d\u0d24\u0d4d",  # വിത്ത് (seed)
        ],
    ),
    (
        "selling_guidance",
        [
            # English
            "where to sell", "how to sell", "best price",
            "sell crops", "buyer", "trader", "transport",
            # Kannada
            "\u0cce\u0c95\u0ccd\u0c95\u0ca1\u0cc6 \u0cae\u0cbe\u0cb0\u0cbe\u0c9f",  # ಎಲ್ಲಿ ಮಾರಾಟ (where to sell)
            "\u0cb9\u0cc7\u0c97\u0cc6 \u0cae\u0cbe\u0cb0\u0cbe\u0c9f",  # ಹೇಗೆ ಮಾರಾಟ (how to sell)
            "\u0c96\u0cb0\u0cc0\u0ca6\u0cbf",  # ಖರೀದಿ (purchase/buyer)
            "\u0cb5\u0ccd\u0caf\u0cbe\u0caa\u0cbe\u0cb0\u0cbf",  # ವ್ಯಾಪಾರಿ (trader)
            # Hindi
            "\u0915\u0939\u093e\u0901 \u092c\u0947\u091a\u0947\u0902",  # कहाँ बेचें (where to sell)
            "\u0916\u0930\u0940\u0926\u093e\u0930",  # खरीदार (buyer)
            "\u0935\u094d\u092f\u093e\u092a\u093e\u0930\u0940",  # व्यापारी (trader)
            "\u092a\u0930\u093f\u0935\u0939\u0928",  # परिवहन (transport)
            # Malayalam
            "\u0d35\u0d3f\u0d15\u0d4d\u0d15\u0d41\u0d28\u0d4d\u0d28",  # വിക്കുന്ന (selling)
            "\u0d35\u0d3e\u0d19\u0d4d\u0d19\u0d41\u0d28\u0d4d\u0d28",  # വാങ്ങുന്ന (buying)
            "\u0d35\u0d4d\u0d2f\u0d3e\u0d2a\u0d3e\u0d30\u0d3f",  # വ്യാപാരി (trader)
            "\u0d15\u0d2f\u0d31\u0d4d\u0d31\u0d41\u0d2e\u0d24\u0d3f",  # കയറ്റുമതി (export/transport)
        ],
    ),
]


class IntentClassifier:
    """
    Rule-based intent classifier for multi-lingual farmer queries.

    No ML model is used. Classification relies on keyword matching.
    When a labeled dataset with 'intent'/'label' columns becomes
    available, replace this class with a trained model and update
    DATASET_STATUS accordingly.
    """

    DATASET_STATUS = DATASET_STATUS  # surfaced as class attribute too

    def classify(self, text: str, language_code: str = "en") -> dict:
        """
        Classify farmer query intent from text.

        Parameters
        ----------
        text : str
            Transcribed (or typed) query in any supported language.
        language_code : str
            ISO language code hint ('en', 'kn', 'hi', 'ml', …).
            Not used for routing — all keyword lists are checked
            regardless — but preserved in output for tracing.

        Returns
        -------
        dict with keys:
            intent      : str   — one of the defined intent names or 'unknown'
            confidence  : float — 1.0 (strong), 0.6 (weak), 0.0 (unknown)
            method      : str   — always 'rule_based'
            match_count : int   — number of matched keywords
        """
        text_lower = text.lower()
        best_intent = "unknown"
        best_count = 0

        for intent_name, keywords in _INTENT_KEYWORDS:
            match_count = sum(
                1 for kw in keywords
                if kw in text_lower or kw in text  # also match Unicode without lowercasing
            )
            if match_count > best_count:
                best_count = match_count
                best_intent = intent_name

        if best_count == 0:
            confidence = 0.0
            best_intent = "unknown"
        elif best_count == 1:
            confidence = 0.6
        else:
            confidence = 1.0

        return {
            "intent":      best_intent,
            "confidence":  confidence,
            "method":      "rule_based",
            "match_count": best_count,
        }


# ---------------------------------------------------------------
# Module-level convenience function
# ---------------------------------------------------------------

_classifier = IntentClassifier()


def classify_intent(text: str, language_code: str = "en") -> dict:
    """
    Classify the intent of a farmer query.

    Parameters
    ----------
    text : str
        Transcribed query text.
    language_code : str
        ISO code hint, default 'en'.

    Returns
    -------
    dict — see IntentClassifier.classify docstring.
    """
    return _classifier.classify(text, language_code)
