# Test Report — AI Farmer Helpline

**Date:** 2026-10-28  
**Hardware:** Windows CPU, Whisper int8 quantization  
**Python:** 3.12.10  
**pytest:** 9.2.0  

---

## Full pytest Output

```
============================= test session starts =============================
platform win32 -- Python 3.12.10, pytest-9.2.0, pluggy-1.6.0 -- D:\Major_Project\.venv\Scripts\python.exe
cachedir: .pytest_cache
rootdir: D:\Major_Project
plugins: anyio-4.14.1
collecting ... collected 76 items

tests/test_auth.py::TestAnonymousRedirect::test_dashboard_redirects_to_login PASSED [  1%]
tests/test_auth.py::TestLoginFailure::test_wrong_credentials_no_redirect PASSED [  2%]
tests/test_auth.py::TestLoginFailure::test_wrong_credentials_shows_generic_error PASSED [  3%]
tests/test_auth.py::TestLoginFailure::test_missing_env_vars_fails_login PASSED [  5%]
tests/test_auth.py::TestLoginSuccess::test_correct_credentials_redirect_to_dashboard PASSED [  6%]
tests/test_auth.py::TestLoginSuccess::test_authenticated_can_access_dashboard PASSED [  7%]
tests/test_auth.py::TestLogout::test_logout_clears_session PASSED        [  9%]
tests/test_database.py::TestInitDb::test_creates_all_three_tables PASSED [ 10%]
tests/test_database.py::TestInitDb::test_idempotent PASSED               [ 11%]
tests/test_database.py::TestCreateSession::test_returns_true PASSED      [ 13%]
tests/test_database.py::TestCreateSession::test_row_appears_in_db PASSED [ 14%]
tests/test_database.py::TestCreateSession::test_default_channel_is_browser PASSED [ 15%]
tests/test_database.py::TestLogInteraction::test_returns_true PASSED     [ 17%]
tests/test_database.py::TestLogInteraction::test_persists_correct_fields PASSED [ 18%]
tests/test_database.py::TestLogInteraction::test_sql_injection_safety PASSED [ 19%]
tests/test_database.py::TestGetRecentInteractions::test_returns_list_of_dicts PASSED [ 21%]
tests/test_database.py::TestGetRecentInteractions::test_limit_is_respected PASSED [ 22%]
tests/test_database.py::TestGetRecentInteractions::test_returns_empty_list_on_no_data PASSED [ 23%]
tests/test_intent.py::TestIntentClassifier::test_weather_english PASSED  [ 25%]
tests/test_intent.py::TestIntentClassifier::test_market_price_english PASSED [ 26%]
tests/test_intent.py::TestIntentClassifier::test_government_scheme_english PASSED [ 27%]
tests/test_intent.py::TestIntentClassifier::test_disease_symptoms_english PASSED [ 28%]
tests/test_intent.py::TestIntentClassifier::test_unknown_intent PASSED   [ 30%]
tests/test_intent.py::TestIntentClassifier::test_kannada_weather PASSED  [ 31%]
tests/test_intent.py::TestIntentClassifier::test_method_always_rule_based PASSED [ 32%]
tests/test_intent.py::TestIntentClassifier::test_strong_match_confidence PASSED [ 34%]
tests/test_intent.py::TestIntentClassifier::test_weak_match_confidence PASSED [ 35%]
tests/test_intent.py::TestIntentClassifier::test_language_code_passthrough PASSED [ 36%]
tests/test_intent.py::TestIntentClassifier::test_result_keys PASSED      [ 38%]
tests/test_location.py::TestExtractLocation::test_valid_indian_location_returns_dict PASSED [ 39%]
tests/test_location.py::TestExtractLocation::test_empty_string_returns_none PASSED [ 40%]
tests/test_location.py::TestExtractLocation::test_geocoder_timeout_returns_none PASSED [ 42%]
tests/test_location.py::TestExtractLocation::test_geocoder_unavailable_returns_none PASSED [ 43%]
tests/test_market_schemes.py::TestMarketService::test_csv_loads_non_empty_list PASSED [ 44%]
tests/test_market_schemes.py::TestMarketService::test_get_market_price_paddy_has_required_fields PASSED [ 46%]
tests/test_market_schemes.py::TestMarketService::test_get_market_price_unknown_crop_returns_unavailable PASSED [ 47%]
tests/test_market_schemes.py::TestMarketService::test_get_market_price_with_district PASSED [ 48%]
tests/test_market_schemes.py::TestMarketService::test_search_market_prices_returns_list PASSED [ 50%]
tests/test_market_schemes.py::TestMarketService::test_search_market_prices_known_crop PASSED [ 51%]
tests/test_market_schemes.py::TestMarketService::test_search_market_prices_each_has_date_and_url PASSED [ 52%]
tests/test_market_schemes.py::TestMarketService::test_search_market_prices_unknown_returns_empty PASSED [ 53%]
tests/test_market_schemes.py::TestMarketService::test_get_market_price_is_live_false PASSED [ 55%]
tests/test_market_schemes.py::TestSchemeService::test_schemes_load_non_empty PASSED [ 56%]
tests/test_market_schemes.py::TestSchemeService::test_search_schemes_insurance_returns_pmfby PASSED [ 57%]
tests/test_market_schemes.py::TestSchemeService::test_search_schemes_returns_at_most_3 PASSED [ 59%]
tests/test_market_schemes.py::TestSchemeService::test_search_schemes_state_filter PASSED [ 60%]
tests/test_market_schemes.py::TestSchemeService::test_format_scheme_response_includes_official_url PASSED [ 61%]
tests/test_market_schemes.py::TestSchemeService::test_format_scheme_response_includes_verified_date PASSED [ 63%]
tests/test_market_schemes.py::TestSchemeService::test_search_schemes_pm_kisan PASSED [ 64%]
tests/test_market_schemes.py::TestSchemeService::test_search_schemes_no_match_returns_empty PASSED [ 65%]
tests/test_rate_limit.py::TestProcessAudioRateLimit::test_eleventh_request_returns_429 PASSED [ 67%]
tests/test_rate_limit.py::TestProcessAudioRateLimit::test_first_request_not_rate_limited PASSED [ 68%]
tests/test_telephony.py::TestMockAdapterUnit::test_handle_incoming_call_returns_nonempty_session_id PASSED [ 69%]
tests/test_telephony.py::TestMockAdapterUnit::test_handle_incoming_call_creates_active_session PASSED [ 71%]
tests/test_telephony.py::TestMockAdapterUnit::test_stream_audio_input_appends_byte_length PASSED [ 72%]
tests/test_telephony.py::TestMockAdapterUnit::test_stream_audio_input_correct_session PASSED [ 73%]
tests/test_telephony.py::TestMockAdapterUnit::test_play_audio_response_stores_path PASSED [ 75%]
tests/test_telephony.py::TestMockAdapterUnit::test_play_audio_response_multiple_paths PASSED [ 76%]
tests/test_telephony.py::TestMockAdapterUnit::test_end_call_sets_status_ended PASSED [ 77%]
tests/test_telephony.py::TestMockAdapterUnit::test_end_call_sets_ended_flag PASSED [ 78%]
tests/test_telephony.py::TestTelephonyRoutes::test_status_returns_200 PASSED [ 80%]
tests/test_telephony.py::TestTelephonyRoutes::test_status_provider_is_mock PASSED [ 81%]
tests/test_telephony.py::TestTelephonyRoutes::test_status_has_status_field PASSED [ 82%]
tests/test_telephony.py::TestTelephonyRoutes::test_incoming_returns_session_id PASSED [ 84%]
tests/test_telephony.py::TestTelephonyRoutes::test_incoming_returns_active_status PASSED [ 85%]
tests/test_telephony.py::TestTelephonyRoutes::test_respond_echoes_message PASSED [ 86%]
tests/test_telephony.py::TestTelephonyRoutes::test_respond_missing_session_returns_error PASSED [ 88%]
tests/test_voice_pipeline.py::TestNoAudioField::test_returns_failure_when_audio_missing PASSED [ 89%]
tests/test_voice_pipeline.py::TestEmptyFilename::test_returns_failure_for_empty_filename PASSED [ 90%]
tests/test_voice_pipeline.py::TestCleanHallucination::test_output_shorter_than_input PASSED [ 92%]
tests/test_voice_pipeline.py::TestCleanHallucination::test_output_is_string PASSED [ 93%]
tests/test_voice_pipeline.py::TestDetectLanguageFallback::test_falls_back_to_kn_on_gemini_exception PASSED [ 94%]
tests/test_weather.py::TestGetWeather::test_valid_response_returns_dict_with_required_keys PASSED [ 96%]
tests/test_weather.py::TestGetWeather::test_request_timeout_returns_none PASSED [ 97%]
tests/test_weather.py::TestGetWeather::test_http_error_returns_none PASSED [ 98%]
tests/test_weather.py::TestGetWeather::test_missing_latitude_returns_none PASSED [100%]

============================== warnings summary ===============================
.venv\Lib\site-packages\anyio\pytest_plugin.py:14: PytestRemovedIn10Warning: _pytest.python.CallSpec2
  has been renamed to CallSpec. The CallSpec2 alias will be removed in pytest 10.
-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
======================= 76 passed, 1 warning in 15.76s ========================
```

**Result: 76 passed, 0 failed, 1 warning (deprecation only)**

---

## Manual Test Checklist

- [ ] Voice recording via browser UI
- [ ] Kannada language detection
- [ ] Weather query response
- [ ] Market price query response
- [ ] Scheme query response
- [ ] Admin login
- [ ] Rate limit enforcement

---

## Blocked Tests

- **Telephony (real phone call):** requires a Twilio account, verified phone number,
  and a public HTTPS webhook. See `docs/TELEPHONY_SETUP.md`.
