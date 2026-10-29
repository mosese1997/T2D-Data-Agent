-- t2d 业务仓库 schema（演示模式：本地 Postgres 模拟 DWS/GaussDB）。
-- 列定义与 config/semantics/datasets.yaml 一致；导入脚本负责灌数据。
-- 只读约束三层：查询网关 validator → 连接级 default_transaction_read_only → DB 授权。

CREATE TABLE IF NOT EXISTS dim_country (
    country_code      VARCHAR(8)  PRIMARY KEY,
    country_name      VARCHAR(64) NOT NULL,
    currency          VARCHAR(8)  NOT NULL,
    business_timezone VARCHAR(64) NOT NULL
);

CREATE TABLE IF NOT EXISTS dim_city (
    city_id      INTEGER PRIMARY KEY,
    city_name    VARCHAR(64) NOT NULL,
    country_code VARCHAR(8)  NOT NULL REFERENCES dim_country(country_code)
);

CREATE TABLE IF NOT EXISTS dim_category (
    category_id     VARCHAR(32) PRIMARY KEY,
    category_name   VARCHAR(64) NOT NULL,
    parent_category VARCHAR(32)
);

CREATE TABLE IF NOT EXISTS dim_channel (
    channel_id   INTEGER PRIMARY KEY,
    channel_name VARCHAR(32) NOT NULL
);

CREATE TABLE IF NOT EXISTS dim_product (
    product_id  INTEGER PRIMARY KEY,
    product_name VARCHAR(128) NOT NULL,
    category_id VARCHAR(32) NOT NULL REFERENCES dim_category(category_id),
    price       NUMERIC(12,2) NOT NULL
);

CREATE TABLE IF NOT EXISTS fx_rates (
    currency    VARCHAR(8) NOT NULL,
    rate_date   DATE NOT NULL,
    rate_to_usd NUMERIC(14,8) NOT NULL,
    PRIMARY KEY (currency, rate_date)
);

CREATE TABLE IF NOT EXISTS orders (
    order_id     BIGINT PRIMARY KEY,
    user_id      BIGINT NOT NULL,
    country_code VARCHAR(8) NOT NULL REFERENCES dim_country(country_code),
    city_id      INTEGER NOT NULL REFERENCES dim_city(city_id),
    channel_id   INTEGER NOT NULL REFERENCES dim_channel(channel_id),
    created_at   TIMESTAMP NOT NULL,
    status       VARCHAR(16) NOT NULL,  -- completed | cancelled
    currency     VARCHAR(8) NOT NULL,
    fx_date      DATE NOT NULL
);

CREATE TABLE IF NOT EXISTS order_items (
    item_id     BIGINT PRIMARY KEY,
    order_id    BIGINT NOT NULL REFERENCES orders(order_id),
    product_id  INTEGER NOT NULL REFERENCES dim_product(product_id),
    quantity    INTEGER NOT NULL,
    unit_price  NUMERIC(12,2) NOT NULL,
    line_amount NUMERIC(14,2) NOT NULL
);

CREATE TABLE IF NOT EXISTS refunds (
    refund_id     BIGINT PRIMARY KEY,
    order_id      BIGINT NOT NULL REFERENCES orders(order_id),
    refunded_at   TIMESTAMP NOT NULL,
    refund_amount NUMERIC(14,2) NOT NULL,
    reason        VARCHAR(64) NOT NULL
);

CREATE TABLE IF NOT EXISTS fulfillment_events (
    event_id    BIGINT PRIMARY KEY,
    order_id    BIGINT NOT NULL REFERENCES orders(order_id),
    event_type  VARCHAR(16) NOT NULL,  -- created | packed | shipped | delivered | exception
    occurred_at TIMESTAMP NOT NULL,
    distance_km NUMERIC(8,2)
);

-- 分析常用索引
CREATE INDEX IF NOT EXISTS ix_orders_created  ON orders (created_at);
CREATE INDEX IF NOT EXISTS ix_orders_country  ON orders (country_code);
CREATE INDEX IF NOT EXISTS ix_items_order     ON order_items (order_id);
CREATE INDEX IF NOT EXISTS ix_items_product   ON order_items (product_id);
CREATE INDEX IF NOT EXISTS ix_refunds_order   ON refunds (order_id);
CREATE INDEX IF NOT EXISTS ix_refunds_time    ON refunds (refunded_at);
CREATE INDEX IF NOT EXISTS ix_fe_order_type   ON fulfillment_events (order_id, event_type);
CREATE INDEX IF NOT EXISTS ix_fe_time         ON fulfillment_events (occurred_at);
CREATE INDEX IF NOT EXISTS ix_fx_lookup       ON fx_rates (currency, rate_date);

-- 汇率回退视图：缺失汇率日自动取就近前一有效日（口径规则结构化——
-- Agent 直接 JOIN 本视图，不需要在 SQL 里手写 LATERAL 回退）。
CREATE OR REPLACE VIEW v_orders_fx AS
SELECT o.order_id, o.user_id, o.country_code, o.city_id, o.channel_id,
       o.created_at, o.status, o.currency, o.fx_date,
       fx.rate_to_usd
FROM orders o
LEFT JOIN LATERAL (
    SELECT rate_to_usd FROM fx_rates
    WHERE fx_rates.currency = o.currency AND fx_rates.rate_date <= o.fx_date
    ORDER BY fx_rates.rate_date DESC LIMIT 1
) fx ON true;

ANALYZE;
