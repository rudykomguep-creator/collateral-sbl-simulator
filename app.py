"""
Collateral Management & SBL Simulator — Streamlit Dashboard
Repo Lifecycle + Securities Borrowing & Lending Settlement Tracker
Built by: Steve Rudy Komguep Jouenang
"""

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
from datetime import date, timedelta
from data_models import (
    Collateral, CollateralType, RepoTrade, TradeStatus,
    EventType, STANDARD_HAIRCUTS, SettlementStatus, LoanDirection, AssetClass
)
from repo_engine import simulate_lifecycle
from sbl_engine import (
    build_sample_portfolio, generate_sbl_transactions,
    compute_counterparty_exposures, settlement_summary
)

# ── Page config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Collateral Management & SBL Simulator",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Styling ──────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    .main-title { font-size: 2rem; font-weight: 700; color: #1a237e; }
    .subtitle { font-size: 1rem; color: #546e7a; margin-bottom: 1.5rem; }
    .stAlert { border-radius: 8px; }
    div[data-testid="metric-container"] { background: #f8f9fa; border-radius: 8px; padding: 0.5rem; }
</style>
""", unsafe_allow_html=True)

# ── Navigation ───────────────────────────────────────────────────────────────
st.markdown('<div class="main-title">📊 Collateral Management & SBL Simulator</div>', unsafe_allow_html=True)
st.markdown('<div class="subtitle">Repo Lifecycle · Securities Borrowing & Lending · Settlement Tracking</div>', unsafe_allow_html=True)

page = st.radio(
    "Select Module",
    ["📄 Repo Trade Lifecycle", "🔄 SBL Settlement Tracker"],
    horizontal=True,
)
st.markdown("---")


# ════════════════════════════════════════════════════════════════════════════
# PAGE 1 — REPO LIFECYCLE
# ════════════════════════════════════════════════════════════════════════════
if page == "📄 Repo Trade Lifecycle":

    st.info(
        "**What is a Repo?** A repurchase agreement (repo) is a short-term secured loan. "
        "The client sells collateral (Treasuries, MBS…) to Morgan Stanley and agrees to repurchase "
        "it at a higher price. This simulator models the full trade lifecycle: margin calls, "
        "collateral substitutions, rolls, and close-outs.",
        icon="ℹ️"
    )

    with st.sidebar:
        st.header("🔧 Repo Trade Parameters")

        st.subheader("Counterparty")
        client_name = st.text_input("Client Name", value="Citadel Asset Management")

        st.subheader("Collateral")
        col_type = st.selectbox(
            "Collateral Type",
            options=list(CollateralType),
            format_func=lambda x: x.value,
            index=1,
        )
        face_value = st.number_input("Face Value ($)", min_value=1_000_000, max_value=500_000_000,
                                      value=50_000_000, step=1_000_000, format="%d")
        market_price_pct = st.slider("Market Price (% of Face)", min_value=85.0, max_value=105.0,
                                      value=98.5, step=0.5)
        market_value = face_value * market_price_pct / 100

        default_haircut = STANDARD_HAIRCUTS[col_type] * 100
        haircut_pct = st.slider("Haircut (%)", min_value=0.5, max_value=20.0,
                                 value=float(round(default_haircut, 1)), step=0.5)
        st.caption(f"📋 Standard haircut for {col_type.value}: {default_haircut:.1f}%")

        eligible_value = market_value * (1 - haircut_pct / 100)
        st.success(f"**Eligible Value:** ${eligible_value:,.0f}")

        st.subheader("Trade Terms")
        repo_rate = st.slider("Repo Rate (% p.a.)", min_value=0.5, max_value=10.0, value=5.30, step=0.05)
        term_days = st.selectbox("Term", options=[1, 2, 3, 7, 14, 30], index=3,
                                  format_func=lambda x: f"{x}d {'(overnight)' if x==1 else '(1 week)' if x==7 else '(2 weeks)' if x==14 else '(1 month)' if x==30 else ''}")

        max_cash = int(eligible_value)
        cash_lent = st.number_input("Cash Lent ($)", min_value=1_000_000, max_value=max_cash,
                                     value=min(int(eligible_value * 0.95), max_cash),
                                     step=100_000, format="%d")
        margin_threshold = st.slider("Margin Call Threshold (%)", min_value=0.5, max_value=5.0, value=2.0, step=0.5)

        st.subheader("📉 Price Scenario")
        scenario = st.selectbox("Collateral Price Path", options=[
            "Stable", "Gradual Decline", "Sharp Drop (Day 3)", "Recovery After Dip", "Volatile"
        ])

        st.subheader("🔄 Maturity")
        roll_on_maturity = st.checkbox("Roll trade at maturity", value=False)
        roll_rate = repo_rate / 100
        roll_days_val = term_days
        if roll_on_maturity:
            roll_rate = st.slider("Roll Rate (%)", min_value=0.5, max_value=10.0, value=repo_rate + 0.05, step=0.05) / 100
            roll_days_val = st.selectbox("Roll Term", options=[1, 2, 3, 7, 14, 30], index=3)

        st.subheader("⚠️ Margin Call Response")
        margin_default_response = st.selectbox("Client response",
            options=["cash", "collateral", "default"],
            format_func=lambda x: {"cash": "✅ Post cash", "collateral": "🔄 Substitute collateral", "default": "🔴 Default"}[x])

    # Generate price path
    def generate_price_path(scenario, mv, days):
        np.random.seed(42)
        if scenario == "Stable":
            return [mv * (1 + np.random.normal(0, 0.001)) for _ in range(days)]
        elif scenario == "Gradual Decline":
            return [mv * (1 - 0.004 * i + np.random.normal(0, 0.001)) for i in range(days)]
        elif scenario == "Sharp Drop (Day 3)":
            path = [mv * (1 + np.random.normal(0, 0.001)) for _ in range(days)]
            for i in range(min(2, days), days):
                path[i] = mv * (0.91 + np.random.normal(0, 0.002))
            return path
        elif scenario == "Recovery After Dip":
            path = []
            for i in range(days):
                if i < days // 3:
                    path.append(mv * (1 - 0.003 * i))
                else:
                    path.append(mv * (0.97 + 0.002 * (i - days // 3)))
            return path
        else:
            path = [mv]
            for _ in range(days - 1):
                path.append(path[-1] * (1 + np.random.normal(0, 0.008)))
            return path

    price_path = generate_price_path(scenario, market_value, term_days)

    collateral = Collateral(col_type, face_value, market_value, haircut_override=haircut_pct/100)
    trade = RepoTrade(client_name, collateral, cash_lent, repo_rate/100, date.today(), term_days, margin_threshold/100)
    events = simulate_lifecycle(trade, price_path, [margin_default_response]*term_days, roll_on_maturity, roll_rate, roll_days_val)

    # Metrics
    st.subheader("📌 Trade Summary")
    c1, c2, c3, c4, c5 = st.columns(5)
    daily_int = cash_lent * (repo_rate/100) / 360
    total_int = daily_int * term_days
    c1.metric("Cash Lent", f"${cash_lent:,.0f}")
    c2.metric("Collateral MV", f"${market_value:,.0f}")
    c3.metric("Repo Rate", f"{repo_rate:.2f}%")
    c4.metric("Daily Interest", f"${daily_int:,.2f}")
    c5.metric("Total Interest", f"${total_int:,.2f}")

    c6, c7, c8 = st.columns(3)
    c6.metric("Repurchase Price", f"${cash_lent + total_int:,.2f}")
    c7.metric("Initial Coverage", f"{eligible_value/cash_lent:.3f}x")
    c8.metric("Margin Calls", sum(1 for e in events if e.event_type == EventType.MARGIN_CALL))

    # Chart 1: Collateral MV + Coverage
    st.subheader("📈 Collateral Price & Coverage Ratio")
    days_list = list(range(len(price_path)))
    coverage_list = [trade.coverage_ratio(mv) for mv in price_path]

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=days_list, y=price_path, name="Collateral MV",
                              line=dict(color="#1565c0", width=2.5), yaxis="y1"))
    threshold_mv = cash_lent / (1 - haircut_pct/100)
    fig.add_hline(y=threshold_mv, line_dash="dash", line_color="#e65100", opacity=0.7,
                  annotation_text="Min Coverage Level", yref="y1")
    fig.add_trace(go.Scatter(x=days_list, y=coverage_list, name="Coverage Ratio",
                              line=dict(color="#2e7d32", width=2, dash="dot"), yaxis="y2"))
    fig.update_layout(
        xaxis_title="Day",
        yaxis=dict(title="Collateral MV ($)", tickformat="$,.0f"),
        yaxis2=dict(title="Coverage Ratio (x)", overlaying="y", side="right", tickformat=".3f"),
        height=380, hovermode="x unified", plot_bgcolor="#fafafa",
        legend=dict(x=0.01, y=0.99),
    )
    st.plotly_chart(fig, use_container_width=True)

    # Chart 2: Cumulative Cash Flow
    st.subheader("💵 Cumulative Cash Flow (MS perspective)")
    cumulative, running = [], 0
    for e in events:
        running += e.cash_flow
        cumulative.append((e.day, running))
    fig2 = go.Figure()
    fig2.add_trace(go.Scatter(
        x=[c[0] for c in cumulative], y=[c[1] for c in cumulative],
        fill="tozeroy", fillcolor="rgba(21,101,192,0.1)",
        line=dict(color="#1565c0", width=2), name="Cumulative CF"
    ))
    fig2.add_hline(y=0, line_color="black", line_width=0.5)
    fig2.update_layout(xaxis_title="Day", yaxis=dict(title="Cash Flow ($)", tickformat="$,.0f"),
                        height=280, plot_bgcolor="#fafafa")
    st.plotly_chart(fig2, use_container_width=True)

    # Event log
    st.subheader("📋 Lifecycle Event Log")
    EVENT_COLORS = {
        EventType.OPEN: "#1565c0", EventType.MARGIN_CALL: "#e65100",
        EventType.MARGIN_MET: "#2e7d32", EventType.SUBSTITUTION: "#6a1b9a",
        EventType.ROLL: "#6a1b9a", EventType.CLOSE: "#2e7d32", EventType.DEFAULT: "#c62828",
    }
    EVENT_ICONS = {
        EventType.OPEN: "📄", EventType.MARGIN_CALL: "⚠️", EventType.MARGIN_MET: "✅",
        EventType.SUBSTITUTION: "🔄", EventType.ROLL: "🔄", EventType.CLOSE: "✅", EventType.DEFAULT: "🔴",
    }
    for event in events:
        icon = EVENT_ICONS.get(event.event_type, "•")
        color = EVENT_COLORS.get(event.event_type, "#000")
        cf_str = f" | CF: ${event.cash_flow:+,.0f}" if event.cash_flow != 0 else ""
        st.markdown(
            f"<div style='padding:0.4rem 0.8rem; margin:0.2rem 0; border-left:3px solid {color}; "
            f"background:#fafafa; border-radius:4px;'>"
            f"<span style='color:#546e7a; font-size:0.8rem;'>Day {event.day:02d}</span> "
            f"{icon} <span style='color:{color};'>{event.description}</span>"
            f"<span style='color:#546e7a; font-size:0.85rem;'>{cf_str}</span></div>",
            unsafe_allow_html=True
        )

    # Concepts
    st.markdown("---")
    st.subheader("📚 Key Concepts")
    with st.expander("What is a Haircut?"):
        st.write("A haircut is a % discount on collateral MV protecting the lender against price drops. "
                 "E.g. $50M MBS with 5% haircut → MS lends only $47.5M. The $2.5M is the safety buffer.")
    with st.expander("What is a Margin Call?"):
        st.write("If collateral drops in value, coverage falls. When the shortfall exceeds the threshold, "
                 "MS issues a margin call: client must post more cash, substitute collateral, or face close-out.")
    with st.expander("What is a Repo Roll?"):
        st.write("At maturity, the client can renew the repo for another term at a new negotiated rate. "
                 "Overnight repos are rolled daily by many clients.")
    with st.expander("Haircuts by Asset Class"):
        df_h = pd.DataFrame([{"Asset Class": ct.value, "Haircut": f"{v*100:.1f}%"}
                              for ct, v in STANDARD_HAIRCUTS.items()])
        st.dataframe(df_h, use_container_width=True, hide_index=True)


# ════════════════════════════════════════════════════════════════════════════
# PAGE 2 — SBL SETTLEMENT TRACKER
# ════════════════════════════════════════════════════════════════════════════
else:
    st.info(
        "**Securities Borrowing & Lending (SBL):** Institutions lend securities they hold "
        "to earn fees, receiving collateral (cash or bonds) in return. This tracker simulates "
        "a collateral management desk: position availability, settlement monitoring, "
        "fail management, and counterparty exposure — core to roles like NBC Capital Markets Operations.",
        icon="ℹ️"
    )

    with st.sidebar:
        st.header("🔧 SBL Parameters")
        n_transactions = st.slider("Number of Transactions", min_value=5, max_value=40, value=18)
        fail_rate = st.slider("Settlement Fail Rate (%)", min_value=0, max_value=40, value=15) / 100
        seed = st.number_input("Random Seed", min_value=1, max_value=999, value=42)
        st.caption("Change seed to generate different transaction sets.")

        st.subheader("Filters")
        filter_direction = st.multiselect("Direction", options=["Lend", "Borrow"], default=["Lend", "Borrow"])
        filter_status = st.multiselect("Status", options=["Pending", "Settled", "Failed", "Partial Fill"],
                                        default=["Pending", "Settled", "Failed", "Partial Fill"])

    # Generate data
    portfolio = build_sample_portfolio(seed=int(seed))
    transactions = generate_sbl_transactions(portfolio, n_transactions, fail_rate, seed=int(seed))
    exposures = compute_counterparty_exposures(transactions)
    summary = settlement_summary(transactions)

    # ── KPIs ─────────────────────────────────────────────────────────────────
    st.subheader("📌 Today's Settlement Dashboard")
    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Total Transactions", summary["total"])
    k2.metric("Settled", summary["settled"], delta=f"{summary['settlement_rate']*100:.0f}% rate")
    k3.metric("Pending", summary["pending"])
    k4.metric("Failed", summary["failed"],
              delta=f"-${summary['failed_notional']:,.0f}" if summary["failed"] > 0 else None,
              delta_color="inverse")
    k5.metric("Daily Fees Earned", f"${summary['daily_fees_earned']:,.0f}")

    # ── Settlement Status Donut ───────────────────────────────────────────────
    col_a, col_b = st.columns(2)

    with col_a:
        st.subheader("Settlement Status Breakdown")
        status_counts = {
            "Settled": summary["settled"],
            "Pending": summary["pending"],
            "Failed": summary["failed"],
            "Partial": summary["partial"],
        }
        colors = {"Settled": "#2e7d32", "Pending": "#1565c0", "Failed": "#c62828", "Partial": "#e65100"}
        fig_donut = go.Figure(go.Pie(
            labels=list(status_counts.keys()),
            values=list(status_counts.values()),
            hole=0.55,
            marker_colors=[colors[k] for k in status_counts],
        ))
        fig_donut.update_layout(height=320, showlegend=True, margin=dict(t=10, b=10))
        st.plotly_chart(fig_donut, use_container_width=True)

    with col_b:
        st.subheader("Notional by Asset Class")
        ac_data = {}
        for t in transactions:
            ac = t.position.asset_class.value
            ac_data[ac] = ac_data.get(ac, 0) + t.notional_value
        fig_bar = go.Figure(go.Bar(
            x=list(ac_data.keys()),
            y=list(ac_data.values()),
            marker_color=["#1565c0", "#2e7d32", "#e65100", "#6a1b9a"],
            text=[f"${v/1e6:.1f}M" for v in ac_data.values()],
            textposition="outside",
        ))
        fig_bar.update_layout(
            height=320, yaxis=dict(tickformat="$,.0f", title="Notional ($)"),
            plot_bgcolor="#fafafa", margin=dict(t=10, b=10)
        )
        st.plotly_chart(fig_bar, use_container_width=True)

    # ── Counterparty Exposure Table ───────────────────────────────────────────
    st.subheader("🏦 Counterparty Collateral Exposure")
    if exposures:
        exp_rows = []
        for e in exposures:
            flag = "🔴 UNDER" if e.is_undercollateralized else "✅ OK"
            exp_rows.append({
                "Counterparty": e.counterparty,
                "Securities Lent ($)": f"${e.total_lent_value:,.0f}",
                "Collateral Received ($)": f"${e.total_collateral_received:,.0f}",
                "Coverage Ratio": f"{e.coverage_ratio:.3f}x",
                "Status": flag,
                "Open Trades": e.open_transactions,
                "Failed": e.failed_settlements,
            })
        df_exp = pd.DataFrame(exp_rows)
        st.dataframe(df_exp, use_container_width=True, hide_index=True)
    else:
        st.info("No lending transactions in current dataset.")

    # ── Portfolio Availability ────────────────────────────────────────────────
    st.subheader("📦 Portfolio — Available to Lend")
    port_rows = []
    for p in portfolio:
        port_rows.append({
            "Ticker": p.ticker,
            "Name": p.name,
            "Asset Class": p.asset_class.value,
            "Total Qty": f"{p.quantity:,}",
            "Market Price": f"${p.market_price:,.2f}",
            "Market Value ($)": f"${p.market_value:,.0f}",
            "Available to Lend (%)": f"{p.available_to_lend*100:.0f}%",
            "Lendable Value ($)": f"${p.lendable_value:,.0f}",
        })
    df_port = pd.DataFrame(port_rows)
    st.dataframe(df_port, use_container_width=True, hide_index=True)

    # ── Transaction Log ───────────────────────────────────────────────────────
    st.subheader("📋 Transaction Log")

    # Apply filters
    filtered = [
        t for t in transactions
        if t.direction.value in filter_direction
        and t.status.value in filter_status
    ]

    STATUS_COLORS = {
        SettlementStatus.SETTLED: "#2e7d32",
        SettlementStatus.PENDING: "#1565c0",
        SettlementStatus.FAILED: "#c62828",
        SettlementStatus.PARTIAL: "#e65100",
    }
    STATUS_ICONS = {
        SettlementStatus.SETTLED: "✅",
        SettlementStatus.PENDING: "⏳",
        SettlementStatus.FAILED: "🔴",
        SettlementStatus.PARTIAL: "⚠️",
    }

    for t in filtered:
        color = STATUS_COLORS[t.status]
        icon = STATUS_ICONS[t.status]
        fail_note = f" — {t.fail_reason}" if t.fail_reason else ""
        direction_arrow = "📤 LEND" if t.direction == LoanDirection.LEND else "📥 BORROW"
        st.markdown(
            f"<div style='padding:0.45rem 0.8rem; margin:0.2rem 0; border-left:3px solid {color}; "
            f"background:#fafafa; border-radius:4px; font-size:0.9rem;'>"
            f"<b>{t.transaction_id}</b> &nbsp;|&nbsp; {direction_arrow} &nbsp;|&nbsp; "
            f"<b>{t.counterparty}</b> &nbsp;|&nbsp; "
            f"{t.quantity:,} × {t.position.ticker} @ ${t.position.market_price:.2f} &nbsp;|&nbsp; "
            f"Notional: <b>${t.notional_value:,.0f}</b> &nbsp;|&nbsp; "
            f"Rate: {t.rate*100:.3f}% &nbsp;|&nbsp; "
            f"Settle: {t.settlement_date.strftime('%b %d')} &nbsp;|&nbsp; "
            f"{icon} <span style='color:{color};'><b>{t.status.value}</b></span>{fail_note}"
            f"</div>",
            unsafe_allow_html=True
        )

    if not filtered:
        st.warning("No transactions match the selected filters.")

    # ── SBL Concepts ──────────────────────────────────────────────────────────
    st.markdown("---")
    st.subheader("📚 Key Concepts")
    with st.expander("What is Securities Borrowing & Lending?"):
        st.write("SBL allows institutions holding securities (e.g. a pension fund with $500M in equities) "
                 "to lend them to borrowers (typically hedge funds covering short positions) in exchange "
                 "for a lending fee. The borrower posts collateral (102% of notional) to protect the lender.")
    with st.expander("What is a Settlement Fail?"):
        st.write("A fail occurs when a transaction does not settle on its expected date — usually T+2. "
                 "Common causes: counterparty lacks the securities, operational issues at DTCC/CDS, "
                 "corporate actions freezing shares, or late confirmations. Fails create operational risk "
                 "and must be resolved by the collateral management team.")
    with st.expander("Why 102% Collateral?"):
        st.write("The 2% overcollateralization buffer protects the lender if the borrower defaults "
                 "and the collateral must be liquidated quickly. For volatile equities, haircuts are higher. "
                 "This margin is marked to market daily — if it drops below 100%, a margin call is issued.")
    with st.expander("What does the Collateral Management team do daily?"):
        st.write("• Monitor all open transactions and upcoming settlements\n"
                 "• Identify and resolve settlement fails with counterparties and DTCC/CDS\n"
                 "• Mark collateral positions to market and trigger margin calls where needed\n"
                 "• Optimize available collateral across counterparties\n"
                 "• Report exposure to front office traders and risk management")

# ── Footer ────────────────────────────────────────────────────────────────────
st.markdown("---")
st.caption(
    "Built by Steve Rudy Komguep Jouenang — BCom Finance, Telfer School of Management (Dean's List) "
)
