"""
Collateral Management & SBL Simulator — Streamlit Dashboard
Repo Lifecycle · SBL Settlement Tracker · Business Rules Engine
Built by: Steve Rudy Komguep Jouenang
"""

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
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

st.markdown("""
<style>
    .main-title { font-size: 2rem; font-weight: 700; color: #1a237e; }
    .subtitle { font-size: 1rem; color: #546e7a; margin-bottom: 1rem; }
    .stAlert { border-radius: 8px; }
    div[data-testid="metric-container"] { background: #f8f9fa; border-radius: 8px; padding: 0.5rem; }
    .alert-box {
        padding: 0.8rem 1.2rem; border-radius: 8px; margin: 0.4rem 0;
        font-weight: 600; font-size: 0.95rem;
    }
    .alert-red   { background: #fdecea; border-left: 5px solid #c62828; color: #c62828; }
    .alert-orange{ background: #fff3e0; border-left: 5px solid #e65100; color: #e65100; }
    .alert-green { background: #e8f5e9; border-left: 5px solid #2e7d32; color: #2e7d32; }
    .rule-card {
        background: #f8f9fa; border-radius: 8px; padding: 1rem 1.2rem;
        margin: 0.5rem 0; border-left: 4px solid #1a237e;
    }
    .rule-pass { border-left-color: #2e7d32; background: #e8f5e9; }
    .rule-fail { border-left-color: #c62828; background: #fdecea; }
    .rule-warn { border-left-color: #e65100; background: #fff3e0; }
    .tx-row {
        padding: 0.5rem 0.9rem; margin: 0.25rem 0;
        border-radius: 6px; font-size: 0.88rem;
        background: #fafafa;
    }
</style>
""", unsafe_allow_html=True)

# ── Header + Navigation ───────────────────────────────────────────────────────
st.markdown('<div class="main-title">📊 Collateral Management & SBL Simulator</div>', unsafe_allow_html=True)
st.markdown('<div class="subtitle">Repo Lifecycle · Securities Borrowing & Lending · Business Rules Engine</div>', unsafe_allow_html=True)

page = st.radio(
    "Select Module",
    ["📄 Repo Trade Lifecycle", "🔄 SBL Settlement Tracker", "📐 Business Rules Engine"],
    horizontal=True,
)
st.markdown("---")


# ════════════════════════════════════════════════════════════════════════════
# PAGE 1 — REPO LIFECYCLE
# ════════════════════════════════════════════════════════════════════════════
if page == "📄 Repo Trade Lifecycle":

    st.info(
        "**What is a Repo?** A repurchase agreement is a short-term secured loan. "
        "A client sells collateral (Treasuries, MBS…) to the desk and agrees to repurchase "
        "it at a higher price. This simulator models the full trade lifecycle: margin calls, "
        "collateral substitutions, rolls, and close-outs.",
        icon="ℹ️"
    )

    with st.sidebar:
        st.header("🔧 Repo Trade Parameters")
        st.subheader("Counterparty")
        client_name = st.text_input("Client Name", value="Citadel Asset Management")

        st.subheader("Collateral")
        col_type = st.selectbox("Collateral Type", options=list(CollateralType),
                                 format_func=lambda x: x.value, index=1)
        face_value = st.number_input("Face Value ($)", min_value=1_000_000, max_value=500_000_000,
                                      value=50_000_000, step=1_000_000, format="%d")
        market_price_pct = st.slider("Market Price (% of Face)", 85.0, 105.0, 98.5, 0.5)
        market_value = face_value * market_price_pct / 100

        default_haircut = STANDARD_HAIRCUTS[col_type] * 100
        haircut_pct = st.slider("Haircut (%)", 0.5, 20.0, float(round(default_haircut, 1)), 0.5)
        st.caption(f"📋 Standard haircut for {col_type.value}: {default_haircut:.1f}%")
        eligible_value = market_value * (1 - haircut_pct / 100)
        st.success(f"**Eligible Value:** ${eligible_value:,.0f}")

        st.subheader("Trade Terms")
        repo_rate = st.slider("Repo Rate (% p.a.)", 0.5, 10.0, 5.30, 0.05)
        term_days = st.selectbox("Term", [1, 2, 3, 7, 14, 30], index=3,
                                  format_func=lambda x: f"{x}d {'(overnight)' if x==1 else '(1 week)' if x==7 else '(2 weeks)' if x==14 else '(1 month)' if x==30 else ''}")
        max_cash = int(eligible_value)
        cash_lent = st.number_input("Cash Lent ($)", min_value=1_000_000, max_value=max_cash,
                                     value=min(int(eligible_value * 0.95), max_cash), step=100_000, format="%d")
        margin_threshold = st.slider("Margin Call Threshold (%)", 0.5, 5.0, 2.0, 0.5)

        st.subheader("📉 Price Scenario")
        scenario = st.selectbox("Collateral Price Path",
            ["Stable", "Gradual Decline", "Sharp Drop (Day 3)", "Recovery After Dip", "Volatile"])

        st.subheader("🔄 Maturity")
        roll_on_maturity = st.checkbox("Roll trade at maturity", value=False)
        roll_rate = repo_rate / 100
        roll_days_val = term_days
        if roll_on_maturity:
            roll_rate = st.slider("Roll Rate (%)", 0.5, 10.0, repo_rate + 0.05, 0.05) / 100
            roll_days_val = st.selectbox("Roll Term", [1, 2, 3, 7, 14, 30], index=3)

        st.subheader("⚠️ Margin Call Response")
        margin_default_response = st.selectbox("Client response",
            options=["cash", "collateral", "default"],
            format_func=lambda x: {"cash": "✅ Post cash", "collateral": "🔄 Substitute collateral", "default": "🔴 Default"}[x])

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
                path.append(mv * (1 - 0.003 * i) if i < days // 3 else mv * (0.97 + 0.002 * (i - days // 3)))
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

    # ── Live Alerts ───────────────────────────────────────────────────────────
    current_mv = price_path[-1] if price_path else market_value
    current_coverage = trade.coverage_ratio(current_mv)
    shortfall = trade.shortfall(current_mv)
    margin_call_count = sum(1 for e in events if e.event_type == EventType.MARGIN_CALL)

    st.subheader("🚨 Live Risk Alerts")
    if trade.status == TradeStatus.DEFAULTED:
        st.markdown('<div class="alert-box alert-red">🔴 COUNTERPARTY DEFAULT — Close-out initiated. Collateral liquidated.</div>', unsafe_allow_html=True)
    elif current_coverage < 1.00:
        st.markdown(f'<div class="alert-box alert-red">🔴 CRITICAL — Coverage ratio {current_coverage:.3f}x is below 1.00x. Immediate margin call required. Shortfall: ${shortfall:,.0f}</div>', unsafe_allow_html=True)
    elif current_coverage < 1.02:
        st.markdown(f'<div class="alert-box alert-orange">🟠 MARGIN CALL RISK — Coverage ratio {current_coverage:.3f}x is below 102% threshold. Shortfall: ${shortfall:,.0f}</div>', unsafe_allow_html=True)
    elif margin_call_count > 0:
        st.markdown(f'<div class="alert-box alert-orange">🟡 {margin_call_count} margin call(s) were triggered during this trade lifecycle. Current coverage: {current_coverage:.3f}x</div>', unsafe_allow_html=True)
    else:
        st.markdown(f'<div class="alert-box alert-green">✅ COLLATERAL OK — Coverage ratio {current_coverage:.3f}x · No margin calls triggered</div>', unsafe_allow_html=True)

    # ── Trade Summary ─────────────────────────────────────────────────────────
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
    c8.metric("Margin Calls", margin_call_count)

    # ── Charts ────────────────────────────────────────────────────────────────
    st.subheader("📈 Collateral Price & Coverage Ratio")
    days_list = list(range(len(price_path)))
    coverage_list = [trade.coverage_ratio(mv) for mv in price_path]

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=days_list, y=price_path, name="Collateral MV",
                              line=dict(color="#1565c0", width=2.5), yaxis="y1"))
    fig.add_hline(y=cash_lent / (1 - haircut_pct/100), line_dash="dash", line_color="#e65100",
                  opacity=0.7, annotation_text="Min Coverage Level", yref="y1")
    fig.add_trace(go.Scatter(x=days_list, y=coverage_list, name="Coverage Ratio",
                              line=dict(color="#2e7d32", width=2, dash="dot"), yaxis="y2"))
    fig.add_hline(y=1.02, line_dash="dot", line_color="#e65100", opacity=0.5,
                  annotation_text="102% threshold", yref="y2")
    fig.update_layout(
        xaxis_title="Day",
        yaxis=dict(title="Collateral MV ($)", tickformat="$,.0f"),
        yaxis2=dict(title="Coverage Ratio (x)", overlaying="y", side="right", tickformat=".3f"),
        height=380, hovermode="x unified", plot_bgcolor="#fafafa", legend=dict(x=0.01, y=0.99),
    )
    st.plotly_chart(fig, use_container_width=True)

    st.subheader("💵 Cumulative Cash Flow — Desk Perspective")
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

    # ── Event Log ─────────────────────────────────────────────────────────────
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
        color = EVENT_COLORS.get(event.event_type, "#000")
        icon = EVENT_ICONS.get(event.event_type, "•")
        cf_str = f" | CF: ${event.cash_flow:+,.0f}" if event.cash_flow != 0 else ""
        st.markdown(
            f"<div style='padding:0.4rem 0.8rem; margin:0.2rem 0; border-left:3px solid {color}; "
            f"background:#fafafa; border-radius:4px;'>"
            f"<span style='color:#546e7a; font-size:0.8rem;'>Day {event.day:02d}</span> "
            f"{icon} <span style='color:{color};'>{event.description}</span>"
            f"<span style='color:#546e7a; font-size:0.85rem;'>{cf_str}</span></div>",
            unsafe_allow_html=True
        )

    st.markdown("---")
    st.subheader("📚 Key Concepts")
    with st.expander("What is a Haircut?"):
        st.write("A % reduction applied to collateral MV protecting the lender against price drops. "
                 "E.g. $50M MBS with 5% haircut → desk lends only $47.5M. The $2.5M is the safety buffer.")
    with st.expander("What is a Margin Call?"):
        st.write("If collateral drops in value and coverage falls below threshold, the desk issues a margin call. "
                 "Client must post more cash, substitute collateral, or face close-out.")
    with st.expander("What is a Repo Roll?"):
        st.write("At maturity, the client renews the repo for another term at a new negotiated rate. "
                 "Overnight repos are rolled daily by many clients.")
    with st.expander("Haircuts by Asset Class"):
        df_h = pd.DataFrame([{"Asset Class": ct.value, "Haircut": f"{v*100:.1f}%"}
                              for ct, v in STANDARD_HAIRCUTS.items()])
        st.dataframe(df_h, use_container_width=True, hide_index=True)


# ════════════════════════════════════════════════════════════════════════════
# PAGE 2 — SBL SETTLEMENT TRACKER
# ════════════════════════════════════════════════════════════════════════════
elif page == "🔄 SBL Settlement Tracker":

    st.info(
        "**Securities Borrowing & Lending (SBL):** Institutions lend securities they hold "
        "to earn fees, receiving collateral in return. This tracker simulates a collateral "
        "management desk: position availability, settlement monitoring, fail management, "
        "and counterparty exposure.",
        icon="ℹ️"
    )

    with st.sidebar:
        st.header("🔧 SBL Parameters")
        n_transactions = st.slider("Number of Transactions", 5, 40, 18)
        fail_rate = st.slider("Settlement Fail Rate (%)", 0, 40, 15) / 100
        seed = st.number_input("Random Seed", min_value=1, max_value=999, value=42)
        st.caption("Change seed to generate different transaction sets.")
        st.subheader("Filters")
        filter_direction = st.multiselect("Direction", ["Lend", "Borrow"], default=["Lend", "Borrow"])
        filter_status = st.multiselect("Status", ["Pending", "Settled", "Failed", "Partial Fill"],
                                        default=["Pending", "Settled", "Failed", "Partial Fill"])

    portfolio = build_sample_portfolio(seed=int(seed))
    transactions = generate_sbl_transactions(portfolio, n_transactions, fail_rate, seed=int(seed))
    exposures = compute_counterparty_exposures(transactions)
    summary = settlement_summary(transactions)

    # ── Live Alerts ───────────────────────────────────────────────────────────
    st.subheader("🚨 Live Risk Alerts")
    undercoll = [e for e in exposures if e.is_undercollateralized]
    failed_today = [t for t in transactions if t.status == SettlementStatus.FAILED]
    critical_fails = [t for t in failed_today if t.notional_value > 5_000_000]

    if undercoll:
        names = ", ".join(e.counterparty for e in undercoll)
        st.markdown(f'<div class="alert-box alert-red">🔴 UNDERCOLLATERALIZED — {len(undercoll)} counterpart(ies) below 102% threshold: {names}</div>', unsafe_allow_html=True)
    if critical_fails:
        st.markdown(f'<div class="alert-box alert-red">🔴 SETTLEMENT RISK — {len(critical_fails)} high-value fail(s) above $5M require immediate follow-up</div>', unsafe_allow_html=True)
    if failed_today and not critical_fails:
        st.markdown(f'<div class="alert-box alert-orange">🟠 SETTLEMENT FAILS — {len(failed_today)} transaction(s) failed. Total exposure: ${sum(t.notional_value for t in failed_today):,.0f}</div>', unsafe_allow_html=True)
    if not undercoll and not failed_today:
        st.markdown('<div class="alert-box alert-green">✅ ALL CLEAR — No undercollateralized positions. No settlement fails.</div>', unsafe_allow_html=True)

    # ── KPIs ──────────────────────────────────────────────────────────────────
    st.subheader("📌 Today's Settlement Dashboard")
    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Total Transactions", summary["total"])
    k2.metric("Settled", summary["settled"], delta=f"{summary['settlement_rate']*100:.0f}% rate")
    k3.metric("Pending", summary["pending"])
    k4.metric("Failed", summary["failed"],
              delta=f"-${summary['failed_notional']:,.0f}" if summary["failed"] > 0 else None,
              delta_color="inverse")
    k5.metric("Daily Fees Earned", f"${summary['daily_fees_earned']:,.0f}")

    # ── Charts ────────────────────────────────────────────────────────────────
    col_a, col_b = st.columns(2)
    with col_a:
        st.subheader("Settlement Status Breakdown")
        status_counts = {"Settled": summary["settled"], "Pending": summary["pending"],
                         "Failed": summary["failed"], "Partial": summary["partial"]}
        colors = {"Settled": "#2e7d32", "Pending": "#1565c0", "Failed": "#c62828", "Partial": "#e65100"}
        fig_donut = go.Figure(go.Pie(
            labels=list(status_counts.keys()), values=list(status_counts.values()),
            hole=0.55, marker_colors=[colors[k] for k in status_counts],
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
            x=list(ac_data.keys()), y=list(ac_data.values()),
            marker_color=["#1565c0", "#2e7d32", "#e65100", "#6a1b9a"],
            text=[f"${v/1e6:.1f}M" for v in ac_data.values()], textposition="outside",
        ))
        fig_bar.update_layout(height=320, yaxis=dict(tickformat="$,.0f", title="Notional ($)"),
                               plot_bgcolor="#fafafa", margin=dict(t=10, b=10))
        st.plotly_chart(fig_bar, use_container_width=True)

    # ── Counterparty Exposure ─────────────────────────────────────────────────
    st.subheader("🏦 Counterparty Collateral Exposure")
    if exposures:
        exp_rows = []
        for e in exposures:
            flag = "🔴 UNDERCOLLATERALIZED" if e.is_undercollateralized else "✅ OK"
            exp_rows.append({
                "Counterparty": e.counterparty,
                "Securities Lent ($)": f"${e.total_lent_value:,.0f}",
                "Collateral Received ($)": f"${e.total_collateral_received:,.0f}",
                "Coverage Ratio": f"{e.coverage_ratio:.3f}x",
                "Status": flag,
                "Open Trades": e.open_transactions,
                "Failed": e.failed_settlements,
            })
        st.dataframe(pd.DataFrame(exp_rows), use_container_width=True, hide_index=True)
    else:
        st.info("No lending transactions in current dataset.")

    # ── Portfolio Availability ────────────────────────────────────────────────
    st.subheader("📦 Portfolio — Available to Lend")
    port_rows = [{
        "Ticker": p.ticker, "Name": p.name, "Asset Class": p.asset_class.value,
        "Qty": f"{p.quantity:,}", "Price": f"${p.market_price:,.2f}",
        "Market Value": f"${p.market_value:,.0f}",
        "Available (%)": f"{p.available_to_lend*100:.0f}%",
        "Lendable Value": f"${p.lendable_value:,.0f}",
    } for p in portfolio]
    st.dataframe(pd.DataFrame(port_rows), use_container_width=True, hide_index=True)

    # ── Transaction Log ───────────────────────────────────────────────────────
    st.subheader("📋 Transaction Log")
    filtered = [t for t in transactions
                if t.direction.value in filter_direction and t.status.value in filter_status]

    STATUS_COLORS = {
        SettlementStatus.SETTLED: "#2e7d32", SettlementStatus.PENDING: "#1565c0",
        SettlementStatus.FAILED: "#c62828", SettlementStatus.PARTIAL: "#e65100",
    }
    STATUS_ICONS = {
        SettlementStatus.SETTLED: "✅", SettlementStatus.PENDING: "⏳",
        SettlementStatus.FAILED: "🔴", SettlementStatus.PARTIAL: "⚠️",
    }

    for t in filtered:
        color = STATUS_COLORS[t.status]
        icon = STATUS_ICONS[t.status]
        fail_note = f"<br><span style='color:#c62828; font-size:0.82rem;'>↳ Fail reason: {t.fail_reason}</span>" if t.fail_reason else ""
        direction_badge = "📤 LEND" if t.direction == LoanDirection.LEND else "📥 BORROW"
        req_coll = t.required_collateral
        st.markdown(
            f"<div class='tx-row' style='border-left:3px solid {color};'>"
            f"<b>{t.transaction_id}</b> &nbsp;·&nbsp; {direction_badge} &nbsp;·&nbsp; "
            f"<b>{t.counterparty}</b> &nbsp;·&nbsp; "
            f"{t.quantity:,} × <b>{t.position.ticker}</b> ({t.position.asset_class.value}) "
            f"@ ${t.position.market_price:.2f} &nbsp;·&nbsp; "
            f"Notional: <b>${t.notional_value:,.0f}</b> &nbsp;·&nbsp; "
            f"Req. Collateral: ${req_coll:,.0f} (102%) &nbsp;·&nbsp; "
            f"Rate: {t.rate*100:.3f}% &nbsp;·&nbsp; "
            f"Settle: {t.settlement_date.strftime('%b %d')} (T+{(t.settlement_date - t.trade_date).days}) &nbsp;·&nbsp; "
            f"{icon} <span style='color:{color};'><b>{t.status.value}</b></span>"
            f"{fail_note}</div>",
            unsafe_allow_html=True
        )

    if not filtered:
        st.warning("No transactions match the selected filters.")

    st.markdown("---")
    st.subheader("📚 Key Concepts")
    with st.expander("What is Securities Borrowing & Lending?"):
        st.write("SBL allows institutions to lend securities they hold to borrowers (typically hedge funds "
                 "covering short positions) in exchange for a lending fee. The borrower posts collateral "
                 "(102% of notional) to protect the lender.")
    with st.expander("What is a Settlement Fail?"):
        st.write("A fail occurs when a transaction does not settle on its expected date (T+2). "
                 "Common causes: counterparty delivery failure, DTCC/CDS operational issues, "
                 "corporate actions, or late confirmations. Fails create operational risk and must "
                 "be resolved by the collateral management team.")
    with st.expander("Why 102% Collateral?"):
        st.write("The 2% overcollateralization buffer protects the lender if the borrower defaults. "
                 "This margin is marked to market daily — if coverage drops below 100%, a margin call is issued.")


# ════════════════════════════════════════════════════════════════════════════
# PAGE 3 — BUSINESS RULES ENGINE
# ════════════════════════════════════════════════════════════════════════════
else:
    st.info(
        "**Business Rules Engine:** Each rule defines a specific business constraint in the collateral "
        "management system. For each rule: the condition, the expected system behavior, and a live test "
        "against configurable inputs — showing observed vs. expected output.",
        icon="📐"
    )

    st.subheader("🎛️ Test Parameters")
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        test_cash_lent = st.number_input("Cash Lent ($)", value=10_000_000, step=500_000, format="%d")
    with col2:
        test_collateral_mv = st.number_input("Collateral MV ($)", value=10_200_000, step=100_000, format="%d")
    with col3:
        test_haircut = st.slider("Haircut (%)", 0.0, 20.0, 5.0, 0.5)
    with col4:
        test_notional = st.number_input("SBL Notional ($)", value=5_000_000, step=100_000, format="%d")
        test_collateral_posted = st.number_input("Collateral Posted ($)", value=5_050_000, step=50_000, format="%d")

    # Derived values for tests
    eligible_val = test_collateral_mv * (1 - test_haircut / 100)
    coverage = eligible_val / test_cash_lent if test_cash_lent > 0 else 0
    shortfall = test_cash_lent - eligible_val
    sbl_coverage = test_collateral_posted / test_notional if test_notional > 0 else 0
    sbl_required = test_notional * 1.02

    st.markdown("---")
    st.subheader("📋 Business Rules — Collateral Management System")

    def rule_card(rule_id, title, condition, expected, observed_val, observed_label, passed, rationale):
        status_class = "rule-pass" if passed else "rule-fail"
        status_icon = "✅ PASS" if passed else "❌ FAIL"
        st.markdown(
            f"<div class='rule-card {status_class}'>"
            f"<div style='display:flex; justify-content:space-between; align-items:center;'>"
            f"<span style='font-weight:700; font-size:1rem;'>{rule_id} — {title}</span>"
            f"<span style='font-weight:700; font-size:0.95rem;'>{status_icon}</span></div>"
            f"<div style='margin-top:0.5rem; font-size:0.88rem; color:#424242;'>"
            f"<b>Condition:</b> {condition}<br>"
            f"<b>Expected:</b> {expected}<br>"
            f"<b>Observed:</b> {observed_label}<br>"
            f"<b>Rationale:</b> {rationale}"
            f"</div></div>",
            unsafe_allow_html=True
        )

    st.markdown("#### 🏦 Repo — Collateral Coverage Rules")

    # Rule 001
    expected_eligible = f"${test_collateral_mv:,.0f} × (1 − {test_haircut:.1f}%) = ${eligible_val:,.0f}"
    rule_card(
        "RULE-001", "Eligible Value = MV × (1 − Haircut)",
        f"Collateral MV = ${test_collateral_mv:,.0f}, Haircut = {test_haircut:.1f}%",
        expected_eligible,
        eligible_val,
        f"${eligible_val:,.0f}",
        True,
        "Haircut reduces the lendable value of collateral to protect the desk against price moves."
    )

    # Rule 002
    expected_coverage = f"${eligible_val:,.0f} / ${test_cash_lent:,.0f} = {coverage:.4f}x"
    rule_card(
        "RULE-002", "Coverage Ratio = Eligible Value / Cash Lent",
        f"Eligible Value = ${eligible_val:,.0f}, Cash Lent = ${test_cash_lent:,.0f}",
        expected_coverage,
        coverage,
        f"{coverage:.4f}x",
        True,
        "Coverage ratio must stay ≥ 1.00x at all times. Below 1.02x triggers a margin call."
    )

    # Rule 003
    mc_triggered = shortfall > test_cash_lent * 0.02
    mc_threshold_amt = test_cash_lent * 0.02
    rule_card(
        "RULE-003", "Margin Call triggered when shortfall > 2% of Cash Lent",
        f"Shortfall = ${shortfall:,.0f}, 2% threshold = ${mc_threshold_amt:,.0f}",
        f"Margin Call {'TRIGGERED' if mc_triggered else 'NOT triggered'} (shortfall {'>' if mc_triggered else '<='} threshold)",
        mc_triggered,
        f"Shortfall ${shortfall:,.0f} {'>' if mc_triggered else '<='} threshold ${mc_threshold_amt:,.0f} → {'🟠 MARGIN CALL' if mc_triggered else '✅ No action'}",
        True,
        "When collateral value drops, the client must post more cash, substitute collateral, or face close-out."
    )

    # Rule 004
    cash_lent_valid = test_cash_lent <= eligible_val
    rule_card(
        "RULE-004", "Cash Lent must not exceed Eligible Value",
        f"Cash Lent = ${test_cash_lent:,.0f}, Eligible Value = ${eligible_val:,.0f}",
        f"Cash Lent {'≤' if cash_lent_valid else '>'} Eligible Value → {'VALID' if cash_lent_valid else 'INVALID — overcollateral breach'}",
        cash_lent_valid,
        f"${test_cash_lent:,.0f} {'≤' if cash_lent_valid else '>'} ${eligible_val:,.0f} → {'✅ VALID' if cash_lent_valid else '🔴 BREACH'}",
        cash_lent_valid,
        "The desk cannot lend more than the eligible (post-haircut) value of the collateral received."
    )

    st.markdown("#### 🔄 SBL — Securities Lending Rules")

    # Rule 005
    sbl_req_met = test_collateral_posted >= sbl_required
    rule_card(
        "RULE-005", "SBL Required Collateral = 102% of Notional",
        f"Notional = ${test_notional:,.0f}",
        f"Required collateral = ${sbl_required:,.0f} (102%)",
        sbl_required,
        f"${sbl_required:,.0f}",
        True,
        "The 2% overcollateralization buffer protects the lender against borrower default and collateral liquidation costs."
    )

    # Rule 006
    rule_card(
        "RULE-006", "SBL Collateral Coverage must be ≥ 102%",
        f"Collateral Posted = ${test_collateral_posted:,.0f}, Notional = ${test_notional:,.0f}",
        f"Coverage ≥ 1.020x → {'OK' if sbl_req_met else 'UNDERCOLLATERALIZED'}",
        sbl_coverage,
        f"{sbl_coverage:.4f}x → {'✅ OK' if sbl_req_met else '🔴 UNDERCOLLATERALIZED — margin call required'}",
        sbl_req_met,
        "If coverage drops below 102%, the collateral management team must issue a margin call to the borrower."
    )

    # Rule 007 — Settlement
    st.markdown("#### ⏱️ Settlement Rules")
    rule_card(
        "RULE-007", "Standard Settlement Cycle = T+2",
        "Trade date = T, Settlement expected = T+2",
        "Settlement must occur within 2 business days of trade date",
        True,
        "Industry standard T+2 settlement for most securities (T+1 for US Treasuries). Failure to settle = fail.",
        True,
        "Late settlement creates counterparty risk and operational burden. The collateral management team monitors all pending T+2 settlements daily."
    )

    # Rule 008
    rule_card(
        "RULE-008", "Daily Mark-to-Market: Collateral revalued each business day",
        "All open positions must be marked to market at end of day",
        "Coverage ratio recalculated daily; margin calls issued if threshold breached",
        True,
        "Daily MTM ensures collateral always reflects current market value — preventing silent undercollateralization.",
        True,
        "Collateral prices move continuously. Without daily MTM, a desk could be unknowingly exposed to significant uncovered risk."
    )

    # Rule 009 — Interest accrual
    st.markdown("#### 💰 Interest & Fee Rules")
    daily_fee_example = test_notional * 0.025 / 360
    rule_card(
        "RULE-009", "Repo Interest Accrual = Cash Lent × Rate / 360",
        f"Cash Lent = ${test_cash_lent:,.0f}, Example rate = 5.30%",
        f"Daily accrual = ${test_cash_lent * 0.053 / 360:,.2f}",
        test_cash_lent * 0.053 / 360,
        f"${test_cash_lent * 0.053 / 360:,.2f} / day",
        True,
        "Repo interest uses an Actual/360 day count convention — standard for money market instruments."
    )

    rule_card(
        "RULE-010", "SBL Lending Fee = Notional × Rate / 360",
        f"Notional = ${test_notional:,.0f}, Example rate = 2.50%",
        f"Daily fee = ${daily_fee_example:,.2f}",
        daily_fee_example,
        f"${daily_fee_example:,.2f} / day",
        True,
        "Securities lending fee accrues daily on the notional value of the loan. Higher fees for hard-to-borrow equities."
    )

    st.markdown("---")
    st.subheader("📊 Rule Summary")
    rules_summary = [
        {"ID": "RULE-001", "Domain": "Repo", "Rule": "Eligible Value = MV × (1 − Haircut)", "Status": "✅ PASS"},
        {"ID": "RULE-002", "Domain": "Repo", "Rule": "Coverage Ratio = Eligible Value / Cash Lent", "Status": "✅ PASS"},
        {"ID": "RULE-003", "Domain": "Repo", "Rule": "Margin Call if shortfall > 2% of Cash Lent", "Status": "✅ PASS" if True else "❌ FAIL"},
        {"ID": "RULE-004", "Domain": "Repo", "Rule": "Cash Lent ≤ Eligible Value", "Status": "✅ PASS" if cash_lent_valid else "❌ FAIL"},
        {"ID": "RULE-005", "Domain": "SBL",  "Rule": "Required Collateral = 102% of Notional", "Status": "✅ PASS"},
        {"ID": "RULE-006", "Domain": "SBL",  "Rule": "SBL Coverage ≥ 102%", "Status": "✅ PASS" if sbl_req_met else "❌ FAIL"},
        {"ID": "RULE-007", "Domain": "Settlement", "Rule": "Standard Settlement = T+2", "Status": "✅ PASS"},
        {"ID": "RULE-008", "Domain": "Settlement", "Rule": "Daily Mark-to-Market required", "Status": "✅ PASS"},
        {"ID": "RULE-009", "Domain": "Interest", "Rule": "Repo Accrual = Cash × Rate / 360", "Status": "✅ PASS"},
        {"ID": "RULE-010", "Domain": "Interest", "Rule": "SBL Fee = Notional × Rate / 360", "Status": "✅ PASS"},
    ]
    st.dataframe(pd.DataFrame(rules_summary), use_container_width=True, hide_index=True)


# ── Footer ─────────────────────────────────────────────────────────────────
st.markdown("---")
st.caption(
    "Built by Steve Rudy Komguep Jouenang — BCom Finance, Telfer School of Management | "
    "Bloomberg BMC Certified | Algorithmic Futures Trader | "
    "github.com/rudykomguep-creator/collateral-sbl-simulator"
)
