# ERD — Phone Shop (P1, Task 3)

```mermaid
erDiagram
    users ||--o{ users : "updated_by"
    users ||--o{ products : "updated_by"
    users ||--o{ import_receipts : "created_by"
    users ||--o{ orders : "customer_id"
    users ||--o{ orders : "cancelled_by"
    users ||--o{ stock_movements : "created_by"
    brands ||--o{ products : "brand_id"
    suppliers ||--o{ import_receipts : "supplier_id"
    products ||--o{ import_items : "product_id"
    products ||--o{ order_items : "product_id"
    products ||--o{ stock_movements : "product_id"
    import_receipts ||--|{ import_items : "receipt_id"
    orders ||--|{ order_items : "order_id"
    orders ||--o| invoices : "order_id UNIQUE"

    users {
        BIGINT id PK
        VARCHAR email UK
        VARCHAR password_hash
        ENUM role
        ENUM status
        DATETIME created_at
        BIGINT updated_by FK
    }
    brands {
        BIGINT id PK
        VARCHAR name UK
    }
    suppliers {
        BIGINT id PK
        VARCHAR name
        BOOLEAN is_active
    }
    products {
        BIGINT id PK
        VARCHAR sku UK
        BIGINT brand_id FK
        DECIMAL sell_price
        DECIMAL cost_price
        INT stock
    }
    import_receipts {
        BIGINT id PK
        VARCHAR code UK
        BIGINT supplier_id FK
        BIGINT created_by FK
    }
    import_items {
        BIGINT id PK
        BIGINT receipt_id FK
        BIGINT product_id FK
        INT quantity
    }
    orders {
        BIGINT id PK
        VARCHAR code UK
        BIGINT customer_id FK
        VARCHAR idempotency_key
        CHAR request_hash
        ENUM status
    }
    order_items {
        BIGINT id PK
        BIGINT order_id FK
        BIGINT product_id FK
        DECIMAL unit_price
        DECIMAL unit_cost
    }
    invoices {
        BIGINT id PK
        VARCHAR invoice_no UK
        BIGINT order_id FK,UK
    }
    stock_movements {
        BIGINT id PK
        BIGINT product_id FK
        ENUM type
        INT quantity_change
        INT stock_after
        VARCHAR operation_key UK
    }
    settings {
        VARCHAR setting_key PK
        VARCHAR setting_value
        DATETIME updated_at
    }
```

**Ghi chú:** `stock_movements.ref_type` / `ref_id` tham chiếu logic tới nhiều loại chứng từ, nên không tạo một khóa ngoại trực tiếp cho cặp này. Service phải kiểm tra `ref_type` và lưu `operation_key` duy nhất. `invoices.order_id` là UNIQUE để mỗi đơn có tối đa một hóa đơn. Ràng buộc COMPLETED phải có hóa đơn sẽ được thực thi trong cùng transaction ở Service của Task US10/US11.

Chỉ gồm 11 bảng P1. Các bảng `auth_sessions`, `password_reset_tokens`, `stock_adjustments`, `stock_adjustment_items` (P2) và `audit_logs` (P3) được bổ sung về sau.
