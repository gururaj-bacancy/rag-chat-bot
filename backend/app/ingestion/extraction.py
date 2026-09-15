from typing import Literal
import anthropic
from pydantic import BaseModel
from app.config import settings

_client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

LineItemCategory = Literal[
    "room_rent", "ot_charges", "doctor_fees", "nursing",
    "medicines", "consumables", "diagnostics", "misc",
]

class LineItemExtraction(BaseModel):
    description: str
    category: LineItemCategory
    amount: float

class BillExtraction(BaseModel):
    line_items: list[LineItemExtraction]
    room_category: str | None = None
    room_rent_per_day: float | None = None

class SettlementLineItemExtraction(BaseModel):
    description: str
    claimed_amount: float
    approved_amount: float
    deducted_amount: float
    deduction_reason: str | None = None

class SettlementExtraction(BaseModel):
    line_items: list[SettlementLineItemExtraction]
    total_claimed: float
    total_approved: float
    total_deducted: float

def extract_bill(text: str) -> BillExtraction:
    response = _client.messages.parse(
        model="claude-haiku-4-5",
        max_tokens=4096,
        messages=[{
            "role": "user",
            "content": (
                "Extract every line item, its category, and amount from this "
                "hospital bill, plus the room category and per-day room rent "
                f"if stated:\n\n{text}"
            ),
        }],
        output_format=BillExtraction,
    )
    return response.parsed_output

def extract_settlement(text: str) -> SettlementExtraction:
    response = _client.messages.parse(
        model="claude-haiku-4-5",
        max_tokens=4096,
        messages=[{
            "role": "user",
            "content": (
                "Extract every claimed/approved/deducted line item and the "
                f"totals from this insurance claim settlement letter:\n\n{text}"
            ),
        }],
        output_format=SettlementExtraction,
    )
    return response.parsed_output

RoomRentLimitType = Literal["fixed_amount", "percentage_of_sum_insured", "no_limit"]

class PolicyRuleExtraction(BaseModel):
    sum_insured: float
    room_rent_limit_per_day: float | None = None
    room_rent_limit_type: RoomRentLimitType
    co_pay_percentage: float = 0.0
    sub_limits: dict[str, float] = {}

def extract_policy_rules(text: str) -> PolicyRuleExtraction:
    response = _client.messages.parse(
        model="claude-haiku-4-5",
        max_tokens=4096,
        messages=[{
            "role": "user",
            "content": (
                "Extract the sum insured, room rent limit (and whether it is a "
                "fixed amount, a percentage of sum insured, or no limit), the "
                "co-payment percentage, and any per-procedure sub-limits from "
                f"this mediclaim policy document:\n\n{text}"
            ),
        }],
        output_format=PolicyRuleExtraction,
    )
    return response.parsed_output
