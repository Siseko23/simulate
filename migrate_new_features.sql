-- FreightFlow Nexus — New Feature Migration
-- Run this ONCE on your Render PostgreSQL instance before deploying

-- 1. Booking: fragile flag (may already exist from previous session)
ALTER TABLE bookings ADD COLUMN IF NOT EXISTS is_fragile BOOLEAN DEFAULT FALSE;

-- 2. Booking: POD signed timestamps (may already exist)
ALTER TABLE bookings ADD COLUMN IF NOT EXISTS pod_signed BOOLEAN DEFAULT FALSE;
ALTER TABLE bookings ADD COLUMN IF NOT EXISTS pod_signed_at TIMESTAMP;
ALTER TABLE bookings ADD COLUMN IF NOT EXISTS delivered_at TIMESTAMP;

-- 3. ShipperProfile: finance contact for POD invoice notifications
ALTER TABLE shipper_profiles ADD COLUMN IF NOT EXISTS finance_contact_name VARCHAR(80);
ALTER TABLE shipper_profiles ADD COLUMN IF NOT EXISTS finance_contact_email VARCHAR(120);

-- 4. Driver: vetting & compliance fields
ALTER TABLE drivers ADD COLUMN IF NOT EXISTS criminal_clearance_date DATE;
ALTER TABLE drivers ADD COLUMN IF NOT EXISTS criminal_clearance_status VARCHAR(20) DEFAULT 'Pending';
ALTER TABLE drivers ADD COLUMN IF NOT EXISTS pdp_expiry DATE;
ALTER TABLE drivers ADD COLUMN IF NOT EXISTS vetting_status VARCHAR(20) DEFAULT 'Pending';

-- 5. GIT Insurance table (new)
CREATE TABLE IF NOT EXISTS git_insurance (
    id              SERIAL PRIMARY KEY,
    booking_id      INTEGER NOT NULL UNIQUE REFERENCES bookings(id) ON DELETE CASCADE,
    cargo_value     FLOAT NOT NULL,
    premium_rate    FLOAT DEFAULT 0.8,
    premium_amount  FLOAT,
    cover_amount    FLOAT,
    policy_ref      VARCHAR(40),
    provider        VARCHAR(80) DEFAULT 'FFN Insurance Partner',
    status          VARCHAR(20) DEFAULT 'Active',
    issued_at       TIMESTAMP DEFAULT NOW(),
    expires_at      TIMESTAMP
);

-- 6. POD Tokens table (new)
CREATE TABLE IF NOT EXISTS pod_tokens (
    id          SERIAL PRIMARY KEY,
    booking_id  INTEGER NOT NULL UNIQUE REFERENCES bookings(id) ON DELETE CASCADE,
    token       VARCHAR(64) NOT NULL UNIQUE,
    scanned     BOOLEAN DEFAULT FALSE,
    scanned_at  TIMESTAMP,
    scanned_by  VARCHAR(80),
    created_at  TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_pod_tokens_token ON pod_tokens(token);

-- Supplier 12-hour acceptance + driver assignment SLA
ALTER TABLE bookings ADD COLUMN supplier_response_deadline DATETIME;
ALTER TABLE bookings ADD COLUMN supplier_accepted_at DATETIME;
ALTER TABLE bookings ADD COLUMN driver_assigned_at DATETIME;
ALTER TABLE bookings ADD COLUMN supplier_sla_status VARCHAR(30) DEFAULT 'Not Started';
