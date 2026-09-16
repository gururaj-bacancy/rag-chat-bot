from pathlib import Path
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4

def _write_lines(path: str, title: str, lines: list[str]) -> None:
    c = canvas.Canvas(path, pagesize=A4)
    width, height = A4
    y = height - 72
    c.setFont("Helvetica-Bold", 14)
    c.drawString(72, y, title)
    y -= 30
    c.setFont("Helvetica", 11)
    for line in lines:
        if y < 72:
            c.showPage()
            c.setFont("Helvetica", 11)
            y = height - 72
        c.drawString(72, y, line)
        y -= 18
    c.save()

def generate_sample_documents(output_dir: str) -> dict[str, str]:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    bill_path = out / "sample_bill.pdf"
    _write_lines(str(bill_path), "APOLLO CITY HOSPITAL - FINAL BILL", [
        "Patient: Ramesh Kumar   Admission: 5 days   Room Category: Private Room",
        "",
        "Room rent (5 days x Rs 8,000/day): Rs 40,000",
        "OT charges: Rs 30,000",
        "Doctor fees: Rs 15,000",
        "Nursing charges: Rs 10,000",
        "Medicines: Rs 12,000",
        "Consumables: Rs 8,000",
        "Diagnostics (lab + radiology): Rs 5,000",
        "",
        "TOTAL BILL AMOUNT: Rs 1,20,000",
    ])

    policy_path = out / "sample_policy.pdf"
    _write_lines(str(policy_path), "SURAKSHA GOLD MEDICLAIM POLICY", [
        "Policy Holder: Ramesh Kumar   Sum Insured: Rs 5,00,000",
        "",
        "ROOM RENT LIMIT",
        "The Company shall pay room rent up to Rs 5,000 per day. Where the",
        "insured is admitted to a room exceeding this limit, associated",
        "medical expenses (room rent, OT charges, doctor fees, nursing) will",
        "be paid in the same proportion as this limit bears to the actual",
        "room rent charged.",
        "",
        "CO-PAYMENT",
        "A co-payment of 10% of the admissible claim amount applies to all",
        "hospitalization claims under this policy.",
        "",
        "SUB-LIMITS",
        "No procedure-specific sub-limits apply under this plan.",
    ])

    settlement_path = out / "sample_settlement.pdf"
    _write_lines(str(settlement_path), "MEDIASSIST TPA - CLAIM SETTLEMENT LETTER", [
        "Claim No: MC-2026-004521   Policy Holder: Ramesh Kumar",
        "",
        "Total amount claimed: Rs 1,20,000",
        "Total amount approved: Rs 70,000",
        "Total amount deducted: Rs 50,000",
        "",
        "Deduction reason: Room rent proportionate deduction as per policy",
        "terms, and applicable co-payment.",
    ])

    return {"bill": str(bill_path), "policy": str(policy_path), "settlement": str(settlement_path)}

if __name__ == "__main__":
    import sys
    paths = generate_sample_documents(sys.argv[1] if len(sys.argv) > 1 else "sample_data/generated")
    for doc_type, path in paths.items():
        print(f"{doc_type}: {path}")
