import os
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st
import psycopg
from psycopg.rows import dict_row
from dotenv import load_dotenv

# ============================================================
# CONFIG
# ============================================================

# Local development fallback
load_dotenv(r"C:\upstox_dashboard\.env")

# Cloud: use Streamlit Secrets.
# Local: fall back to NEON_DATABASE_URL from .env.
try:
    DATABASE_URL = st.secrets["NEON_DATABASE_URL"]
except Exception:
    DATABASE_URL = os.getenv("NEON_DATABASE_URL")

IST = ZoneInfo("Asia/Kolkata")

st.set_page_config(
    page_title="Top 20 Money Flow",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# Mobile-friendly CSS
st.markdown(
    """
    <style>
      .block-container {padding-top: 0.8rem; padding-bottom: 2rem; max-width: 1200px;}
      div[data-testid="stMetric"] {
          border: 1px solid rgba(128,128,128,.25);
          border-radius: 12px;
          padding: 10px 12px;
      }
      .small-note {font-size: 0.82rem; opacity: 0.72;}
      .stock-card {
          border: 1px solid rgba(128,128,128,.25);
          border-radius: 14px;
          padding: 12px 14px;
          margin-bottom: 10px;
      }
      @media (max-width: 700px) {
          .block-container {padding-left: .6rem; padding-right: .6rem;}
          h1 {font-size: 1.45rem !important;}
          h2 {font-size: 1.15rem !important;}
      }
    </style>
    """,
    unsafe_allow_html=True,
)

if not DATABASE_URL:
    st.error("NEON_DATABASE_URL is missing. Add it to Streamlit Secrets in the cloud, or to your local .env file.")
    st.stop()


# ============================================================
# DATABASE
# ============================================================

def query_df(sql, params=None):
    with psycopg.connect(DATABASE_URL, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params or ())
            rows = cur.fetchall()
    return pd.DataFrame(rows)


def load_universe():
    sql = """
    WITH latest_date AS (
        SELECT MAX(trading_date) AS trading_date
        FROM public.money_flow_universe
    )
    SELECT
        trading_date,
        freeze_ts,
        rank,
        symbol,
        futures_value_cr,
        options_value_cr,
        total_money_flow_cr,
        future_volume,
        future_oi,
        future_price,
        spot_price,
        selection_method
    FROM public.money_flow_universe
    WHERE trading_date = (SELECT trading_date FROM latest_date)
    ORDER BY rank;
    """
    return query_df(sql)


def load_latest_snapshots():
    sql = """
    WITH latest_date AS (
        SELECT MAX((ts AT TIME ZONE 'Asia/Kolkata')::date) AS trading_date
        FROM public.stock_engine_snapshots
    ),
    ranked AS (
        SELECT
            s.*,
            ROW_NUMBER() OVER (
                PARTITION BY s.symbol
                ORDER BY s.ts DESC
            ) AS rn
        FROM public.stock_engine_snapshots s
        WHERE (s.ts AT TIME ZONE 'Asia/Kolkata')::date =
              (SELECT trading_date FROM latest_date)
    )
    SELECT *
    FROM ranked
    WHERE rn = 1
    ORDER BY money_flow_rank NULLS LAST, symbol;
    """
    return query_df(sql)


def load_symbol_history(symbol, limit=40):
    sql = """
    SELECT *
    FROM public.stock_engine_snapshots
    WHERE symbol = %s
    ORDER BY ts DESC
    LIMIT %s;
    """
    df = query_df(sql, (symbol, limit))
    if not df.empty:
        df = df.sort_values("ts")
    return df



def load_oi_milestones():
    """First +2%, +4% and +8% futures-OI crossings for the latest trading day."""
    sql = """
    WITH latest_date AS (
        SELECT MAX(trading_date) AS trading_date
        FROM public.money_flow_universe
    ),
    base AS (
        SELECT
            (s.ts AT TIME ZONE 'Asia/Kolkata')::date AS trading_date,
            s.symbol, s.ts, s.future, s.future_oi, s.future_oi_change_pct_t0,
            u.rank AS money_flow_rank, u.future_price AS future_930,
            u.future_oi AS oi_930, u.futures_value_cr AS futures_value_930_cr
        FROM public.stock_engine_snapshots s
        JOIN public.money_flow_universe u
          ON u.symbol = s.symbol
         AND u.trading_date = (s.ts AT TIME ZONE 'Asia/Kolkata')::date
        WHERE u.trading_date = (SELECT trading_date FROM latest_date)
    ),
    c2 AS (
        SELECT DISTINCT ON (symbol) symbol, ts AS time_2pct,
               future_oi_change_pct_t0 AS oi_2pct, future AS future_2pct, future_oi AS future_oi_2pct
        FROM base WHERE future_oi_change_pct_t0 >= 2 ORDER BY symbol, ts
    ),
    c4 AS (
        SELECT DISTINCT ON (symbol) symbol, ts AS time_4pct,
               future_oi_change_pct_t0 AS oi_4pct, future AS future_4pct, future_oi AS future_oi_4pct
        FROM base WHERE future_oi_change_pct_t0 >= 4 ORDER BY symbol, ts
    ),
    c8 AS (
        SELECT DISTINCT ON (symbol) symbol, ts AS time_8pct,
               future_oi_change_pct_t0 AS oi_8pct, future AS future_8pct, future_oi AS future_oi_8pct
        FROM base WHERE future_oi_change_pct_t0 >= 8 ORDER BY symbol, ts
    ),
    symbols AS (
        SELECT DISTINCT symbol, money_flow_rank, future_930, oi_930, futures_value_930_cr FROM base
    )
    SELECT s.*,
           c2.time_2pct, c2.oi_2pct, c2.future_2pct, c2.future_oi_2pct,
           c4.time_4pct, c4.oi_4pct, c4.future_4pct, c4.future_oi_4pct,
           c8.time_8pct, c8.oi_8pct, c8.future_8pct, c8.future_oi_8pct,
           CASE WHEN c2.time_2pct IS NOT NULL AND c4.time_4pct IS NOT NULL
                THEN EXTRACT(EPOCH FROM (c4.time_4pct-c2.time_2pct))/60.0 END AS minutes_2_to_4,
           CASE WHEN c4.time_4pct IS NOT NULL AND c8.time_8pct IS NOT NULL
                THEN EXTRACT(EPOCH FROM (c8.time_8pct-c4.time_4pct))/60.0 END AS minutes_4_to_8
    FROM symbols s
    LEFT JOIN c2 USING(symbol)
    LEFT JOIN c4 USING(symbol)
    LEFT JOIN c8 USING(symbol)
    ORDER BY money_flow_rank;
    """
    return query_df(sql)


def load_early_detector_history(days=31):
    """Reconstruct v1.0 acceleration events from existing Neon snapshots."""
    sql = """
    WITH base AS (
        SELECT
            (s.ts AT TIME ZONE 'Asia/Kolkata')::date AS trading_date,
            s.symbol, s.ts, s.future, s.future_oi, s.future_oi_change_pct_t0, s.zone_state,
            u.rank AS money_flow_rank, u.future_price AS future_930,
            u.future_oi AS oi_930, u.futures_value_cr AS futures_value_930_cr
        FROM public.stock_engine_snapshots s
        JOIN public.money_flow_universe u
          ON u.symbol = s.symbol
         AND u.trading_date = (s.ts AT TIME ZONE 'Asia/Kolkata')::date
        WHERE (s.ts AT TIME ZONE 'Asia/Kolkata')::date >=
              ((CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Kolkata')::date - (%s::int))
    ),
    c2 AS (
        SELECT DISTINCT ON (trading_date, symbol) trading_date, symbol, ts AS time_2pct,
               future_oi_change_pct_t0 AS oi_2pct
        FROM base WHERE future_oi_change_pct_t0 >= 2
        ORDER BY trading_date, symbol, ts
    ),
    c4 AS (
        SELECT DISTINCT ON (trading_date, symbol) trading_date, symbol, ts AS time_4pct,
               future_oi_change_pct_t0 AS oi_4pct, future AS future_4pct, future_oi AS future_oi_4pct,
               zone_state AS zone_4pct, money_flow_rank, future_930, oi_930, futures_value_930_cr
        FROM base WHERE future_oi_change_pct_t0 >= 4
        ORDER BY trading_date, symbol, ts
    ),
    c8 AS (
        SELECT DISTINCT ON (trading_date, symbol) trading_date, symbol, ts AS time_8pct,
               future_oi_change_pct_t0 AS oi_8pct
        FROM base WHERE future_oi_change_pct_t0 >= 8
        ORDER BY trading_date, symbol, ts
    )
    SELECT c4.trading_date, c4.money_flow_rank, c4.symbol,
           c2.time_2pct, c4.time_4pct, c8.time_8pct,
           ROUND((EXTRACT(EPOCH FROM (c4.time_4pct-c2.time_2pct))/60.0)::numeric,0) AS minutes_2_to_4,
           ROUND((((c4.future_4pct/NULLIF(c4.future_930,0))-1)*100)::numeric,2) AS future_move_4pct,
           ROUND((c4.futures_value_930_cr * (((c4.future_4pct*c4.future_oi_4pct)/
                 NULLIF((c4.future_930*c4.oi_930),0))-1))::numeric,2) AS exposure_change_4pct_cr,
           c4.oi_4pct, c4.zone_4pct,
           CASE
             WHEN EXTRACT(EPOCH FROM (c4.time_4pct-c2.time_2pct))/60.0 <= 30 AND c4.future_4pct > c4.future_930 THEN 'ACCELERATING LONG'
             WHEN EXTRACT(EPOCH FROM (c4.time_4pct-c2.time_2pct))/60.0 <= 30 AND c4.future_4pct < c4.future_930 THEN 'ACCELERATING SHORT'
             ELSE 'NO ACCELERATION'
           END AS detector_state
    FROM c4
    JOIN c2 USING(trading_date, symbol)
    LEFT JOIN c8 USING(trading_date, symbol)
    ORDER BY trading_date DESC, money_flow_rank;
    """
    return query_df(sql, (days,))


# ============================================================
# MASTER DASHBOARD SCORING
# ============================================================

def pct_rank_abs(series):
    s = pd.to_numeric(series, errors="coerce").abs()
    if s.notna().sum() <= 1:
        return pd.Series([0.0] * len(s), index=s.index)
    return s.rank(pct=True, method="average").fillna(0.0) * 100.0


def build_master_score(df):
    """
    Cross-sectional Top-20 attention score.
    This does NOT claim historical extremeness.
    It ranks current 3-minute activity against the other selected stocks.
    """
    if df.empty:
        return df

    out = df.copy()

    activity_cols = [
        "future_oi_change_3m",
        "call_oi_change_3m",
        "put_oi_change_3m",
        "pcr_change_3m",
        "pcr_acceleration",
        "call_iv_change_3m",
        "put_iv_change_3m",
        "call_iv_acceleration",
        "put_iv_acceleration",
        "call_fresh_value_cr",
        "put_fresh_value_cr",
        "atm_call_oi_change_3m",
        "atm_put_oi_change_3m",
    ]

    rank_parts = []
    for col in activity_cols:
        if col in out.columns:
            rank_parts.append(pct_rank_abs(out[col]))

    if rank_parts:
        score_matrix = pd.concat(rank_parts, axis=1)
        out["master_attention_score"] = score_matrix.mean(axis=1)
    else:
        out["master_attention_score"] = 0.0

    def status(score):
        if score >= 80:
            return "EXTREME"
        if score >= 65:
            return "STRONG"
        if score >= 50:
            return "NOTABLE"
        return "NORMAL"

    out["master_status"] = out["master_attention_score"].apply(status)

    # Direction is a simple confluence tag, not a trade signal.
    def direction(row):
        bullish = 0
        bearish = 0

        f_oi = float(row.get("future_oi_change_3m") or 0)
        call_oi = float(row.get("call_oi_change_3m") or 0)
        put_oi = float(row.get("put_oi_change_3m") or 0)
        pcr_d = float(row.get("pcr_change_3m") or 0)
        atm_call = float(row.get("atm_call_oi_change_3m") or 0)
        atm_put = float(row.get("atm_put_oi_change_3m") or 0)

        if put_oi > call_oi:
            bullish += 1
        elif call_oi > put_oi:
            bearish += 1

        if pcr_d > 0:
            bullish += 1
        elif pcr_d < 0:
            bearish += 1

        if atm_call < 0:
            bullish += 1
        if atm_put < 0:
            bearish += 1

        # Futures OI is confirmation only; direction requires spot change,
        # which is not yet stored directly as a 3m % field.
        if bullish >= bearish + 2:
            return "Bullish confluence"
        if bearish >= bullish + 2:
            return "Bearish confluence"
        return "Mixed"

    out["confluence"] = out.apply(direction, axis=1)
    return out




# ============================================================
# EARLY DETECTOR v1.0
# ============================================================

ACCELERATION_MINUTES = 30


def build_early_detector(df):
    """Frozen v1.0 research rules for the one-month observation window."""
    if df.empty:
        return df
    out = df.copy()
    numeric_cols = [
        "future_oi_change_pct_t0", "future_oi_change_3m", "future", "future_oi",
        "future_930", "oi_930", "futures_value_930_cr", "spot", "spot_930",
        "minutes_2_to_4", "minutes_4_to_8", "future_4pct", "future_oi_4pct"
    ]
    for col in numeric_cols:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")

    out["price_change_from_930_pct"] = ((out["spot"] / out["spot_930"]) - 1.0) * 100.0
    out["future_price_change_from_930_pct"] = ((out["future"] / out["future_930"]) - 1.0) * 100.0
    out["futures_exposure_change_cr"] = out["futures_value_930_cr"] * (
        ((out["future"] * out["future_oi"]) / (out["future_930"] * out["oi_930"])) - 1.0
    )
    out["future_move_at_4pct"] = ((out["future_4pct"] / out["future_930"]) - 1.0) * 100.0
    out["exposure_at_4pct_cr"] = out["futures_value_930_cr"] * (
        ((out["future_4pct"] * out["future_oi_4pct"]) / (out["future_930"] * out["oi_930"])) - 1.0
    )

    def oi_stage(v):
        if pd.isna(v): return "QUIET"
        if v >= 8: return "STRONG"
        if v >= 4: return "BUILDING"
        if v >= 2: return "WATCH"
        return "QUIET"

    bearish_zones = {"BELOW STRONG DEMAND", "WEAK DEMAND BROKEN", "STRONG DEMAND"}
    bullish_zones = {"ABOVE DPOC", "WEAK SUPPLY", "WEAK SUPPLY BROKEN", "STRONG SUPPLY"}

    def state(row):
        mins = row.get("minutes_2_to_4")
        f4 = row.get("future_move_at_4pct")
        if pd.notna(mins) and mins <= ACCELERATION_MINUTES and pd.notna(f4):
            if f4 > 0: return "🟢 ACCELERATING LONG"
            if f4 < 0: return "🔴 ACCELERATING SHORT"
        oi = float(row.get("future_oi_change_pct_t0") or 0)
        fut_move = float(row.get("future_price_change_from_930_pct") or 0)
        zone = str(row.get("zone_state") or "").upper()
        if oi >= 8 and fut_move > 0: return "🟢 STRONG LONG BUILD"
        if oi >= 8 and fut_move < 0: return "🔴 STRONG SHORT BUILD"
        if oi >= 4 and fut_move > 0: return "🟢 BUILDING LONG"
        if oi >= 4 and fut_move < 0: return "🔴 BUILDING SHORT"
        if oi >= 2 and fut_move > 0: return "🟡 WATCH LONG"
        if oi >= 2 and fut_move < 0: return "🟡 WATCH SHORT"
        if zone in bearish_zones and fut_move <= 0: return "⚠️ BEARISH ZONE WATCH"
        if zone in bullish_zones and fut_move >= 0: return "👀 BULLISH ZONE WATCH"
        return "— NEUTRAL"

    out["oi_stage"] = out["future_oi_change_pct_t0"].apply(oi_stage)
    out["build_state"] = out.apply(state, axis=1)
    priority = {
        "🔴 ACCELERATING SHORT":0, "🟢 ACCELERATING LONG":1,
        "🔴 STRONG SHORT BUILD":2, "🟢 STRONG LONG BUILD":3,
        "🔴 BUILDING SHORT":4, "🟢 BUILDING LONG":5,
        "🟡 WATCH SHORT":6, "🟡 WATCH LONG":7,
        "⚠️ BEARISH ZONE WATCH":8, "👀 BULLISH ZONE WATCH":9, "— NEUTRAL":10
    }
    out["build_priority"] = out["build_state"].map(priority).fillna(99)
    return out

# ============================================================
# HELPERS
# ============================================================

def num(v, digits=2, suffix=""):
    if v is None or pd.isna(v):
        return "-"
    try:
        return f"{float(v):,.{digits}f}{suffix}"
    except Exception:
        return str(v)


def integer(v):
    if v is None or pd.isna(v):
        return "-"
    try:
        return f"{int(float(v)):,}"
    except Exception:
        return str(v)


def iv_pct(v):
    if v is None or pd.isna(v):
        return "-"
    try:
        return f"{float(v) * 100:.2f}%"
    except Exception:
        return "-"


def ts_ist(v):
    if v is None or pd.isna(v):
        return "-"
    t = pd.Timestamp(v)
    if t.tzinfo is None:
        t = t.tz_localize("UTC")
    return t.tz_convert("Asia/Kolkata").strftime("%d %b %H:%M:%S")


# ============================================================
# UI
# ============================================================

st.title("Top 20 Money Flow — Early Detector v1.0")
st.caption("Neon-backed dashboard • Accelerating Long/Short buildup highlighted across all Top-20 stocks.")

universe = load_universe()
latest = build_master_score(load_latest_snapshots())
milestones = load_oi_milestones() if not universe.empty else pd.DataFrame()

if not latest.empty and not universe.empty:
    baseline = universe[["symbol", "spot_price", "future_price", "future_oi", "futures_value_cr"]].rename(
        columns={"spot_price":"spot_930", "future_price":"future_930", "future_oi":"oi_930", "futures_value_cr":"futures_value_930_cr"}
    )
    latest = latest.merge(baseline, on="symbol", how="left")
    if not milestones.empty:
        keep = ["symbol","time_2pct","oi_2pct","future_2pct","future_oi_2pct",
                "time_4pct","oi_4pct","future_4pct","future_oi_4pct",
                "time_8pct","oi_8pct","future_8pct","future_oi_8pct",
                "minutes_2_to_4","minutes_4_to_8"]
        latest = latest.merge(milestones[[c for c in keep if c in milestones.columns]], on="symbol", how="left")
    latest = build_early_detector(latest)

if universe.empty:
    st.warning(
        "No frozen money-flow universe is available yet. "
        "Run the money-flow collector on the next trading day; the Top 20 should freeze around 09:30 IST."
    )
    st.stop()

latest_date = universe["trading_date"].max()
freeze_ts = universe["freeze_ts"].iloc[0] if "freeze_ts" in universe.columns else None

c1, c2, c3 = st.columns(3)
c1.metric("Universe date", str(latest_date))
c2.metric("Frozen stocks", len(universe))
c3.metric("Freeze time", ts_ist(freeze_ts))

if latest.empty:
    st.info(
        "The Top 20 universe exists, but no stock-engine snapshots are available yet. "
        "Once the 3-minute collector starts writing, the two dashboards will populate automatically."
    )

tab1, tab2, tab3, tab4, tab5 = st.tabs(["Master", "Early Detector", "30-Day Monitor", "Liquidity", "Stock detail"])

# ---------------- MASTER ----------------
with tab1:
    st.subheader("Master Dashboard")

    if not latest.empty:
        master = latest.sort_values(
            ["master_attention_score", "money_flow_rank"],
            ascending=[False, True]
        ).copy()

        show_cols = [
            "money_flow_rank",
            "symbol",
            "master_status",
            "master_attention_score",
            "confluence",
            "spot",
            "future_oi_change_3m",
            "call_oi_change_3m",
            "put_oi_change_3m",
            "pcr",
            "pcr_change_3m",
            "call_iv",
            "put_iv",
            "call_fresh_value_cr",
            "put_fresh_value_cr",
            "zone_state",
        ]
        show_cols = [c for c in show_cols if c in master.columns]

        formatted = master[show_cols].copy()
        if "master_attention_score" in formatted:
            formatted["master_attention_score"] = formatted["master_attention_score"].round(1)
        if "call_iv" in formatted:
            formatted["call_iv"] = (pd.to_numeric(formatted["call_iv"], errors="coerce") * 100).round(2)
        if "put_iv" in formatted:
            formatted["put_iv"] = (pd.to_numeric(formatted["put_iv"], errors="coerce") * 100).round(2)

        st.dataframe(
            formatted,
            use_container_width=True,
            hide_index=True,
            column_config={
                "money_flow_rank": "Rank",
                "symbol": "Symbol",
                "master_status": "Status",
                "master_attention_score": st.column_config.ProgressColumn(
                    "Attention",
                    min_value=0,
                    max_value=100,
                    format="%.1f",
                ),
                "confluence": "Confluence",
                "spot": st.column_config.NumberColumn("Spot", format="%.2f"),
                "future_oi_change_3m": "Fut ΔOI 3m",
                "call_oi_change_3m": "Call ΔOI 3m",
                "put_oi_change_3m": "Put ΔOI 3m",
                "pcr": st.column_config.NumberColumn("PCR", format="%.3f"),
                "pcr_change_3m": st.column_config.NumberColumn("PCR Δ3m", format="%.4f"),
                "call_iv": st.column_config.NumberColumn("Call IV %", format="%.2f"),
                "put_iv": st.column_config.NumberColumn("Put IV %", format="%.2f"),
                "call_fresh_value_cr": st.column_config.NumberColumn("Call Fresh ₹Cr", format="%.3f"),
                "put_fresh_value_cr": st.column_config.NumberColumn("Put Fresh ₹Cr", format="%.3f"),
                "zone_state": "Zone",
            }
        )

        top = master.iloc[0]
        st.markdown("#### Highest-attention stock")
        a, b, c, d = st.columns(4)
        a.metric("Symbol", str(top.get("symbol", "-")))
        b.metric("Master", str(top.get("master_status", "-")))
        c.metric("Attention", num(top.get("master_attention_score"), 1, "/100"))
        d.metric("Confluence", str(top.get("confluence", "-")))

        st.markdown(
            '<div class="small-note">'
            'The Master score is cross-sectional: it compares the current 3-minute activity of the Top 20 against one another. '
            'It is not yet a historical probability or trading recommendation.'
            '</div>',
            unsafe_allow_html=True,
        )


# ---------------- EARLY DETECTOR ----------------
with tab2:
    st.subheader("Early Detector v1.0")
    st.caption("Frozen for one month: +2% WATCH, +4% BUILDING, +8% STRONG. ACCELERATING = first +2% to +4% in <=30 minutes; futures direction at +4% defines LONG or SHORT.")

    if not latest.empty:
        early = latest.sort_values(["build_priority", "money_flow_rank"], ascending=[True, True]).copy()
        accel_long = int((early["build_state"] == "🟢 ACCELERATING LONG").sum())
        accel_short = int((early["build_state"] == "🔴 ACCELERATING SHORT").sum())
        active_2 = int((pd.to_numeric(early["future_oi_change_pct_t0"], errors="coerce") >= 2).sum())
        active_8 = int((pd.to_numeric(early["future_oi_change_pct_t0"], errors="coerce") >= 8).sum())
        m1,m2,m3,m4 = st.columns(4)
        m1.metric("Accelerating Long", accel_long)
        m2.metric("Accelerating Short", accel_short)
        m3.metric("OI >=2%", active_2)
        m4.metric("OI >=8%", active_8)

        active_accel = early[early["build_state"].isin(["🟢 ACCELERATING LONG", "🔴 ACCELERATING SHORT"])]
        if not active_accel.empty:
            st.markdown("### 🚨 Acceleration highlights")
            for _,r in active_accel.iterrows():
                border = "#2ea043" if "LONG" in r["build_state"] else "#d1242f"
                html = (
                    f'<div style="border:2px solid {border};border-radius:14px;padding:12px 14px;margin:8px 0;">'
                    f'<b>{r.get("build_state","-")} — #{r.get("money_flow_rank","-")} {r.get("symbol","-")}</b><br>'
                    f'2→4 OI: <b>{num(r.get("minutes_2_to_4"),0," min")}</b> &nbsp;|&nbsp; '
                    f'Fut @4%: <b>{num(r.get("future_move_at_4pct"),2,"%")}</b> &nbsp;|&nbsp; '
                    f'Exposure @4%: <b>{num(r.get("exposure_at_4pct_cr"),2," Cr")}</b><br>'
                    f'Current OI vs T0: <b>{num(r.get("future_oi_change_pct_t0"),2,"%")}</b> &nbsp;|&nbsp; '
                    f'Current Fut vs 09:30: <b>{num(r.get("future_price_change_from_930_pct"),2,"%")}</b> &nbsp;|&nbsp; '
                    f'Zone: <b>{r.get("zone_state","-")}</b></div>'
                )
                st.markdown(html, unsafe_allow_html=True)
        else:
            st.info("No Accelerating Long/Short state has qualified yet on the latest trading day.")

        cols = ["money_flow_rank","symbol","build_state","oi_stage","future_oi_change_pct_t0",
                "future_price_change_from_930_pct","futures_exposure_change_cr","minutes_2_to_4",
                "minutes_4_to_8","future_move_at_4pct","exposure_at_4pct_cr","zone_state","next_zone"]
        view = early[[c for c in cols if c in early.columns]].copy()
        for c in ["future_oi_change_pct_t0","future_price_change_from_930_pct","futures_exposure_change_cr",
                  "minutes_2_to_4","minutes_4_to_8","future_move_at_4pct","exposure_at_4pct_cr"]:
            if c in view: view[c] = pd.to_numeric(view[c], errors="coerce").round(2)
        st.markdown("### All Top-20 stocks")
        st.dataframe(view, use_container_width=True, hide_index=True, column_config={
            "money_flow_rank":"Rank", "symbol":"Symbol", "build_state":"Build State", "oi_stage":"OI Stage",
            "future_oi_change_pct_t0":st.column_config.NumberColumn("OI vs 09:30",format="%.2f%%"),
            "future_price_change_from_930_pct":st.column_config.NumberColumn("Fut vs 09:30",format="%.2f%%"),
            "futures_exposure_change_cr":st.column_config.NumberColumn("Exposure Δ ₹Cr",format="%.2f"),
            "minutes_2_to_4":st.column_config.NumberColumn("2→4 min",format="%.0f"),
            "minutes_4_to_8":st.column_config.NumberColumn("4→8 min",format="%.0f"),
            "future_move_at_4pct":st.column_config.NumberColumn("Fut @4%",format="%.2f%%"),
            "exposure_at_4pct_cr":st.column_config.NumberColumn("Exposure @4% ₹Cr",format="%.2f"),
            "zone_state":"Zone", "next_zone":"Next Zone"
        })
        st.markdown('<div class="small-note">v1.0 is frozen for the one-month study. Zone/PCR/IV/options stay as context and do not alter the acceleration label yet.</div>', unsafe_allow_html=True)

# ---------------- 30-DAY MONITOR ----------------
with tab3:
    st.subheader("30-Day Early Detector Monitor")
    st.caption("Reconstructed from existing Neon snapshots; no Railway collector change required.")
    hist_events = load_early_detector_history(31)
    if hist_events.empty:
        st.info("No historical +2% to +4% events are available yet.")
    else:
        al = hist_events[hist_events["detector_state"] == "ACCELERATING LONG"]
        ash = hist_events[hist_events["detector_state"] == "ACCELERATING SHORT"]
        h1,h2,h3,h4 = st.columns(4)
        h1.metric("Accelerating Long events", len(al))
        h2.metric("Accelerating Short events", len(ash))
        h3.metric("Trading days", hist_events["trading_date"].nunique())
        h4.metric("Total 4% crossings", len(hist_events))
        only_accel = hist_events[hist_events["detector_state"] != "NO ACCELERATION"].copy()
        dcols = ["trading_date","money_flow_rank","symbol","detector_state","time_2pct","time_4pct",
                 "minutes_2_to_4","oi_4pct","future_move_4pct","exposure_change_4pct_cr","zone_4pct","time_8pct"]
        st.dataframe(only_accel[[c for c in dcols if c in only_accel.columns]], use_container_width=True, hide_index=True, column_config={
            "detector_state":"Acceleration", "minutes_2_to_4":"2→4 min",
            "oi_4pct":st.column_config.NumberColumn("OI @4%",format="%.2f%%"),
            "future_move_4pct":st.column_config.NumberColumn("Fut @4%",format="%.2f%%"),
            "exposure_change_4pct_cr":st.column_config.NumberColumn("Exposure @4% ₹Cr",format="%.2f"),
            "zone_4pct":"Zone @4%"
        })

# ---------------- LIQUIDITY ----------------
with tab4:
    st.subheader("Liquidity Dashboard")

    if not latest.empty:
        liq = latest.sort_values("money_flow_rank").copy()

        for _, row in liq.iterrows():
            symbol = row.get("symbol", "-")
            rank = row.get("money_flow_rank", "-")
            zone = row.get("zone_state", "-")
            nxt = row.get("next_zone", "-")
            spot = row.get("spot")
            dpoc = row.get("dpoc")
            basis = row.get("future_basis")

            st.markdown(
                f"""
                <div class="stock-card">
                    <b>#{rank} {symbol}</b><br>
                    Spot: <b>{num(spot,2)}</b> &nbsp; | &nbsp;
                    DPOC: <b>{num(dpoc,2)}</b> &nbsp; | &nbsp;
                    Fut basis: <b>{num(basis,2)}</b><br>
                    Current zone: <b>{zone}</b><br>
                    Next zone: <b>{nxt}</b>
                </div>
                """,
                unsafe_allow_html=True,
            )

# ---------------- DETAIL ----------------
with tab5:
    st.subheader("Stock detail")

    symbols = universe.sort_values("rank")["symbol"].tolist()
    selected = st.selectbox("Select stock", symbols)

    selected_row = latest[latest["symbol"] == selected] if not latest.empty else pd.DataFrame()

    if not selected_row.empty:
        r = selected_row.iloc[0]

        st.markdown(f"### #{r.get('money_flow_rank','-')} {selected}")

        x1, x2, x3, x4 = st.columns(4)
        x1.metric("Spot", num(r.get("spot"), 2))
        x2.metric("Future", num(r.get("future"), 2))
        x3.metric("PCR", num(r.get("pcr"), 3))
        x4.metric("Zone", str(r.get("zone_state", "-")))

        y1, y2, y3, y4 = st.columns(4)
        y1.metric("Fut ΔOI 3m", integer(r.get("future_oi_change_3m")))
        y2.metric("Call ΔOI 3m", integer(r.get("call_oi_change_3m")))
        y3.metric("Put ΔOI 3m", integer(r.get("put_oi_change_3m")))
        y4.metric("Next zone", str(r.get("next_zone", "-")))

        z1, z2, z3, z4 = st.columns(4)
        z1.metric("Call IV", iv_pct(r.get("call_iv")))
        z2.metric("Put IV", iv_pct(r.get("put_iv")))
        z3.metric("Call fresh ₹Cr", num(r.get("call_fresh_value_cr"), 3))
        z4.metric("Put fresh ₹Cr", num(r.get("put_fresh_value_cr"), 3))

        hist = load_symbol_history(selected, 40)

        if not hist.empty:
            hist = hist.copy()
            hist["IST"] = pd.to_datetime(hist["ts"], utc=True).dt.tz_convert("Asia/Kolkata")
            plot = hist.set_index("IST")

            if "spot" in plot:
                st.markdown("#### Spot — recent 3-minute history")
                st.line_chart(plot[["spot"]], use_container_width=True)

            if {"call_iv", "put_iv"}.issubset(plot.columns):
                iv_plot = plot[["call_iv", "put_iv"]].apply(pd.to_numeric, errors="coerce") * 100
                st.markdown("#### IV — recent 3-minute history")
                st.line_chart(iv_plot, use_container_width=True)

            history_cols = [
                "ts",
                "spot",
                "future_basis",
                "future_oi_change_3m",
                "call_oi_change_3m",
                "put_oi_change_3m",
                "pcr",
                "pcr_change_3m",
                "zone_state",
                "next_zone",
            ]
            history_cols = [c for c in history_cols if c in hist.columns]
            st.markdown("#### Recent snapshots")
            st.dataframe(
                hist[history_cols].sort_values("ts", ascending=False),
                use_container_width=True,
                hide_index=True,
            )
    else:
        st.info("No 3-minute snapshot exists yet for this stock.")

st.divider()

r1, r2 = st.columns(2)
with r1:
    if st.button("Refresh now", use_container_width=True):
        st.rerun()

with r2:
    st.caption("Keep this page open on your phone. Use Refresh now after each 3-minute collector cycle.")

st.caption(
    "Data source: your Neon database. The dashboard is read-only and does not place trades or modify market data."
)
