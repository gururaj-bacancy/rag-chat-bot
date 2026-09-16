-- Persist figures that the Haiku extraction pass already produces but that
-- earlier versions of the ingestion pipeline discarded:
--   * the bill's stated per-day room rent (previously reconstructed in the
--     reconciliation engine by dividing the room_rent line item by a
--     hardcoded 5-day stay),
--   * the settlement letter's own stated claimed/approved/deducted totals
--     (previously reconstructed by summing per-item approved amounts, which
--     fails for settlement letters that print only totals and no item table).
--
-- All four are nullable so pre-existing documents rows stay valid; the
-- reconciliation engine falls back to its old heuristics when they are NULL.
ALTER TABLE documents ADD COLUMN IF NOT EXISTS room_rent_per_day NUMERIC(12,2);
ALTER TABLE documents ADD COLUMN IF NOT EXISTS settlement_total_claimed NUMERIC(12,2);
ALTER TABLE documents ADD COLUMN IF NOT EXISTS settlement_total_approved NUMERIC(12,2);
ALTER TABLE documents ADD COLUMN IF NOT EXISTS settlement_total_deducted NUMERIC(12,2);
