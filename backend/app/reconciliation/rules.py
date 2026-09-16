from dataclasses import dataclass

from app.ingestion.extraction import PolicyRuleExtraction

PROPORTIONATE_CATEGORIES = {"room_rent", "ot_charges", "doctor_fees", "nursing"}


@dataclass
class RuleLineItem:
    description: str
    category: str
    amount: float


@dataclass
class LineItemAdjustment:
    description: str
    original_amount: float
    eligible_amount: float
    deduction: float


@dataclass
class ReconciliationBreakdown:
    room_rent_deduction: float
    room_rent_adjustments: list[LineItemAdjustment]
    admissible_before_copay: float
    co_pay_deduction: float
    computed_approved_amount: float


def apply_sub_limits(items: list[RuleLineItem], sub_limits: dict[str, float]) -> list[RuleLineItem]:
    result = []
    for item in items:
        limit = sub_limits.get(item.category)
        amount = min(item.amount, limit) if limit is not None else item.amount
        result.append(RuleLineItem(description=item.description, category=item.category, amount=amount))
    return result


def compute_room_rent_proportionate_deduction(
    items: list[RuleLineItem], room_rent_limit_per_day: float, room_rent_charged_per_day: float,
) -> tuple[float, list[LineItemAdjustment]]:
    if room_rent_charged_per_day <= room_rent_limit_per_day:
        return 0.0, []

    ratio = room_rent_limit_per_day / room_rent_charged_per_day
    adjustments = []
    total_deduction = 0.0
    for item in items:
        if item.category in PROPORTIONATE_CATEGORIES:
            eligible = item.amount * ratio
            deduction = item.amount - eligible
            total_deduction += deduction
            adjustments.append(LineItemAdjustment(
                description=item.description, original_amount=item.amount,
                eligible_amount=eligible, deduction=deduction,
            ))
    return total_deduction, adjustments


def compute_admissible_amount(
    items: list[RuleLineItem], policy_rules: PolicyRuleExtraction, room_rent_charged_per_day: float,
) -> ReconciliationBreakdown:
    capped_items = apply_sub_limits(items, policy_rules.sub_limits)

    room_rent_deduction = 0.0
    room_rent_adjustments: list[LineItemAdjustment] = []
    if policy_rules.room_rent_limit_type == "fixed_amount" and policy_rules.room_rent_limit_per_day:
        room_rent_deduction, room_rent_adjustments = compute_room_rent_proportionate_deduction(
            capped_items, policy_rules.room_rent_limit_per_day, room_rent_charged_per_day,
        )

    total_before_deduction = sum(i.amount for i in capped_items)
    admissible_before_copay = total_before_deduction - room_rent_deduction
    co_pay_deduction = admissible_before_copay * (policy_rules.co_pay_percentage / 100.0)
    computed_approved_amount = admissible_before_copay - co_pay_deduction

    return ReconciliationBreakdown(
        room_rent_deduction=room_rent_deduction,
        room_rent_adjustments=room_rent_adjustments,
        admissible_before_copay=admissible_before_copay,
        co_pay_deduction=co_pay_deduction,
        computed_approved_amount=computed_approved_amount,
    )
