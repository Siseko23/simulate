import io, zipfile
from app.models import Booking
from app.services.evidence_pack import waybill_pdf, pod_pdf, completion_report_pdf, combined_service_pack_pdf, build_service_pack

def test_public_home_runs(client):
    assert client.get("/").status_code == 200

def test_pdf_and_zip_generation(app):
    with app.app_context():
        booking = Booking.query.first()
        assert booking is not None
        assert waybill_pdf(booking).startswith(b"%PDF")
        assert pod_pdf(booking).startswith(b"%PDF")
        assert completion_report_pdf(booking).startswith(b"%PDF")
        assert combined_service_pack_pdf(booking).startswith(b"%PDF")
        package = build_service_pack(booking).getvalue()
        with zipfile.ZipFile(io.BytesIO(package)) as archive:
            names = archive.namelist()
            assert any(name.endswith("00-complete-service-pack.pdf") for name in names)
            assert any(name.endswith("01-waybill-cmr.pdf") for name in names)
            assert any(name.endswith("02-proof-of-delivery.pdf") for name in names)
            assert any(name.endswith("03-driver-completion-report.pdf") for name in names)
