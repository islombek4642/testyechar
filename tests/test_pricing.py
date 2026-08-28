from app.ai.statistics import PRICING


def test_opus_5_pricing_present():
    row = PRICING["claude-opus-5"]
    assert row["input_per_mtok"] == 5.00
    assert row["output_per_mtok"] == 25.00
    assert row["batch_discount"] == 0.50


def test_opus_4_8_pricing_present():
    row = PRICING["claude-opus-4-8"]
    assert row["input_per_mtok"] == 5.00
    assert row["output_per_mtok"] == 25.00
    assert row["batch_discount"] == 0.50


def test_sonnet_5_pricing_present():
    # $2/$10 was introductory pricing through 2026-08-31; Anthropic made it
    # the permanent rate instead of reverting to $3/$15.
    row = PRICING["claude-sonnet-5"]
    assert row["input_per_mtok"] == 2.00
    assert row["output_per_mtok"] == 10.00
    assert row["batch_discount"] == 0.50


def test_pricing_only_has_the_4_bot_supported_models():
    # Bot's Sozlamalar menu only ever offers these 4 (bot/handlers.py
    # MODEL_OPTIONS) — no legacy/unused models should linger here.
    assert set(PRICING.keys()) == {
        "claude-opus-5", "claude-opus-4-8", "claude-opus-4-7", "claude-sonnet-5",
    }
