from app.ingestion.extraction import PolicyRuleExtraction
from app.reconciliation.rules import (
    RuleLineItem,
    apply_sub_limits,
    compute_admissible_amount,
    compute_room_rent_proportionate_deduction,
)


def _reference_bill_items() -> list[RuleLineItem]:
    """The reference worked example from docs/plan.md's "Reference: Demo
    Reconciliation Numbers" section."""
    return [
        RuleLineItem(description="Room rent (5 days)", category="room_rent", amount=40000.0),
        RuleLineItem(description="OT charges", category="ot_charges", amount=30000.0),
        RuleLineItem(description="Doctor fees", category="doctor_fees", amount=15000.0),
        RuleLineItem(description="Nursing charges", category="nursing", amount=10000.0),
        RuleLineItem(description="Medicines", category="medicines", amount=12000.0),
        RuleLineItem(description="Consumables", category="consumables", amount=8000.0),
        RuleLineItem(description="Diagnostics", category="diagnostics", amount=5000.0),
    ]


def test_compute_room_rent_proportionate_deduction_no_deduction_when_charged_within_limit():
    """When charged per-day room rent is at or below the limit, no proportionate
    deduction applies at all — not to room rent, not to any other category."""
    items = _reference_bill_items()

    deduction, adjustments = compute_room_rent_proportionate_deduction(
        items, room_rent_limit_per_day=5000.0, room_rent_charged_per_day=5000.0
    )

    assert deduction == 0.0
    assert adjustments == []


def test_compute_room_rent_proportionate_deduction_reference_numbers():
    """Reference example: limit 5000/day, charged 8000/day -> ratio 0.625.
    The 4 proportionate categories (room_rent, ot_charges, doctor_fees, nursing)
    sum to 95000; deduction = 95000 * (1 - 0.625) = 35625."""
    items = _reference_bill_items()

    deduction, adjustments = compute_room_rent_proportionate_deduction(
        items, room_rent_limit_per_day=5000.0, room_rent_charged_per_day=8000.0
    )

    assert round(deduction, 2) == 35625.0

    adjusted_descriptions = {a.description for a in adjustments}
    assert adjusted_descriptions == {
        "Room rent (5 days)",
        "OT charges",
        "Doctor fees",
        "Nursing charges",
    }
    # exempt categories (medicines, consumables, diagnostics) must not appear
    assert "Medicines" not in adjusted_descriptions
    assert "Consumables" not in adjusted_descriptions
    assert "Diagnostics" not in adjusted_descriptions


def test_apply_sub_limits_caps_amount_when_limit_exists():
    """An item whose category has a sub-limit is capped at that limit."""
    items = [
        RuleLineItem(description="OT charges", category="ot_charges", amount=60000.0),
    ]

    result = apply_sub_limits(items, {"ot_charges": 40000.0})

    assert result[0].amount == 40000.0
    assert result[0].description == "OT charges"
    assert result[0].category == "ot_charges"


def test_apply_sub_limits_leaves_uncapped_categories_untouched():
    """An item whose category has no matching sub-limit passes through unchanged."""
    items = [
        RuleLineItem(description="Nursing charges", category="nursing", amount=10000.0),
    ]

    result = apply_sub_limits(items, {"ot_charges": 40000.0})

    assert result[0].amount == 10000.0


def test_compute_admissible_amount_reference_scenario():
    """Full reference scenario end to end: matches the numbers documented in
    docs/plan.md's "Reference: Demo Reconciliation Numbers" section exactly."""
    items = _reference_bill_items()
    policy_rules = PolicyRuleExtraction(
        sum_insured=500000.0,
        room_rent_limit_per_day=5000.0,
        room_rent_limit_type="fixed_amount",
        co_pay_percentage=10.0,
        sub_limits={},
    )

    breakdown = compute_admissible_amount(items, policy_rules, room_rent_charged_per_day=8000.0)

    assert round(breakdown.room_rent_deduction, 2) == 35625.0
    assert round(breakdown.admissible_before_copay, 2) == 84375.0
    assert round(breakdown.co_pay_deduction, 2) == 8437.5
    assert round(breakdown.computed_approved_amount, 2) == 75937.5
