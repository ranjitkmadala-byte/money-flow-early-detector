# Money Flow Early Detector v1.2 — Railway

This dashboard adds OI Spurt as a read-only analysis layer. The Money Flow collector is not changed.

## OI Spurt v1.0 study rules
- 3-minute futures OI increase >= 0.50%: OI SPURT
- 3-minute futures OI increase >= 1.00%: STRONG OI SPURT
- Directional context uses futures vs the frozen 09:30 futures price
- Existing acceleration remains +2% to +4% cumulative OI within <=30 minutes
- Final display progression: WATCH -> OI SPURT -> ACCELERATING -> STRONG

## Railway
Use the same `NEON_DATABASE_URL` variable.
Start command: `streamlit run streamlit_app.py --server.port $PORT --server.address 0.0.0.0`

No collector tables are modified.

## v1.3 — Option Lead + Dominant Option

Adds a read-only research layer using the existing `stock_engine_snapshots` plus the v3.4 `money_flow_option_snapshots` table.

New views/fields:
- Aggregate option fresh-value acceleration (3m vs previous-five-snapshot average)
- Research Option Lead time and count
- Current dominant exact frozen option (CE/PE, strike, wing, LTP multiple, 3m OI change, IV)
- Dominant exact option at the first >=0.50% Futures OI Spurt
- First frozen option to reach 2x its opening/reference LTP
- Timeline deltas: Option Lead -> OI Spurt -> 2-to-4 Acceleration -> Option 2x
- Frozen six-option history in Stock Detail

Research Option Lead is observational only and currently defined as:
- 3-minute aggregate option fresh value >= Rs 0.50Cr, and
- >= 2.0x the mean of the prior five 3-minute snapshots.

This does NOT change the Money Flow collector, OI Spurt threshold, or 2-to-4 acceleration rule.

Dominant exact option is ranked by `abs(oi_change_3m * ltp)`. This is a relative premium-weighted OI intensity proxy, not literal cash flow.
