-- Real production schema, extracted directly from Supabase on 2026-08-05.
-- Used by CI to spin up a fresh Postgres test database that matches
-- production exactly, so tests catch Postgres-specific bugs (unlike the
-- old SQLite-based test setup, which missed the strftime() bug tonight).

CREATE TABLE IF NOT EXISTS active_carts (
    customer_phone TEXT PRIMARY KEY,
    customer_name TEXT,
    items_json TEXT,
    updated_at TIMESTAMP DEFAULT NOW(),
    reminder_sent_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS activity_log (
    id SERIAL PRIMARY KEY,
    staff_name TEXT NOT NULL,
    action TEXT NOT NULL,
    details TEXT,
    order_id INTEGER,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS app_events (
    id SERIAL PRIMARY KEY,
    event_type TEXT,
    customer_phone TEXT,
    product_sku TEXT,
    metadata TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS attendance (
    id SERIAL PRIMARY KEY,
    staff_id INTEGER,
    clock_in TIMESTAMP,
    clock_out TIMESTAMP,
    date DATE DEFAULT CURRENT_DATE
);

CREATE TABLE IF NOT EXISTS attendance_log (
    id SERIAL PRIMARY KEY,
    staff_id INTEGER,
    clock_in TIMESTAMP,
    clock_out TIMESTAMP,
    hours_worked NUMERIC,
    date DATE DEFAULT CURRENT_DATE,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS categories (
    id SERIAL PRIMARY KEY,
    name_en VARCHAR,
    name_te VARCHAR,
    name_hi VARCHAR,
    icon VARCHAR
);

CREATE TABLE IF NOT EXISTS customer_loyalty_points (
    id SERIAL PRIMARY KEY,
    phone VARCHAR NOT NULL,
    points INTEGER DEFAULT 0,
    total_earned INTEGER DEFAULT 0,
    total_redeemed INTEGER DEFAULT 0,
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS customer_profiles (
    id SERIAL PRIMARY KEY,
    phone TEXT NOT NULL,
    name TEXT,
    bike_brand TEXT,
    bike_model TEXT,
    bike_sku TEXT,
    total_orders INTEGER DEFAULT 0,
    total_spent REAL DEFAULT 0,
    last_order_date TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    pin TEXT,
    email TEXT,
    address TEXT,
    city TEXT,
    pincode TEXT,
    upi_id TEXT,
    whatsapp TEXT
);

CREATE TABLE IF NOT EXISTS customer_tokens (
    id SERIAL PRIMARY KEY,
    phone VARCHAR NOT NULL,
    token TEXT NOT NULL,
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS customers (
    id SERIAL PRIMARY KEY,
    name VARCHAR,
    phone VARCHAR,
    language VARCHAR DEFAULT 'te',
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS inventory_logs (
    id SERIAL PRIMARY KEY,
    product_id INTEGER,
    sku TEXT,
    old_qty INTEGER,
    new_qty INTEGER,
    change_reason TEXT,
    changed_by TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS mechanic_profiles (
    id SERIAL PRIMARY KEY,
    name VARCHAR NOT NULL,
    phone VARCHAR NOT NULL,
    shop_name VARCHAR,
    area VARCHAR,
    status VARCHAR DEFAULT 'pending',
    approved_by INTEGER,
    approved_at TIMESTAMP,
    notes TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS offers (
    id SERIAL PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT,
    discount_percent INTEGER DEFAULT 0,
    emoji TEXT DEFAULT '🎉',
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS products (
    id SERIAL PRIMARY KEY,
    sku VARCHAR NOT NULL,
    name_en VARCHAR,
    name_te VARCHAR,
    name_hi VARCHAR,
    category_id INTEGER,
    brand VARCHAR,
    price NUMERIC,
    mrp NUMERIC,
    selling_price NUMERIC,
    stock_qty INTEGER DEFAULT 0,
    min_stock_alert INTEGER DEFAULT 5,
    price_updated_by INTEGER,
    price_updated_at TIMESTAMP,
    image_url TEXT,
    is_oem BOOLEAN DEFAULT false,
    barcode TEXT
);

CREATE TABLE IF NOT EXISTS orders (
    id SERIAL PRIMARY KEY,
    customer_id INTEGER,
    status VARCHAR DEFAULT 'new',
    pickup_time VARCHAR,
    total_amount NUMERIC,
    payment_type VARCHAR,
    payment_time TIMESTAMP,
    collected_by INTEGER,
    created_at TIMESTAMP DEFAULT NOW(),
    custom_id VARCHAR,
    customer_name VARCHAR,
    customer_phone VARCHAR,
    packed_by VARCHAR
);

CREATE TABLE IF NOT EXISTS order_items (
    id SERIAL PRIMARY KEY,
    order_id INTEGER,
    product_id INTEGER,
    qty INTEGER,
    price NUMERIC
);

CREATE TABLE IF NOT EXISTS push_tokens (
    id SERIAL PRIMARY KEY,
    staff_id INTEGER,
    token TEXT NOT NULL,
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS rewards (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    points_required INTEGER DEFAULT 100,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS service_reminders_sent (
    id SERIAL PRIMARY KEY,
    customer_phone TEXT,
    sent_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS staff_profiles (
    id SERIAL PRIMARY KEY,
    name VARCHAR,
    phone VARCHAR,
    role VARCHAR,
    is_active BOOLEAN DEFAULT true,
    photo_url TEXT,
    is_clocked_in BOOLEAN DEFAULT false,
    clock_in_time TIMESTAMP,
    clock_out_time TIMESTAMP,
    total_hours_today NUMERIC DEFAULT 0,
    pin VARCHAR
);

CREATE TABLE IF NOT EXISTS staff_push_tokens (
    id SERIAL PRIMARY KEY,
    staff_id INTEGER,
    push_token TEXT UNIQUE,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS warranty_claims (
    id SERIAL PRIMARY KEY,
    order_id INTEGER,
    product_name TEXT,
    customer_name TEXT,
    customer_phone TEXT,
    issue_description TEXT,
    status TEXT DEFAULT 'pending',
    resolution_type TEXT,
    resolution_notes TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    resolved_at TIMESTAMP,
    resolved_by TEXT
);
