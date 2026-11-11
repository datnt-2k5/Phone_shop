-- Task 42 / US07 P2
-- Tao 2 bang phieu kiem ke va chi tiet dieu chinh ton.
-- KHONG co DROP, TRUNCATE, DELETE hay UPDATE du lieu cu.
-- Chon dung database trong phpMyAdmin truoc khi thuc thi.

CREATE TABLE IF NOT EXISTS stock_adjustments (
    id BIGINT NOT NULL AUTO_INCREMENT,
    code VARCHAR(50) NOT NULL,
    reason VARCHAR(255) NOT NULL,
    created_by BIGINT NOT NULL,
    created_at DATETIME NOT NULL,

    PRIMARY KEY (id),
    CONSTRAINT uq_stock_adjustments_code UNIQUE (code),

    KEY idx_stock_adjustments_created_at (created_at),

    CONSTRAINT fk_stock_adjustments_created_by
        FOREIGN KEY (created_by)
        REFERENCES users(id),

    CONSTRAINT chk_stock_adjustments_reason
        CHECK (CHAR_LENGTH(TRIM(reason)) > 0)
)
ENGINE = InnoDB
DEFAULT CHARACTER SET utf8mb4
COLLATE utf8mb4_unicode_ci;


CREATE TABLE IF NOT EXISTS stock_adjustment_items (
    id BIGINT NOT NULL AUTO_INCREMENT,
    adjustment_id BIGINT NOT NULL,
    product_id BIGINT NOT NULL,
    old_quantity INT NOT NULL,
    actual_quantity INT NOT NULL,
    quantity_change INT NOT NULL,
    stock_after INT NOT NULL,

    PRIMARY KEY (id),

    CONSTRAINT uq_stock_adjustment_items_product
        UNIQUE (adjustment_id, product_id),

    KEY idx_stock_adjustment_items_product (product_id),

    CONSTRAINT fk_stock_adjustment_items_header
        FOREIGN KEY (adjustment_id)
        REFERENCES stock_adjustments(id),

    CONSTRAINT fk_stock_adjustment_items_product
        FOREIGN KEY (product_id)
        REFERENCES products(id),

    CONSTRAINT chk_adjustment_old_qty
        CHECK (old_quantity >= 0),

    CONSTRAINT chk_adjustment_actual_qty
        CHECK (actual_quantity >= 0),

    CONSTRAINT chk_adjustment_change_nonzero
        CHECK (quantity_change <> 0),

    CONSTRAINT chk_adjustment_stock_nonnegative
        CHECK (stock_after >= 0),

    CONSTRAINT chk_adjustment_delta_consistent
        CHECK (
            old_quantity + quantity_change = actual_quantity
        ),

    CONSTRAINT chk_adjustment_stock_consistent
        CHECK (stock_after = actual_quantity)
)
ENGINE = InnoDB
DEFAULT CHARACTER SET utf8mb4
COLLATE utf8mb4_unicode_ci;
