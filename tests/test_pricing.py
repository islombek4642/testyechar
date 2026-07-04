from app.ai.statistics import PRICING


def test_opus_4_8_pricing_present():
    row = PRICING["claude-opus-4-8"]
    assert row["input_per_mtok"] == 5.00
    assert row["output_per_mtok"] == 25.00
    assert row["batch_discount"] == 0.50


def test_sonnet_5_pricing_present():
    row = PRICING["claude-sonnet-5"]
    assert row["input_per_mtok"] == 3.00
    assert row["output_per_mtok"] == 15.00
    assert row["batch_discount"] == 0.50
