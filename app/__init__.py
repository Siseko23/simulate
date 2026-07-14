"""
FreightFlow Nexus - Application Factory
"""
from flask import Flask
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_mail import Mail

from config import config
from app.models import db, User, Complaint, ComplaintMessage, ComplianceDocument, DocumentRequest, RateCard, Payout, AdminAccount, PlatformSettings, AISettings, ChatMessage, ShipperDocument, DeliveryEvidence, DeliveryEvidenceFile  # noqa: F401 - ensure all models are in metadata

login_manager = LoginManager()
migrate       = Migrate()
mail          = Mail()


def _ensure_runtime_columns(app):
    """Small SQLite-safe compatibility migration for demo zips.

    Older packaged demo databases do not have the supplier SLA columns yet.
    Flask-Migrate remains the proper production path, but this keeps the
    downloadable demo runnable immediately after unzip.
    """
    with app.app_context():
        try:
            uri = app.config.get("SQLALCHEMY_DATABASE_URI", "")
            if not uri.startswith("sqlite"):
                return
            from sqlalchemy import inspect, text
            existing = {c["name"] for c in inspect(db.engine).get_columns("bookings")}
            additions = {
                "supplier_response_deadline": "DATETIME",
                "supplier_accepted_at": "DATETIME",
                "driver_assigned_at": "DATETIME",
                "supplier_sla_status": "VARCHAR(30) DEFAULT 'Not Started'",
                "location_access_requested": "BOOLEAN DEFAULT 0",
                "location_access_reason": "VARCHAR(200)",
                "location_access_status": "VARCHAR(20) DEFAULT 'Not Requested'",
                "location_access_approved_at": "DATETIME",
                "collection_lat": "FLOAT",
                "collection_lng": "FLOAT",
                "delivery_lat": "FLOAT",
                "delivery_lng": "FLOAT",
            }
            with db.engine.begin() as conn:
                for name, sql_type in additions.items():
                    if name not in existing:
                        conn.execute(text(f"ALTER TABLE bookings ADD COLUMN {name} {sql_type}"))
            fa_existing = {c["name"] for c in inspect(db.engine).get_columns("fleet_assignments")} if inspect(db.engine).has_table("fleet_assignments") else set()
            fa_additions = {"dropoff_lat":"FLOAT", "dropoff_lng":"FLOAT", "next_booking_id":"INTEGER"}
            with db.engine.begin() as conn:
                for name, sql_type in fa_additions.items():
                    if name not in fa_existing:
                        conn.execute(text(f"ALTER TABLE fleet_assignments ADD COLUMN {name} {sql_type}"))
        except Exception:
            # Never block app startup over compatibility migration; route-level
            # guards still fail safely if a DB cannot be altered.
            pass


def create_app(config_name="default"):
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config.from_object(config[config_name])

    # Init extensions
    db.init_app(app)
    migrate.init_app(app, db)
    mail.init_app(app)
    _ensure_runtime_columns(app)
    with app.app_context():
        # Creates new additive tables such as delivery evidence without touching existing demo data.
        db.create_all()

    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = "Please log in to access this page."
    login_manager.login_message_category = "warning"

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    # Register blueprints
    from app.routes.auth     import auth_bp
    from app.routes.shipper  import shipper_bp
    from app.routes.supplier import supplier_bp
    from app.routes.admin    import admin_bp
    from app.routes.driver   import driver_bp
    from app.routes.public   import public_bp, api_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(shipper_bp,  url_prefix="/shipper")
    app.register_blueprint(supplier_bp, url_prefix="/supplier")
    app.register_blueprint(admin_bp,    url_prefix="/admin")
    app.register_blueprint(driver_bp,   url_prefix="/driver")
    app.register_blueprint(public_bp)
    app.register_blueprint(api_bp,      url_prefix="/api")

    # Jinja helpers - registered as BOTH filters and globals so templates
    # can use either {{ value | zar }} or {{ zar(value) }}
    def _zar(value):
        try:
            return f"R {float(value):,.2f}"
        except (TypeError, ValueError):
            return "R 0.00"

    def _pct(value):
        try:
            return f"{float(value):.1f}%"
        except (TypeError, ValueError):
            return "0%"

    app.template_filter("zar")(_zar)
    app.template_filter("pct")(_pct)
    app.jinja_env.globals["zar"] = _zar
    app.jinja_env.globals["pct"] = _pct

    # enumerate_filter: used in v19 templates as `list | enumerate_filter`
    # returns list of (index, item) tuples - same as Python enumerate()
    app.jinja_env.filters["enumerate_filter"] = lambda iterable: list(enumerate(iterable))
    app.jinja_env.globals["enumerate"] = enumerate

    @app.context_processor
    def inject_globals():
        from flask_login import current_user
        from app.models import Notification
        from datetime import timedelta

        role = None
        user = None
        bell_notifications = []
        bell_count = 0

        if current_user.is_authenticated:
            role = current_user.role
            user = current_user.full_name or current_user.email

            # Build bell notifications matching v19 format
            raw = current_user.notifications\
                      .order_by(Notification.created_at.desc()).limit(6).all()
            bell_count = current_user.notifications.filter_by(is_read=False).count()

            icon_map = {"success":"OK", "warning":"Warning", "error":"X", "info":"Info"}
            for n in raw:
                # human-readable time delta
                from datetime import datetime
                delta = datetime.utcnow() - n.created_at
                if delta.seconds < 3600:
                    t = f"{delta.seconds // 60}m ago"
                elif delta.days == 0:
                    t = f"{delta.seconds // 3600}h ago"
                else:
                    t = f"{delta.days}d ago"

                # Make notification items real navigation targets instead of inert # links.
                link = None
                if n.ref_type == "booking" and n.ref_id:
                    if role == "shipper":
                        link = f"/shipper/bookings/{n.ref_id}"
                    elif role == "supplier":
                        link = "/supplier/bookings"
                    elif role == "driver":
                        link = f"/driver/booking/{n.ref_id}"
                    elif role == "admin":
                        link = f"/admin/bookings?q={n.ref_id}"
                elif role == "shipper":
                    link = "/shipper/"
                elif role == "supplier":
                    link = "/supplier/"
                elif role == "driver":
                    link = "/driver/"
                elif role == "admin":
                    link = "/admin/"
                else:
                    link = "/"

                bell_notifications.append({
                    "id":     n.id,
                    "title":  n.title,
                    "detail": n.body[:60] + "..." if n.body and len(n.body) > 60 else n.body or "",
                    "time":   t,
                    "icon":   icon_map.get(n.type, "Info"),
                    "read":   n.is_read,
                    "link":   link,
                })

        return dict(
            role=role,
            user=user,
            bell_notifications=bell_notifications,
            bell_count=bell_count,
            unread_notifications=bell_count,
            google_maps_key=(app.config.get("GOOGLE_MAPS_API_KEY") or app.config.get("GOOGLE_MAPS_KEY") or ""),
        )

    return app
