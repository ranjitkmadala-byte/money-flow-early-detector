# Money Flow Early Detector — Railway Service

This service is a read-only Streamlit dashboard for the Money Flow Early Detector v1.0.

## Railway deployment

1. Create a new Railway service.
2. Deploy this folder/repository as the source.
3. Add the Railway variable:
   `NEON_DATABASE_URL=<your Neon Postgres connection string>`
4. Railway should use the included start command:
   `streamlit run streamlit_app.py --server.port $PORT --server.address 0.0.0.0`
5. In Railway Networking, generate a public domain.
6. Open the domain and confirm the dashboard loads.

## Important

- Do not add Upstox API credentials to this dashboard service.
- Do not modify the existing `upstox-money-flow-engine` service.
- This dashboard reads the same Neon data already written by the collector.
- Keep `NEON_DATABASE_URL` only in Railway Variables; never hard-code it in GitHub.

## Included files

- `streamlit_app.py` — Early Detector dashboard
- `requirements.txt` — Python dependencies
- `Procfile` — Railway start command
- `railway.toml` — deploy/start configuration
