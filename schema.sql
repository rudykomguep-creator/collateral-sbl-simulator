-- ============================================================
-- Collateral Management & SBL — Database Schema
-- ============================================================
-- Relational model for persisting repo trades, SBL transactions,
-- lifecycle events, and counterparty exposure tracking.
-- Compatible with PostgreSQL / SQLite.
-- ============================================================


-- ── Reference Tables ─────────────────────────────────────────────────────────

CREATE TABLE collateral_types (
    id          SERIAL PRIMARY KEY,
    code        VARCHAR(20)  NOT NULL UNIQUE,  -- e.g. 'TREASURY', 'MBS'
    description VARCHAR(100) NOT NULL,
    haircut     DECIMAL(6,4) NOT NULL           -- e.g. 0.0500 = 5%
);

INSERT INTO collateral_types (code, description, haircut) VALUES
    ('TREASURY',  'US Treasury',              0.0200),
    ('MBS',       'MBS (Mortgage-Backed)',     0.0500),
    ('CMBS',      'CMBS (Commercial MBS)',     0.0800),
    ('ABS',       'ABS (Asset-Backed)',        0.0700),
    ('IG_CORP',   'IG Corporate Bond',         0.0600);

CREATE TABLE asset_classes (
    id          SERIAL PRIMARY KEY,
    code        VARCHAR(20)  NOT NULL UNIQUE,
    description VARCHAR(100) NOT NULL
);

INSERT INTO asset_classes (code, description) VALUES
    ('EQUITY',      'Equity'),
    ('GOV_BOND',    'Government Bond'),
    ('CORP_BOND',   'Corporate Bond'),
    ('ETF',         'ETF');


-- ── Repo Tables ───────────────────────────────────────────────────────────────

CREATE TABLE counterparties (
    id              SERIAL PRIMARY KEY,
    name            VARCHAR(200) NOT NULL,
    lei             VARCHAR(20),           -- Legal Entity Identifier
    country         VARCHAR(3),
    client_type     VARCHAR(50),           -- 'HEDGE_FUND', 'ASSET_MANAGER', 'REIT', etc.
    created_at      TIMESTAMP DEFAULT NOW()
);

CREATE TABLE repo_trades (
    id                  SERIAL PRIMARY KEY,
    trade_ref           VARCHAR(30)   NOT NULL UNIQUE,  -- e.g. 'REPO-20260524-0001'
    counterparty_id     INT           NOT NULL REFERENCES counterparties(id),
    collateral_type_id  INT           NOT NULL REFERENCES collateral_types(id),
    face_value          DECIMAL(18,2) NOT NULL,
    collateral_mv       DECIMAL(18,2) NOT NULL,         -- Market value at trade open
    haircut             DECIMAL(6,4)  NOT NULL,
    eligible_value      DECIMAL(18,2) GENERATED ALWAYS AS (collateral_mv * (1 - haircut)) STORED,
    cash_lent           DECIMAL(18,2) NOT NULL,
    repo_rate           DECIMAL(8,6)  NOT NULL,         -- Annual rate e.g. 0.053000
    start_date          DATE          NOT NULL,
    maturity_date       DATE          NOT NULL,
    term_days           INT           NOT NULL,
    margin_threshold    DECIMAL(6,4)  NOT NULL DEFAULT 0.0200,
    status              VARCHAR(30)   NOT NULL DEFAULT 'OPEN',
    -- CHECK constraint on status
    CONSTRAINT chk_repo_status CHECK (status IN ('OPEN','MARGIN_CALL_PENDING','ROLLED','CLOSED','DEFAULTED')),
    created_at          TIMESTAMP     DEFAULT NOW()
);

CREATE TABLE lifecycle_events (
    id              SERIAL PRIMARY KEY,
    trade_id        INT           NOT NULL REFERENCES repo_trades(id),
    event_day       INT           NOT NULL,
    event_date      DATE          NOT NULL,
    event_type      VARCHAR(30)   NOT NULL,
    description     TEXT,
    cash_flow       DECIMAL(18,2) DEFAULT 0,
    collateral_mv   DECIMAL(18,2),
    trade_status    VARCHAR(30),
    created_at      TIMESTAMP     DEFAULT NOW(),
    CONSTRAINT chk_event_type CHECK (event_type IN (
        'TRADE_OPENED','MARGIN_CALL','MARGIN_MET',
        'SUBSTITUTION','ROLL','TRADE_CLOSED','DEFAULT'
    ))
);


-- ── SBL Tables ────────────────────────────────────────────────────────────────

CREATE TABLE securities (
    id              SERIAL PRIMARY KEY,
    ticker          VARCHAR(20)   NOT NULL UNIQUE,
    name            VARCHAR(200)  NOT NULL,
    asset_class_id  INT           NOT NULL REFERENCES asset_classes(id),
    currency        CHAR(3)       NOT NULL DEFAULT 'CAD',
    isin            VARCHAR(12),
    cusip           VARCHAR(9)
);

CREATE TABLE portfolio_positions (
    id                  SERIAL PRIMARY KEY,
    security_id         INT           NOT NULL REFERENCES securities(id),
    quantity            INT           NOT NULL,
    market_price        DECIMAL(14,4) NOT NULL,
    price_date          DATE          NOT NULL,
    available_to_lend   DECIMAL(5,4)  NOT NULL DEFAULT 1.0000,  -- 0 to 1
    CONSTRAINT chk_atl CHECK (available_to_lend BETWEEN 0 AND 1)
);

CREATE TABLE sbl_transactions (
    id                  SERIAL PRIMARY KEY,
    transaction_ref     VARCHAR(30)   NOT NULL UNIQUE,  -- e.g. 'SBL-20260001'
    direction           VARCHAR(10)   NOT NULL,         -- 'LEND' or 'BORROW'
    counterparty_id     INT           NOT NULL REFERENCES counterparties(id),
    security_id         INT           NOT NULL REFERENCES securities(id),
    quantity            INT           NOT NULL,
    price_at_trade      DECIMAL(14,4) NOT NULL,
    notional_value      DECIMAL(18,2) GENERATED ALWAYS AS (quantity * price_at_trade) STORED,
    required_collateral DECIMAL(18,2) GENERATED ALWAYS AS (quantity * price_at_trade * 1.02) STORED,
    lending_rate        DECIMAL(8,6)  NOT NULL,         -- Annual fee e.g. 0.025000
    collateral_type_id  INT           NOT NULL REFERENCES collateral_types(id),
    trade_date          DATE          NOT NULL,
    settlement_date     DATE          NOT NULL,
    term_days           INT           NOT NULL DEFAULT 1,
    status              VARCHAR(20)   NOT NULL DEFAULT 'PENDING',
    fail_reason         TEXT,
    CONSTRAINT chk_sbl_direction CHECK (direction IN ('LEND', 'BORROW')),
    CONSTRAINT chk_sbl_status    CHECK (status IN ('PENDING','SETTLED','FAILED','PARTIAL')),
    created_at          TIMESTAMP     DEFAULT NOW()
);

CREATE TABLE collateral_exposure_snapshots (
    id                          SERIAL PRIMARY KEY,
    snapshot_date               DATE          NOT NULL,
    counterparty_id             INT           NOT NULL REFERENCES counterparties(id),
    total_lent_value            DECIMAL(18,2) NOT NULL,
    total_collateral_received   DECIMAL(18,2) NOT NULL,
    coverage_ratio              DECIMAL(8,6)  NOT NULL,
    open_transactions           INT           NOT NULL,
    failed_settlements          INT           NOT NULL DEFAULT 0,
    created_at                  TIMESTAMP     DEFAULT NOW()
);


-- ── Indexes ───────────────────────────────────────────────────────────────────

CREATE INDEX idx_repo_trades_status       ON repo_trades(status);
CREATE INDEX idx_repo_trades_maturity     ON repo_trades(maturity_date);
CREATE INDEX idx_lifecycle_trade_id       ON lifecycle_events(trade_id);
CREATE INDEX idx_sbl_status              ON sbl_transactions(status);
CREATE INDEX idx_sbl_settlement_date     ON sbl_transactions(settlement_date);
CREATE INDEX idx_sbl_counterparty        ON sbl_transactions(counterparty_id);
CREATE INDEX idx_exposure_date           ON collateral_exposure_snapshots(snapshot_date);


-- ============================================================
-- ANALYTICAL QUERIES
-- ============================================================


-- 1. All open repo trades with current coverage status
--    → Used by traders to monitor desk exposure at a glance
SELECT
    t.trade_ref,
    cp.name                                     AS counterparty,
    ct.description                              AS collateral_type,
    t.cash_lent,
    t.collateral_mv,
    t.eligible_value,
    ROUND(t.eligible_value / t.cash_lent, 4)    AS coverage_ratio,
    t.repo_rate * 100                           AS rate_pct,
    t.maturity_date,
    (t.maturity_date - CURRENT_DATE)            AS days_to_maturity,
    t.status
FROM repo_trades t
JOIN counterparties  cp ON cp.id = t.counterparty_id
JOIN collateral_types ct ON ct.id = t.collateral_type_id
WHERE t.status IN ('OPEN', 'MARGIN_CALL_PENDING')
ORDER BY days_to_maturity ASC;


-- 2. Trades maturing today or tomorrow — must be actioned (roll or close)
--    → Morning checklist for repo traders
SELECT
    t.trade_ref,
    cp.name         AS counterparty,
    t.cash_lent,
    t.repo_rate * 100 AS rate_pct,
    t.maturity_date,
    t.status
FROM repo_trades t
JOIN counterparties cp ON cp.id = t.counterparty_id
WHERE t.maturity_date BETWEEN CURRENT_DATE AND CURRENT_DATE + INTERVAL '1 day'
  AND t.status NOT IN ('CLOSED', 'DEFAULTED', 'ROLLED')
ORDER BY t.maturity_date, t.cash_lent DESC;


-- 3. Active margin calls — trades where coverage has dropped below threshold
--    → Triggered when collateral prices move; requires immediate action
SELECT
    t.trade_ref,
    cp.name                                         AS counterparty,
    t.cash_lent,
    t.collateral_mv,
    t.eligible_value,
    ROUND(t.eligible_value / t.cash_lent, 4)        AS coverage_ratio,
    ROUND(t.cash_lent - t.eligible_value, 2)        AS shortfall,
    ct.description                                  AS collateral_type
FROM repo_trades t
JOIN counterparties   cp ON cp.id = t.counterparty_id
JOIN collateral_types ct ON ct.id = t.collateral_type_id
WHERE t.status = 'MARGIN_CALL_PENDING'
ORDER BY shortfall DESC;


-- 4. Today's SBL settlement fails — requires follow-up with counterparty/DTCC
--    → Core morning task for collateral management operations
SELECT
    s.transaction_ref,
    cp.name             AS counterparty,
    sec.ticker,
    sec.name            AS security_name,
    ac.description      AS asset_class,
    s.quantity,
    s.notional_value,
    s.settlement_date,
    s.status,
    s.fail_reason
FROM sbl_transactions s
JOIN counterparties   cp  ON cp.id  = s.counterparty_id
JOIN securities       sec ON sec.id = s.security_id
JOIN asset_classes    ac  ON ac.id  = sec.asset_class_id
WHERE s.status IN ('FAILED', 'PARTIAL')
  AND s.settlement_date <= CURRENT_DATE
ORDER BY s.notional_value DESC;


-- 5. Counterparty collateral coverage — undercollateralized positions
--    → Daily risk report: who needs to post more collateral
SELECT
    cp.name                                             AS counterparty,
    SUM(s.notional_value)                               AS total_lent,
    SUM(s.required_collateral)                          AS required_collateral,
    ROUND(SUM(s.required_collateral) /
          NULLIF(SUM(s.notional_value), 0), 4)          AS coverage_ratio,
    COUNT(*)                                            AS open_trades,
    CASE
        WHEN SUM(s.required_collateral) /
             NULLIF(SUM(s.notional_value), 0) < 1.02
        THEN 'UNDERCOLLATERALIZED'
        ELSE 'OK'
    END                                                 AS collateral_status
FROM sbl_transactions s
JOIN counterparties cp ON cp.id = s.counterparty_id
WHERE s.direction = 'LEND'
  AND s.status NOT IN ('FAILED', 'SETTLED')
GROUP BY cp.name
ORDER BY coverage_ratio ASC;


-- 6. Daily fee income from active lending — P&L tracking
--    → Revenue attribution by counterparty and asset class
SELECT
    cp.name                                             AS counterparty,
    ac.description                                      AS asset_class,
    COUNT(*)                                            AS transactions,
    SUM(s.notional_value)                               AS total_notional,
    ROUND(AVG(s.lending_rate) * 100, 4)                 AS avg_rate_pct,
    ROUND(SUM(s.notional_value * s.lending_rate / 360), 2) AS daily_fee_income
FROM sbl_transactions s
JOIN counterparties cp  ON cp.id  = s.counterparty_id
JOIN securities     sec ON sec.id = s.security_id
JOIN asset_classes  ac  ON ac.id  = sec.asset_class_id
WHERE s.direction = 'LEND'
  AND s.status = 'SETTLED'
GROUP BY cp.name, ac.description
ORDER BY daily_fee_income DESC;


-- 7. Portfolio availability — how much of each position is free to lend
--    → Used by lending desk when a new borrow request comes in
SELECT
    sec.ticker,
    sec.name,
    ac.description                                      AS asset_class,
    pp.quantity                                         AS total_qty,
    pp.market_price,
    ROUND(pp.quantity * pp.market_price, 2)             AS market_value,
    ROUND(pp.available_to_lend * 100, 1)               AS available_pct,
    ROUND(pp.quantity * pp.available_to_lend)           AS lendable_qty,
    ROUND(pp.quantity * pp.market_price
          * pp.available_to_lend, 2)                    AS lendable_value
FROM portfolio_positions pp
JOIN securities    sec ON sec.id = pp.security_id
JOIN asset_classes ac  ON ac.id  = sec.asset_class_id
WHERE pp.price_date = CURRENT_DATE
ORDER BY lendable_value DESC;


-- 8. Settlement rate by asset class over the last 30 days
--    → Operational KPI: where are fails concentrated?
SELECT
    ac.description                                      AS asset_class,
    COUNT(*)                                            AS total_transactions,
    SUM(CASE WHEN s.status = 'SETTLED' THEN 1 ELSE 0 END) AS settled,
    SUM(CASE WHEN s.status = 'FAILED'  THEN 1 ELSE 0 END) AS failed,
    ROUND(
        100.0 * SUM(CASE WHEN s.status = 'SETTLED' THEN 1 ELSE 0 END)
        / COUNT(*), 2
    )                                                   AS settlement_rate_pct
FROM sbl_transactions s
JOIN securities    sec ON sec.id = s.security_id
JOIN asset_classes ac  ON ac.id  = sec.asset_class_id
WHERE s.trade_date >= CURRENT_DATE - INTERVAL '30 days'
GROUP BY ac.description
ORDER BY settlement_rate_pct ASC;
