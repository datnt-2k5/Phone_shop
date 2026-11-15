
-- Task 55 / US09-T18: persistent Customer cart.
-- Execute separately in phone_shop and phone_shop_test.
-- One row per Customer. Only IDs and quantities are stored.

CREATE TABLE IF NOT EXISTS customer_carts (
    customer_id BIGINT NOT NULL,
    items_json LONGTEXT NOT NULL,
    revision BIGINT NOT NULL DEFAULT 0,
    updated_at DATETIME(6) NOT NULL
        DEFAULT CURRENT_TIMESTAMP(6),

    PRIMARY KEY (customer_id),

    CONSTRAINT chk_customer_carts_json
        CHECK (JSON_VALID(items_json)),

    CONSTRAINT chk_customer_carts_revision
        CHECK (revision >= 0)
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4;
