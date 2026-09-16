import json
from unittest.mock import patch

from sqlalchemy import text

from app.agent.tools import make_reconcile_claim_tool, make_search_docs_tool
from app.db.models import Chunk, Document, LineItem, PolicyRule

# NOTE on invocation convention: `@beta_tool`-decorated functions are
# instances of `anthropic.lib.tools._beta_functions.BetaFunctionTool`, not
# plain functions. Inspecting that class shows `__call__` is a `@property`
# that returns the *raw* wrapped function (so `tool(query="x")` happens to
# work too, bypassing pydantic validation), but the SDK's own Tool Runner
# (`anthropic/lib/tools/_beta_runner.py`, `_tool_dispatch.py`) always invokes
# tools via `tool.call(tool_use.input)`, i.e. a single dict of the arguments
# the model produced from the JSON schema. `.call(...)` is therefore the
# faithful way to invoke these tools in tests, since it's exactly how Task
# 15's agent loop (via the Tool Runner) will call them.


def _make_embedding(hot_index: int, dim: int = 1024) -> list[float]:
    vec = [0.0] * dim
    vec[hot_index] = 1.0
    return vec


def _populate_search_vectors(session, document_id: int) -> None:
    session.execute(text(
        "UPDATE chunks SET search_vector = to_tsvector('english', chunk_text) "
        "WHERE document_id = :doc_id"
    ), {"doc_id": document_id})
    session.commit()


def test_search_docs_tool_returns_matching_chunk(db_session):
    document = Document(doc_type="policy", filename="policy.pdf", status="indexed")
    db_session.add(document)
    db_session.commit()

    chunk = Chunk(
        document_id=document.id,
        chunk_text="Room rent is capped at one percent of the sum insured per day.",
        contextual_text="Room rent is capped at one percent of the sum insured per day.",
        page_number=3,
        embedding=_make_embedding(0),
    )
    db_session.add(chunk)
    db_session.commit()
    _populate_search_vectors(db_session, document.id)

    with patch("app.agent.tools.embed_query", return_value=_make_embedding(0)) as mock_embed_query:
        search_docs = make_search_docs_tool(db_session)
        result = search_docs.call({"query": "room rent limit per day"})
        mock_embed_query.assert_called_once_with("room rent limit per day")

    payload = json.loads(result)
    assert isinstance(payload, list)
    assert len(payload) == 1
    entry = payload[0]
    assert entry["chunk_id"] == chunk.id
    assert entry["doc_type"] == "policy"
    assert entry["filename"] == "policy.pdf"
    assert entry["page_number"] == 3
    assert entry["text"] == chunk.chunk_text


def _seed_reference_scenario(db_session):
    """Same seed shape as Task 13's test_reconciliation_engine.py reference
    scenario, with a deliberately wrong settlement approved_amount (70000
    instead of the correct 75937.50) so a real discrepancy is produced."""
    bill = Document(doc_type="bill", filename="bill.pdf", status="indexed")
    policy = Document(doc_type="policy", filename="policy.pdf", status="indexed")
    settlement = Document(doc_type="settlement", filename="settlement.pdf", status="indexed")
    db_session.add_all([bill, policy, settlement])
    db_session.commit()

    bill_items = [
        LineItem(document_id=bill.id, description="Room rent (5 days)", category="room_rent", amount=40000),
        LineItem(document_id=bill.id, description="OT charges", category="ot_charges", amount=30000),
        LineItem(document_id=bill.id, description="Doctor fees", category="doctor_fees", amount=15000),
        LineItem(document_id=bill.id, description="Nursing charges", category="nursing", amount=10000),
        LineItem(document_id=bill.id, description="Medicines", category="medicines", amount=12000),
        LineItem(document_id=bill.id, description="Consumables", category="consumables", amount=8000),
        LineItem(document_id=bill.id, description="Diagnostics", category="diagnostics", amount=5000),
    ]
    db_session.add_all(bill_items)

    db_session.add(PolicyRule(
        document_id=policy.id,
        sum_insured=500000,
        room_rent_limit_per_day=5000,
        room_rent_limit_type="fixed_amount",
        co_pay_percentage=10,
        sub_limits={},
    ))

    db_session.add(LineItem(
        document_id=settlement.id,
        description="Total settlement",
        category="settlement_line",
        amount=120000,
        claimed_amount=120000,
        approved_amount=70000,
        deducted_amount=50000,
    ))

    db_session.commit()


def test_reconcile_claim_tool_reports_discrepancy(db_session):
    _seed_reference_scenario(db_session)
    db_session.expire_all()

    reconcile_claim = make_reconcile_claim_tool(db_session)
    result = reconcile_claim.call({})

    payload = json.loads(result)
    assert payload["matches"] is False
    assert round(payload["discrepancy"], 2) == 5937.5
    assert round(payload["computed_approved_amount"], 2) == 75937.5
    assert round(payload["actual_approved_amount"], 2) == 70000.0
    assert "room_rent_deduction" in payload
    assert "co_pay_deduction" in payload
    assert isinstance(payload["room_rent_adjustments"], list)
    assert len(payload["room_rent_adjustments"]) > 0
    for adjustment in payload["room_rent_adjustments"]:
        assert set(adjustment.keys()) == {"description", "original_amount", "eligible_amount", "deduction"}


def test_reconcile_claim_tool_reports_missing_documents(db_session):
    bill = Document(doc_type="bill", filename="bill.pdf", status="indexed")
    db_session.add(bill)
    db_session.commit()

    db_session.add(LineItem(
        document_id=bill.id, description="Room rent (5 days)", category="room_rent", amount=40000,
    ))
    db_session.commit()

    reconcile_claim = make_reconcile_claim_tool(db_session)
    result = reconcile_claim.call({})

    payload = json.loads(result)
    assert payload["error"] == "missing_documents"
