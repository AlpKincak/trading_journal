"""External broker connectors.

Phase 2 adds a **read-only** TradeLocker connector. Connectors here never place,
modify, cancel, or close trades/orders/positions — they only *read* data for the
local journal.
"""
