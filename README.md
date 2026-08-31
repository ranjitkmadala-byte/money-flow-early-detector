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
