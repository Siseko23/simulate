"""
FreightFlow Nexus - Database Models
All entities: User, ShipperProfile, SupplierProfile, Driver, Vehicle,
Booking, Quote, Invoice, PurchaseOrder, Notification, AuditLog,
SupplierScoreHistory, BookingStatusEvent, AddressBook, AvailabilitySlot
"""
from datetime import datetime, timezone, timedelta
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
import bcrypt

db = SQLAlchemy()

def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)

# ─────────────────────────────────────────────────────────────────────────────
# USER & AUTH
# ─────────────────────────────────────────────────────────────────────────────

class User(UserMixin, db.Model):
    __tablename__ = "users"

    id            = db.Column(db.Integer, primary_key=True)
    email         = db.Column(db.String(180), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    role          = db.Column(db.String(20), nullable=False)   # shipper|supplier|driver|admin
    first_name    = db.Column(db.String(80))
    last_name     = db.Column(db.String(80))
    phone         = db.Column(db.String(30))
    is_active     = db.Column(db.Boolean, default=True)
    is_verified   = db.Column(db.Boolean, default=False)
    created_at    = db.Column(db.DateTime, default=utcnow)
    last_login    = db.Column(db.DateTime)

    # relationships
    shipper_profile  = db.relationship("ShipperProfile",  back_populates="user", uselist=False, cascade="all, delete")
    supplier_profile = db.relationship("SupplierProfile", back_populates="user", uselist=False, cascade="all, delete")
    driver_profile   = db.relationship("Driver",          back_populates="user", uselist=False, cascade="all, delete")
    admin_profile    = db.relationship("AdminProfile",    back_populates="user", uselist=False, cascade="all, delete")
    notifications    = db.relationship("Notification", back_populates="user", lazy="dynamic", cascade="all, delete")
    audit_logs       = db.relationship("AuditLog", back_populates="user", lazy="dynamic")

    def set_password(self, password: str):
        self.password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

    def check_password(self, password: str) -> bool:
        return bcrypt.checkpw(password.encode(), self.password_hash.encode())

    @property
    def full_name(self):
        return f"{self.first_name or ''} {self.last_name or ''}".strip() or self.email

    def __repr__(self):
        return f"<User {self.email} [{self.role}]>"


class ShipperProfile(db.Model):
    __tablename__ = "shipper_profiles"

    id              = db.Column(db.Integer, primary_key=True)
    user_id         = db.Column(db.Integer, db.ForeignKey("users.id"), unique=True, nullable=False)
    account_type    = db.Column(db.String(20), default="Business")  # Business|Individual
    company_name    = db.Column(db.String(120))
    vat_number      = db.Column(db.String(30))
    industry        = db.Column(db.String(80))
    address         = db.Column(db.String(200))
    city            = db.Column(db.String(60))
    province        = db.Column(db.String(60))
    credit_limit    = db.Column(db.Float, default=0)
    credit_used     = db.Column(db.Float, default=0)
    total_spend     = db.Column(db.Float, default=0)
    health_score    = db.Column(db.Float, default=75.0)
    risk_flag       = db.Column(db.String(200))       # admin risk note
    admin_notes     = db.Column(db.Text)              # internal admin notes
    finance_contact_name  = db.Column(db.String(80))  # Who gets POD/invoice notifications
    finance_contact_email = db.Column(db.String(120))
    created_at      = db.Column(db.DateTime, default=utcnow)

    user            = db.relationship("User", back_populates="shipper_profile")
    bookings        = db.relationship("Booking", back_populates="shipper", lazy="dynamic")
    address_book    = db.relationship("AddressBook", back_populates="shipper", lazy="dynamic", cascade="all, delete")


class SupplierProfile(db.Model):
    __tablename__ = "supplier_profiles"

    id              = db.Column(db.Integer, primary_key=True)
    user_id         = db.Column(db.Integer, db.ForeignKey("users.id"), unique=True, nullable=False)
    company_name    = db.Column(db.String(120), nullable=False)
    reg_number      = db.Column(db.String(40))
    vat_number      = db.Column(db.String(30))
    base_city       = db.Column(db.String(60))
    operating_region= db.Column(db.String(120))
    insurance_ref   = db.Column(db.String(80))
    bank_name       = db.Column(db.String(60))
    bank_account    = db.Column(db.String(30))
    bank_branch     = db.Column(db.String(20))
    account_holder  = db.Column(db.String(80))
    account_type    = db.Column(db.String(40), default="Current / Cheque")
    status          = db.Column(db.String(20), default="Under Review")  # Active|Suspended|Under Review
    score           = db.Column(db.Float, default=4.0)
    total_jobs      = db.Column(db.Integer, default=0)
    on_time_jobs    = db.Column(db.Integer, default=0)
    cancelled_jobs  = db.Column(db.Integer, default=0)
    acceptance_rate = db.Column(db.Float, default=95.0)
    created_at      = db.Column(db.DateTime, default=utcnow)
    approved_at     = db.Column(db.DateTime)

    user            = db.relationship("User", back_populates="supplier_profile")
    drivers         = db.relationship("Driver", back_populates="supplier", lazy="dynamic", cascade="all, delete")
    vehicles        = db.relationship("Vehicle", back_populates="supplier", lazy="dynamic", cascade="all, delete")
    quotes          = db.relationship("Quote", back_populates="supplier", lazy="dynamic")
    bookings        = db.relationship("Booking", back_populates="supplier", lazy="dynamic")
    score_history   = db.relationship("SupplierScoreHistory", back_populates="supplier", lazy="dynamic", cascade="all, delete")
    availability    = db.relationship("AvailabilitySlot", back_populates="supplier", lazy="dynamic", cascade="all, delete")

    @property
    def on_time_rate(self):
        if self.total_jobs == 0:
            return 100.0
        return round((self.on_time_jobs / self.total_jobs) * 100, 1)

    @property
    def cancellation_rate(self):
        if self.total_jobs == 0:
            return 0.0
        return round((self.cancelled_jobs / self.total_jobs) * 100, 1)


class AdminProfile(db.Model):
    __tablename__ = "admin_profiles"

    id          = db.Column(db.Integer, primary_key=True)
    user_id     = db.Column(db.Integer, db.ForeignKey("users.id"), unique=True, nullable=False)
    department  = db.Column(db.String(40), default="Operations")  # Operations|Finance|Compliance|Tech|Management
    access_level= db.Column(db.String(20), default="Standard")    # Standard|Senior|Super

    user        = db.relationship("User", back_populates="admin_profile")


# ─────────────────────────────────────────────────────────────────────────────
# FLEET & DRIVERS
# ─────────────────────────────────────────────────────────────────────────────

class Driver(db.Model):
    __tablename__ = "drivers"

    id              = db.Column(db.Integer, primary_key=True)
    user_id         = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)  # optional portal access
    supplier_id     = db.Column(db.Integer, db.ForeignKey("supplier_profiles.id"), nullable=False)
    name            = db.Column(db.String(80), nullable=False)
    id_number       = db.Column(db.String(20), unique=True)
    license_code    = db.Column(db.String(10), default="EC")
    license_expiry  = db.Column(db.Date)
    phone           = db.Column(db.String(20))
    pin             = db.Column(db.String(6), default="0000")  # driver portal login PIN
    status          = db.Column(db.String(20), default="Active")   # Active|Inactive|On Trip
    rating          = db.Column(db.Float, default=4.5)
    total_trips     = db.Column(db.Integer, default=0)
    created_at      = db.Column(db.DateTime, default=utcnow)
    assigned_vehicle_id = db.Column(db.Integer, db.ForeignKey("vehicles.id"), nullable=True)

    # Vetting & compliance
    criminal_clearance_date   = db.Column(db.Date)
    criminal_clearance_status = db.Column(db.String(20), default="Pending")  # Pending|Cleared|Failed
    pdp_expiry                = db.Column(db.Date)       # Professional Driving Permit
    vetting_status            = db.Column(db.String(20), default="Pending")  # Pending|Vetted|Rejected

    user            = db.relationship("User", back_populates="driver_profile")
    supplier        = db.relationship("SupplierProfile", back_populates="drivers")
    assigned_vehicle = db.relationship("Vehicle", foreign_keys=[assigned_vehicle_id], backref="assigned_drivers")
    bookings        = db.relationship("Booking", back_populates="driver", lazy="dynamic")


class Vehicle(db.Model):
    __tablename__ = "vehicles"

    id              = db.Column(db.Integer, primary_key=True)
    supplier_id     = db.Column(db.Integer, db.ForeignKey("supplier_profiles.id"), nullable=False)
    reg_number      = db.Column(db.String(20), unique=True, nullable=False)
    vehicle_type    = db.Column(db.String(60))   # Superlink|Horse & Trailer|8-Ton Rigid...
    payload_ton     = db.Column(db.Float)
    cbm             = db.Column(db.Float)
    year            = db.Column(db.Integer)
    roadworthy_expiry = db.Column(db.Date)
    availability    = db.Column(db.String(20), default="Available")  # Available|On Trip|Maintenance
    created_at      = db.Column(db.DateTime, default=utcnow)

    supplier        = db.relationship("SupplierProfile", back_populates="vehicles")
    bookings        = db.relationship("Booking", back_populates="vehicle", lazy="dynamic")


# ─────────────────────────────────────────────────────────────────────────────
# BOOKINGS & QUOTES
# ─────────────────────────────────────────────────────────────────────────────

class Booking(db.Model):
    __tablename__ = "bookings"

    id                  = db.Column(db.Integer, primary_key=True)
    ref                 = db.Column(db.String(20), unique=True, nullable=False, index=True)
    shipper_id          = db.Column(db.Integer, db.ForeignKey("shipper_profiles.id"), nullable=False)
    supplier_id         = db.Column(db.Integer, db.ForeignKey("supplier_profiles.id"))
    driver_id           = db.Column(db.Integer, db.ForeignKey("drivers.id"))
    vehicle_id          = db.Column(db.Integer, db.ForeignKey("vehicles.id"))
    accepted_quote_id   = db.Column(db.Integer, db.ForeignKey("quotes.id"))

    # Route
    collection_address  = db.Column(db.String(200))
    collection_city     = db.Column(db.String(60))
    delivery_address    = db.Column(db.String(200))
    delivery_city       = db.Column(db.String(60))
    route               = db.Column(db.String(120))   # "Durban -> Johannesburg"
    distance_km         = db.Column(db.Float)
    collection_lat      = db.Column(db.Float)
    collection_lng      = db.Column(db.Float)
    delivery_lat        = db.Column(db.Float)
    delivery_lng        = db.Column(db.Float)

    # Cargo
    commodity           = db.Column(db.String(80))
    pieces              = db.Column(db.Integer)
    weight_per_item_kg  = db.Column(db.Float)
    total_weight_kg     = db.Column(db.Float)
    vehicle_type_req    = db.Column(db.String(60))
    destination_type    = db.Column(db.String(30))   # DC|Direct|Port

    # Contacts
    collection_contact  = db.Column(db.String(80))
    collection_phone    = db.Column(db.String(20))
    delivery_contact    = db.Column(db.String(80))
    delivery_phone      = db.Column(db.String(20))

    # Financials
    quoted_value        = db.Column(db.Float, default=0)
    platform_fee        = db.Column(db.Float, default=0)
    supplier_payout     = db.Column(db.Float, default=0)

    # Dates
    collection_date     = db.Column(db.Date)
    delivery_date       = db.Column(db.Date)
    created_at          = db.Column(db.DateTime, default=utcnow)
    confirmed_at        = db.Column(db.DateTime)
    collected_at        = db.Column(db.DateTime)
    delivered_at        = db.Column(db.DateTime)

    # Supplier response SLA: once shipper pays the platform, the selected supplier
    # has 12 hours to accept the booking AND assign a driver/vehicle.
    supplier_response_deadline = db.Column(db.DateTime)
    supplier_accepted_at       = db.Column(db.DateTime)
    driver_assigned_at         = db.Column(db.DateTime)
    supplier_sla_status        = db.Column(db.String(30), default="Not Started")  # Not Started|Pending|Accepted|Completed|Expired

    # Status
    status              = db.Column(db.String(30), default="Pending Quotes")
    # Pending Quotes | Quotes Received | Confirmed | Driver Assigned |
    # Collected | In Transit | Approaching Destination | Delivered | Cancelled

    risk_level          = db.Column(db.String(10), default="Low")  # Low|Medium|High
    notes               = db.Column(db.Text)
    is_fragile          = db.Column(db.Boolean, default=False)
    pod_signed          = db.Column(db.Boolean, default=False)
    # Live GPS tracking
    gps_lat             = db.Column(db.Float)
    gps_lng             = db.Column(db.Float)
    gps_updated_at      = db.Column(db.DateTime)
    pod_signed_at       = db.Column(db.DateTime)

    # Shipper-requested live driver location access. This protects suppliers and
    # drivers while allowing live tracking for high-value/sensitive loads.
    location_access_requested = db.Column(db.Boolean, default=False)
    location_access_reason    = db.Column(db.String(200))
    location_access_status    = db.Column(db.String(20), default="Not Requested")  # Not Requested|Pending|Approved|Rejected
    location_access_approved_at = db.Column(db.DateTime)

    # Shipper rating of completed delivery
    rating              = db.Column(db.Integer)        # 1-5 stars
    rating_comment      = db.Column(db.Text)
    rated_at            = db.Column(db.DateTime)

    # Relationships
    shipper     = db.relationship("ShipperProfile", back_populates="bookings")
    supplier    = db.relationship("SupplierProfile", back_populates="bookings")
    driver      = db.relationship("Driver", back_populates="bookings")
    vehicle     = db.relationship("Vehicle", back_populates="bookings")
    quotes      = db.relationship("Quote", back_populates="booking",
                                  primaryjoin="Booking.id == Quote.booking_id",
                                  foreign_keys="Quote.booking_id", lazy="dynamic", cascade="all, delete")
    status_events = db.relationship("BookingStatusEvent", back_populates="booking",
                                    order_by="BookingStatusEvent.created_at", cascade="all, delete")
    invoice     = db.relationship("Invoice", back_populates="booking", uselist=False, cascade="all, delete")
    purchase_order = db.relationship("PurchaseOrder", back_populates="booking", uselist=False, cascade="all, delete")
    delivery_evidence = db.relationship("DeliveryEvidence", back_populates="booking", uselist=False, cascade="all, delete-orphan")

    def generate_ref(self):
        import random, string
        self.ref = "FFN-" + str(datetime.now().year) + "-" + ''.join(random.choices(string.digits, k=4))

    @property
    def total_weight(self):
        if self.pieces and self.weight_per_item_kg:
            return self.pieces * self.weight_per_item_kg
        return self.total_weight_kg or 0

    def calculate_platform_fee(self, pct=26.7):
        self.platform_fee  = round(self.quoted_value * (pct / 100), 2)
        self.supplier_payout = round(self.quoted_value - self.platform_fee, 2)

    def start_supplier_response_sla(self, hours=12):
        self.supplier_response_deadline = utcnow() + timedelta(hours=hours)
        self.supplier_accepted_at = None
        self.driver_assigned_at = None
        self.supplier_sla_status = "Pending"

    @property
    def supplier_response_expired(self):
        return bool(
            self.supplier_response_deadline
            and not self.driver_assigned_at
            and utcnow() > self.supplier_response_deadline
            and self.status in ("Pending Supplier Acceptance", "Pending Dispatch", "Confirmed")
        )

    @property
    def supplier_response_hours_left(self):
        if not self.supplier_response_deadline or self.driver_assigned_at:
            return None
        seconds = (self.supplier_response_deadline - utcnow()).total_seconds()
        return max(0, round(seconds / 3600, 1))


class Quote(db.Model):
    __tablename__ = "quotes"

    id              = db.Column(db.Integer, primary_key=True)
    booking_id      = db.Column(db.Integer, db.ForeignKey("bookings.id"), nullable=False)
    supplier_id     = db.Column(db.Integer, db.ForeignKey("supplier_profiles.id"), nullable=False)
    amount          = db.Column(db.Float, nullable=False)
    transit_days    = db.Column(db.Integer)
    notes           = db.Column(db.Text)
    valid_until     = db.Column(db.DateTime)
    status          = db.Column(db.String(20), default="Pending")  # Pending|Accepted|Rejected|Expired
    ai_score        = db.Column(db.Float)     # composite AI ranking score
    rank            = db.Column(db.Integer)   # 1 = best
    created_at      = db.Column(db.DateTime, default=utcnow)

    booking         = db.relationship("Booking", back_populates="quotes",
                                      foreign_keys=[booking_id])
    supplier        = db.relationship("SupplierProfile", back_populates="quotes")


# ─────────────────────────────────────────────────────────────────────────────
# FINANCIALS
# ─────────────────────────────────────────────────────────────────────────────

class Invoice(db.Model):
    __tablename__ = "invoices"

    id              = db.Column(db.Integer, primary_key=True)
    booking_id      = db.Column(db.Integer, db.ForeignKey("bookings.id"), unique=True, nullable=False)
    invoice_number  = db.Column(db.String(30), unique=True, nullable=False)
    amount          = db.Column(db.Float)
    vat_amount      = db.Column(db.Float)
    total_amount    = db.Column(db.Float)
    status          = db.Column(db.String(20), default="Unpaid")  # Unpaid|Paid|Overdue
    due_date        = db.Column(db.Date)
    paid_at         = db.Column(db.DateTime)
    created_at      = db.Column(db.DateTime, default=utcnow)

    booking         = db.relationship("Booking", back_populates="invoice")

    def generate_number(self):
        self.invoice_number = f"INV-{datetime.now().year}-{self.id:05d}"


class PurchaseOrder(db.Model):
    __tablename__ = "purchase_orders"

    id              = db.Column(db.Integer, primary_key=True)
    booking_id      = db.Column(db.Integer, db.ForeignKey("bookings.id"), unique=True, nullable=False)
    po_number       = db.Column(db.String(30), unique=True, nullable=False)
    gross_amount    = db.Column(db.Float)
    platform_fee    = db.Column(db.Float)
    net_payable     = db.Column(db.Float)
    status          = db.Column(db.String(20), default="Invoice Pending")  # Invoice Pending|Invoice Received|Approved|Paid
    invoice_filename   = db.Column(db.String(200))
    invoice_uploaded_at = db.Column(db.DateTime)
    approved_at     = db.Column(db.DateTime)
    paid_at         = db.Column(db.DateTime)
    created_at      = db.Column(db.DateTime, default=utcnow)

    booking         = db.relationship("Booking", back_populates="purchase_order")

    def generate_number(self):
        self.po_number = f"PO-{datetime.now().year}-{self.id:05d}"


# ─────────────────────────────────────────────────────────────────────────────
# TRACKING & EVENTS
# ─────────────────────────────────────────────────────────────────────────────

class BookingStatusEvent(db.Model):
    __tablename__ = "booking_status_events"

    id          = db.Column(db.Integer, primary_key=True)
    booking_id  = db.Column(db.Integer, db.ForeignKey("bookings.id"), nullable=False)
    status      = db.Column(db.String(40), nullable=False)
    note        = db.Column(db.String(200))
    actor       = db.Column(db.String(80))   # who triggered this change
    lat         = db.Column(db.Float)
    lng         = db.Column(db.Float)
    created_at  = db.Column(db.DateTime, default=utcnow)

    booking     = db.relationship("Booking", back_populates="status_events")


class DeliveryEvidence(db.Model):
    """Structured proof-of-delivery record for one booking."""
    __tablename__ = "delivery_evidence"

    id = db.Column(db.Integer, primary_key=True)
    booking_id = db.Column(db.Integer, db.ForeignKey("bookings.id"), nullable=False, unique=True, index=True)
    receiver_name = db.Column(db.String(150), nullable=False)
    delivery_notes = db.Column(db.Text)
    latitude = db.Column(db.Float, nullable=False)
    longitude = db.Column(db.Float, nullable=False)
    delivered_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    completed_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=utcnow)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)

    booking = db.relationship("Booking", back_populates="delivery_evidence")
    completed_by = db.relationship("User")
    files = db.relationship("DeliveryEvidenceFile", back_populates="evidence", cascade="all, delete-orphan", lazy="selectin")

    def file_of_type(self, file_type):
        return next((item for item in self.files if item.file_type == file_type), None)


class DeliveryEvidenceFile(db.Model):
    """A typed file attached to delivery evidence."""
    __tablename__ = "delivery_evidence_files"

    id = db.Column(db.Integer, primary_key=True)
    evidence_id = db.Column(db.Integer, db.ForeignKey("delivery_evidence.id"), nullable=False, index=True)
    file_type = db.Column(db.String(40), nullable=False)  # pod|delivery_photo|receiver_signature|driver_signature
    file_path = db.Column(db.String(500), nullable=False)
    original_filename = db.Column(db.String(255), nullable=False)
    stored_filename = db.Column(db.String(255), nullable=False, unique=True)
    mime_type = db.Column(db.String(100))
    uploaded_at = db.Column(db.DateTime, default=utcnow)

    evidence = db.relationship("DeliveryEvidence", back_populates="files")


# ─────────────────────────────────────────────────────────────────────────────
# NOTIFICATIONS
# ─────────────────────────────────────────────────────────────────────────────

class Notification(db.Model):
    __tablename__ = "notifications"

    id          = db.Column(db.Integer, primary_key=True)
    user_id     = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    title       = db.Column(db.String(120), nullable=False)
    body        = db.Column(db.String(400))
    type        = db.Column(db.String(30), default="info")  # info|success|warning|error
    ref_type    = db.Column(db.String(20))   # booking|supplier|system
    ref_id      = db.Column(db.String(30))   # e.g. booking ref
    is_read     = db.Column(db.Boolean, default=False)
    created_at  = db.Column(db.DateTime, default=utcnow)

    user        = db.relationship("User", back_populates="notifications")


# ─────────────────────────────────────────────────────────────────────────────
# ANALYTICS & INTELLIGENCE
# ─────────────────────────────────────────────────────────────────────────────

class SupplierScoreHistory(db.Model):
    __tablename__ = "supplier_score_history"

    id          = db.Column(db.Integer, primary_key=True)
    supplier_id = db.Column(db.Integer, db.ForeignKey("supplier_profiles.id"), nullable=False)
    score       = db.Column(db.Float, nullable=False)
    on_time_rate= db.Column(db.Float)
    cancel_rate = db.Column(db.Float)
    recorded_at = db.Column(db.DateTime, default=utcnow)

    supplier    = db.relationship("SupplierProfile", back_populates="score_history")


class AddressBook(db.Model):
    __tablename__ = "address_book"

    id          = db.Column(db.Integer, primary_key=True)
    shipper_id  = db.Column(db.Integer, db.ForeignKey("shipper_profiles.id"), nullable=False)
    label       = db.Column(db.String(80))
    address     = db.Column(db.String(200))
    city        = db.Column(db.String(60))
    contact_name= db.Column(db.String(80))
    contact_phone= db.Column(db.String(20))
    type        = db.Column(db.String(20), default="Delivery")  # Collection|Delivery

    shipper     = db.relationship("ShipperProfile", back_populates="address_book")


class AvailabilitySlot(db.Model):
    __tablename__ = "availability_slots"

    id          = db.Column(db.Integer, primary_key=True)
    supplier_id = db.Column(db.Integer, db.ForeignKey("supplier_profiles.id"), nullable=False)
    date        = db.Column(db.Date, nullable=False)
    vehicle_type= db.Column(db.String(60))
    slots_total = db.Column(db.Integer, default=1)
    slots_used  = db.Column(db.Integer, default=0)
    note        = db.Column(db.String(120))

    # Blocked-date calendar fields (maintenance / holiday / peak blackout)
    is_blocked  = db.Column(db.Boolean, default=False)
    block_type  = db.Column(db.String(20))   # maintenance | holiday | peak
    reason      = db.Column(db.String(200))

    supplier    = db.relationship("SupplierProfile", back_populates="availability")


class AuditLog(db.Model):
    __tablename__ = "audit_logs"

    id          = db.Column(db.Integer, primary_key=True)
    user_id     = db.Column(db.Integer, db.ForeignKey("users.id"))
    action      = db.Column(db.String(80))
    entity_type = db.Column(db.String(40))
    entity_id   = db.Column(db.String(40))
    detail      = db.Column(db.Text)
    ip_address  = db.Column(db.String(45))
    created_at  = db.Column(db.DateTime, default=utcnow)

    user        = db.relationship("User", back_populates="audit_logs")


# ─────────────────────────────────────────────────────────────────────────────
# COMPLAINTS
# ─────────────────────────────────────────────────────────────────────────────

class Complaint(db.Model):
    __tablename__ = "complaints"

    id              = db.Column(db.Integer, primary_key=True)
    ref             = db.Column(db.String(25), unique=True, nullable=False, index=True)

    # Who filed it
    shipper_id      = db.Column(db.Integer, db.ForeignKey("shipper_profiles.id"), nullable=False)
    # Related booking (optional but recommended)
    booking_id      = db.Column(db.Integer, db.ForeignKey("bookings.id"), nullable=True)
    # Supplier the complaint is ultimately about
    supplier_id     = db.Column(db.Integer, db.ForeignKey("supplier_profiles.id"), nullable=True)

    category        = db.Column(db.String(80), nullable=False)
    priority        = db.Column(db.String(20), default="Normal")   # Normal|Urgent|Critical
    description     = db.Column(db.Text, nullable=False)
    evidence_files  = db.Column(db.String(400))   # comma-separated filenames
    dispute_amount  = db.Column(db.Float)         # ZAR amount in dispute, optional

    # Workflow status
    # Submitted -> Under Admin Review -> Forwarded to Supplier -> Supplier Responded -> Resolved | Closed
    status          = db.Column(db.String(40), default="Submitted")
    assigned_agent_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

    # Admin actions
    admin_notes     = db.Column(db.Text)          # internal notes (not visible to supplier)
    forwarded_at    = db.Column(db.DateTime)       # when admin forwarded to supplier
    forwarded_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

    # Supplier response
    supplier_response  = db.Column(db.Text)
    supplier_responded_at = db.Column(db.DateTime)

    # Resolution
    resolution_notes = db.Column(db.Text)
    resolved_at      = db.Column(db.DateTime)

    created_at      = db.Column(db.DateTime, default=utcnow)
    updated_at      = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)

    # Relationships
    shipper         = db.relationship("ShipperProfile", foreign_keys=[shipper_id],
                                      backref=db.backref("complaints", lazy="dynamic"))
    booking         = db.relationship("Booking", foreign_keys=[booking_id],
                                      backref=db.backref("complaints", lazy="dynamic"))
    supplier        = db.relationship("SupplierProfile", foreign_keys=[supplier_id],
                                      backref=db.backref("complaints", lazy="dynamic"))
    forwarded_by    = db.relationship("User", foreign_keys=[forwarded_by_id])
    assigned_agent  = db.relationship("User", foreign_keys=[assigned_agent_id])
    messages        = db.relationship("ComplaintMessage", back_populates="complaint",
                                      order_by="ComplaintMessage.created_at", cascade="all, delete")

    def generate_ref(self):
        import random, string
        self.ref = "CMP-" + str(datetime.now().year) + "-" + ''.join(random.choices(string.digits, k=5))

    @property
    def status_color(self):
        return {
            "Submitted":             "#1e40af",
            "Under Admin Review":    "#854d0e",
            "Forwarded to Supplier": "#7e22ce",
            "Supplier Responded":    "#065f46",
            "Resolved":              "#166534",
            "Closed":                "#374151",
        }.get(self.status, "#374151")


# ─────────────────────────────────────────────────────────────────────────────
# COMPLAINT MESSAGE THREAD (ported from v15 - two-way conversation)
# ─────────────────────────────────────────────────────────────────────────────

class ComplaintMessage(db.Model):
    __tablename__ = "complaint_messages"

    id            = db.Column(db.Integer, primary_key=True)
    complaint_id  = db.Column(db.Integer, db.ForeignKey("complaints.id"), nullable=False)
    sender_role   = db.Column(db.String(20))   # shipper|support|supplier|system
    sender_name   = db.Column(db.String(120))
    text          = db.Column(db.Text)
    attachment    = db.Column(db.String(200))
    created_at    = db.Column(db.DateTime, default=utcnow)

    complaint     = db.relationship("Complaint", back_populates="messages")


# ─────────────────────────────────────────────────────────────────────────────
# COMPLIANCE DOCUMENTS (supplier compliance vault + admin verification)
# ─────────────────────────────────────────────────────────────────────────────

class ComplianceDocument(db.Model):
    __tablename__ = "compliance_documents"

    id              = db.Column(db.Integer, primary_key=True)
    supplier_id     = db.Column(db.Integer, db.ForeignKey("supplier_profiles.id"), nullable=False)
    name            = db.Column(db.String(120), nullable=False)
    status          = db.Column(db.String(30), default="Pending review")
    # Pending review|Verified|Rejected|Awaiting re-upload
    filename        = db.Column(db.String(200))
    file_size_kb    = db.Column(db.Integer)
    pages           = db.Column(db.Integer)
    expiry_date     = db.Column(db.Date)
    rejection_reason = db.Column(db.String(300))
    uploaded_at     = db.Column(db.DateTime, default=utcnow)
    verified_at     = db.Column(db.DateTime)
    verified_by_id  = db.Column(db.Integer, db.ForeignKey("users.id"))

    supplier        = db.relationship("SupplierProfile", backref=db.backref("documents", lazy="dynamic"))
    verified_by     = db.relationship("User", foreign_keys=[verified_by_id])

    @property
    def is_expiring_soon(self):
        if not self.expiry_date:
            return False
        return (self.expiry_date - datetime.utcnow().date()).days <= 30

    @property
    def days_to_expiry(self):
        if not self.expiry_date:
            return None
        return (self.expiry_date - datetime.utcnow().date()).days


class DocumentRequest(db.Model):
    __tablename__ = "document_requests"

    id              = db.Column(db.Integer, primary_key=True)
    supplier_id     = db.Column(db.Integer, db.ForeignKey("supplier_profiles.id"), nullable=False)
    doc_type        = db.Column(db.String(120), nullable=False)
    deadline        = db.Column(db.Date)
    status          = db.Column(db.String(20), default="Pending")  # Pending|Fulfilled|Overdue
    overdue_action  = db.Column(db.String(20), default="suspend")  # suspend|flag|none
    sent_at         = db.Column(db.DateTime, default=utcnow)
    fulfilled_at    = db.Column(db.DateTime)

    supplier        = db.relationship("SupplierProfile", backref=db.backref("doc_requests", lazy="dynamic"))

    @property
    def is_overdue(self):
        return self.status == "Pending" and self.deadline and self.deadline < datetime.utcnow().date()


# ─────────────────────────────────────────────────────────────────────────────
# RATE CARDS (supplier pricing, versioned)
# ─────────────────────────────────────────────────────────────────────────────

class RateCard(db.Model):
    __tablename__ = "rate_cards"

    id              = db.Column(db.Integer, primary_key=True)
    supplier_id     = db.Column(db.Integer, db.ForeignKey("supplier_profiles.id"), nullable=False)
    route           = db.Column(db.String(120), nullable=False)
    vehicle_type    = db.Column(db.String(60))
    load_type       = db.Column(db.String(80))
    base_rate       = db.Column(db.Float)
    fuel_surcharge_pct = db.Column(db.Float, default=0)
    minimum_charge  = db.Column(db.Float)
    version         = db.Column(db.String(10), default="v1")
    is_active       = db.Column(db.Boolean, default=True)
    created_at      = db.Column(db.DateTime, default=utcnow)
    updated_at      = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)

    supplier        = db.relationship("SupplierProfile", backref=db.backref("rate_cards", lazy="dynamic"))


# ─────────────────────────────────────────────────────────────────────────────
# PAYOUTS (finance - paying suppliers for delivered bookings)
# ─────────────────────────────────────────────────────────────────────────────

class Payout(db.Model):
    __tablename__ = "payouts"

    id              = db.Column(db.Integer, primary_key=True)
    supplier_id     = db.Column(db.Integer, db.ForeignKey("supplier_profiles.id"), nullable=False)
    payout_ref      = db.Column(db.String(30), unique=True, nullable=False)
    amount          = db.Column(db.Float)
    bookings_count  = db.Column(db.Integer)
    bank_summary    = db.Column(db.String(60))     # e.g. "FNB ···1034"
    paid_at         = db.Column(db.DateTime, default=utcnow)
    paid_by_id      = db.Column(db.Integer, db.ForeignKey("users.id"))

    supplier        = db.relationship("SupplierProfile", backref=db.backref("payouts", lazy="dynamic"))
    paid_by         = db.relationship("User", foreign_keys=[paid_by_id])

    def generate_ref(self):
        import random, string
        self.payout_ref = "PAY-" + ''.join(random.choices(string.digits, k=6))


# ─────────────────────────────────────────────────────────────────────────────
# ADMIN ACCOUNTS (departmental admin management - superadmin/finance/support/etc)
# ─────────────────────────────────────────────────────────────────────────────

class AdminAccount(db.Model):
    __tablename__ = "admin_accounts"

    id              = db.Column(db.Integer, primary_key=True)
    user_id         = db.Column(db.Integer, db.ForeignKey("users.id"), unique=True, nullable=False)
    department      = db.Column(db.String(30), default="support")
    # superadmin|finance|support|compliance|operations
    is_active       = db.Column(db.Boolean, default=True)
    created_at      = db.Column(db.DateTime, default=utcnow)
    deactivated_at  = db.Column(db.DateTime)

    user            = db.relationship("User", backref=db.backref("admin_account", uselist=False))

    DEPARTMENTS = {
        "superadmin":  {"name": "Super Admin",      "icon": "Admin"},
        "finance":     {"name": "Finance",          "icon": "Money"},
        "support":     {"name": "Customer Support", "icon": "Shield"},
        "compliance":  {"name": "Compliance",       "icon": "List"},
        "operations":  {"name": "Operations",       "icon": "Settings"},
    }


# ─────────────────────────────────────────────────────────────────────────────
# PLATFORM SETTINGS (volumetric divisor, fees - singleton row)
# ─────────────────────────────────────────────────────────────────────────────

class PlatformSettings(db.Model):
    __tablename__ = "platform_settings"

    id                    = db.Column(db.Integer, primary_key=True)
    volumetric_divisor    = db.Column(db.Integer, default=4000)
    platform_fee_pct      = db.Column(db.Float, default=26.7)
    commission_pct        = db.Column(db.Float, default=3.5)
    updated_at            = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)

    @staticmethod
    def get():
        s = PlatformSettings.query.first()
        if not s:
            s = PlatformSettings()
            db.session.add(s)
            db.session.commit()
        return s


class AISettings(db.Model):
    __tablename__ = "ai_settings"

    id                          = db.Column(db.Integer, primary_key=True)
    proximity_radius_km         = db.Column(db.Integer, default=30)
    price_weight                = db.Column(db.Integer, default=50)
    performance_weight          = db.Column(db.Integer, default=35)
    proximity_weight            = db.Column(db.Integer, default=15)
    min_performance_score       = db.Column(db.Float, default=2.5)
    supplier_response_window_hrs = db.Column(db.Integer, default=2)
    updated_at                  = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)

    @staticmethod
    def get():
        s = AISettings.query.first()
        if not s:
            s = AISettings()
            db.session.add(s)
            db.session.commit()
        return s


# ─────────────────────────────────────────────────────────────────────────────
# CHAT (supplier ↔ driver, driver ↔ supplier messaging)
# ─────────────────────────────────────────────────────────────────────────────

class ChatMessage(db.Model):
    __tablename__ = "chat_messages"

    id              = db.Column(db.Integer, primary_key=True)
    supplier_id     = db.Column(db.Integer, db.ForeignKey("supplier_profiles.id"), nullable=False)
    driver_id       = db.Column(db.Integer, db.ForeignKey("drivers.id"), nullable=False)
    sender_role     = db.Column(db.String(20))   # supplier|driver
    text            = db.Column(db.Text)
    issue_type      = db.Column(db.String(40))   # delay|breakdown|accident|other, optional
    attachment      = db.Column(db.String(200))
    is_read         = db.Column(db.Boolean, default=False)
    created_at      = db.Column(db.DateTime, default=utcnow)

    supplier        = db.relationship("SupplierProfile", backref=db.backref("chat_messages", lazy="dynamic"))
    driver          = db.relationship("Driver", backref=db.backref("chat_messages", lazy="dynamic"))


# ─────────────────────────────────────────────────────────────────────────────
# SHIPPER COMPLIANCE DOCS (CIPC registration, tax clearance, etc.)
# ─────────────────────────────────────────────────────────────────────────────

class ShipperDocument(db.Model):
    __tablename__ = "shipper_documents"

    id              = db.Column(db.Integer, primary_key=True)
    shipper_id      = db.Column(db.Integer, db.ForeignKey("shipper_profiles.id"), nullable=False)
    name            = db.Column(db.String(120), nullable=False)
    status          = db.Column(db.String(30), default="Pending review")
    filename        = db.Column(db.String(200))
    uploaded_at     = db.Column(db.DateTime, default=utcnow)

    shipper         = db.relationship("ShipperProfile", backref=db.backref("documents", lazy="dynamic"))


# ─────────────────────────────────────────────────────────────────────────────
# GIT INSURANCE (Goods-in-Transit - one per booking)
# ─────────────────────────────────────────────────────────────────────────────

class GITInsurance(db.Model):
    __tablename__ = "git_insurance"

    id              = db.Column(db.Integer, primary_key=True)
    booking_id      = db.Column(db.Integer, db.ForeignKey("bookings.id"), unique=True, nullable=False)
    cargo_value     = db.Column(db.Float, nullable=False)       # declared value in ZAR
    premium_rate    = db.Column(db.Float, default=0.8)          # % of cargo value
    premium_amount  = db.Column(db.Float)                       # ZAR premium
    cover_amount    = db.Column(db.Float)                       # = cargo_value
    policy_ref      = db.Column(db.String(40))                  # auto-generated
    provider        = db.Column(db.String(80), default="FFN Insurance Partner")
    status          = db.Column(db.String(20), default="Active")  # Active|Claimed|Expired|Cancelled
    issued_at       = db.Column(db.DateTime, default=utcnow)
    expires_at      = db.Column(db.DateTime)

    booking         = db.relationship("Booking", backref=db.backref("git_insurance", uselist=False, cascade="all, delete"))

    def generate_policy_ref(self):
        import random, string
        self.policy_ref = "GIT-" + ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))

    def calculate_premium(self):
        rate = self.premium_rate if self.premium_rate is not None else 0.8
        self.premium_rate   = rate
        self.premium_amount = round(self.cargo_value * (rate / 100), 2)
        self.cover_amount   = self.cargo_value


# ─────────────────────────────────────────────────────────────────────────────
# POD QR TOKEN (one per booking - scanned at delivery to trigger invoice)
# ─────────────────────────────────────────────────────────────────────────────

class PODToken(db.Model):
    __tablename__ = "pod_tokens"

    id              = db.Column(db.Integer, primary_key=True)
    booking_id      = db.Column(db.Integer, db.ForeignKey("bookings.id"), unique=True, nullable=False)
    token           = db.Column(db.String(64), unique=True, nullable=False, index=True)
    scanned         = db.Column(db.Boolean, default=False)
    scanned_at      = db.Column(db.DateTime)
    scanned_by      = db.Column(db.String(80))   # driver name or scanner identity
    created_at      = db.Column(db.DateTime, default=utcnow)

    booking         = db.relationship("Booking", backref=db.backref("pod_token", uselist=False, cascade="all, delete"))

# ─────────────────────────────────────────────────────────────────────────────
# SUPPLIER CONTROL TOWER: TRAILERS, PLANNING, MAINTENANCE
# ─────────────────────────────────────────────────────────────────────────────

class Trailer(db.Model):
    __tablename__ = "trailers"
    id = db.Column(db.Integer, primary_key=True)
    supplier_id = db.Column(db.Integer, db.ForeignKey("supplier_profiles.id"), nullable=False, index=True)
    asset_number = db.Column(db.String(30), nullable=False)
    reg_number = db.Column(db.String(20), nullable=False)
    trailer_type = db.Column(db.String(60), nullable=False)
    payload_ton = db.Column(db.Float, default=0)
    cbm = db.Column(db.Float, default=0)
    status = db.Column(db.String(25), default="Available")
    current_city = db.Column(db.String(80))
    roadworthy_expiry = db.Column(db.Date)
    licence_expiry = db.Column(db.Date)
    next_service_date = db.Column(db.Date)
    created_at = db.Column(db.DateTime, default=utcnow)
    __table_args__ = (db.UniqueConstraint("supplier_id", "asset_number", name="uq_supplier_trailer_asset"),)

class SupplierPlanningSettings(db.Model):
    __tablename__ = "supplier_planning_settings"
    id = db.Column(db.Integer, primary_key=True)
    supplier_id = db.Column(db.Integer, db.ForeignKey("supplier_profiles.id"), nullable=False, unique=True)
    home_depot_city = db.Column(db.String(80), default="Durban")
    return_load_radius_km = db.Column(db.Integer, default=200)
    max_deadhead_km = db.Column(db.Integer, default=250)
    turnaround_buffer_minutes = db.Column(db.Integer, default=60)
    planning_horizon_days = db.Column(db.Integer, default=14)
    maintenance_warning_km = db.Column(db.Integer, default=1000)
    compliance_warning_days = db.Column(db.Integer, default=30)

class FleetAssignment(db.Model):
    __tablename__ = "fleet_assignments"
    id = db.Column(db.Integer, primary_key=True)
    supplier_id = db.Column(db.Integer, db.ForeignKey("supplier_profiles.id"), nullable=False, index=True)
    booking_id = db.Column(db.Integer, db.ForeignKey("bookings.id"), nullable=False, unique=True)
    vehicle_id = db.Column(db.Integer, db.ForeignKey("vehicles.id"), nullable=False)
    trailer_id = db.Column(db.Integer, db.ForeignKey("trailers.id"))
    driver_id = db.Column(db.Integer, db.ForeignKey("drivers.id"), nullable=False)
    origin_city = db.Column(db.String(80))
    destination_city = db.Column(db.String(80))
    depart_at = db.Column(db.DateTime)
    eta_at = db.Column(db.DateTime)
    available_at = db.Column(db.DateTime)
    projected_city = db.Column(db.String(80))
    return_load_status = db.Column(db.String(30), default="Required")
    dropoff_lat = db.Column(db.Float)
    dropoff_lng = db.Column(db.Float)
    next_booking_id = db.Column(db.Integer, db.ForeignKey("bookings.id"))
    next_booking = db.relationship("Booking", foreign_keys=[next_booking_id])
    created_at = db.Column(db.DateTime, default=utcnow)
    booking = db.relationship("Booking")
    vehicle = db.relationship("Vehicle")
    trailer = db.relationship("Trailer")
    driver = db.relationship("Driver")

class MaintenanceRecord(db.Model):
    __tablename__ = "maintenance_records"
    id = db.Column(db.Integer, primary_key=True)
    supplier_id = db.Column(db.Integer, db.ForeignKey("supplier_profiles.id"), nullable=False, index=True)
    asset_kind = db.Column(db.String(20), nullable=False)  # Horse|Trailer
    vehicle_id = db.Column(db.Integer, db.ForeignKey("vehicles.id"))
    trailer_id = db.Column(db.Integer, db.ForeignKey("trailers.id"))
    maintenance_type = db.Column(db.String(60), nullable=False)
    status = db.Column(db.String(30), default="Scheduled")
    scheduled_date = db.Column(db.Date)
    completed_date = db.Column(db.Date)
    odometer_km = db.Column(db.Integer)
    next_service_km = db.Column(db.Integer)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=utcnow)
