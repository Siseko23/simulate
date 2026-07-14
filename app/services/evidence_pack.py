import io
import os
import zipfile
from datetime import datetime
from pathlib import Path
from werkzeug.utils import secure_filename
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, Image

POD_DIR = os.path.join('app', 'static', 'pod_photos')
INV_DIR = os.path.join('app', 'static', 'supplier_invoices')


def _evidence(booking):
    return getattr(booking, 'delivery_evidence', None)


def pod_files(booking):
    evidence = _evidence(booking)
    if evidence:
        return [f.stored_filename for f in evidence.files]
    found = []
    for event in sorted(booking.status_events, key=lambda x: x.created_at or datetime.min, reverse=True):
        note = event.note or ''
        for marker in ('Proof documents uploaded:', 'Documents:'):
            if marker in note:
                chunk = note.split(marker, 1)[1].split(' | ', 1)[0]
                for raw in chunk.split(','):
                    name = secure_filename(raw.strip())
                    path = os.path.abspath(os.path.join(POD_DIR, name))
                    if name and os.path.isfile(path) and name not in found:
                        found.append(name)
    return found


def pod_meta(booking):
    evidence = _evidence(booking)
    if evidence:
        receiver_sig = evidence.file_of_type('receiver_signature')
        driver_sig = evidence.file_of_type('driver_signature')
        return {
            'receiver': evidence.receiver_name or '',
            'note': evidence.delivery_notes or '',
            'driver_signature': driver_sig.stored_filename if driver_sig else '',
            'receiver_signature': receiver_sig.stored_filename if receiver_sig else '',
            'gps': f'{evidence.latitude:.6f}, {evidence.longitude:.6f}',
        }
    meta = {'receiver': '', 'note': '', 'driver_signature': '', 'receiver_signature': '', 'gps': ''}
    for event in sorted(booking.status_events, key=lambda x: x.created_at or datetime.min, reverse=True):
        note = event.note or ''
        for key, marker in [('receiver','POD signed by '),('note','POD note: '),('note','Note: '),('driver_signature','Driver signature file: '),('receiver_signature','Receiver signature file: '),('gps','Delivery GPS: ')]:
            if not meta[key] and marker in note:
                meta[key] = note.split(marker, 1)[1].split(' | ', 1)[0].strip()
    if not meta['gps'] and booking.gps_lat is not None and booking.gps_lng is not None:
        meta['gps'] = f'{booking.gps_lat:.6f}, {booking.gps_lng:.6f}'
    return meta


def _styles():
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name='FFNTitle', parent=styles['Title'], alignment=TA_CENTER, fontSize=20, leading=24, spaceAfter=12))
    styles.add(ParagraphStyle(name='FFNSub', parent=styles['Heading2'], fontSize=12, leading=15, spaceBefore=8, spaceAfter=6))
    styles.add(ParagraphStyle(name='Small', parent=styles['BodyText'], fontSize=8, leading=10))
    return styles


def _header(story, title, booking):
    styles = _styles()
    story.extend([
        Paragraph('FREIGHTFLOW NEXUS', styles['FFNTitle']),
        Paragraph(title, styles['Heading1']),
        Paragraph(f'Booking reference: <b>{booking.ref}</b>', styles['BodyText']),
        Spacer(1, 6 * mm),
    ])


def _details_table(rows):
    table = Table([[Paragraph(str(a), _styles()['Small']), Paragraph(str(b), _styles()['Small'])] for a, b in rows], colWidths=[52*mm, 120*mm])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (0,-1), colors.HexColor('#F2F4F7')),
        ('GRID', (0,0), (-1,-1), 0.4, colors.HexColor('#D0D5DD')),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('FONTNAME', (0,0), (0,-1), 'Helvetica-Bold'),
        ('LEFTPADDING', (0,0), (-1,-1), 6), ('RIGHTPADDING', (0,0), (-1,-1), 6),
        ('TOPPADDING', (0,0), (-1,-1), 5), ('BOTTOMPADDING', (0,0), (-1,-1), 5),
    ]))
    return table


def _pdf(title, booking, rows, image_paths=None):
    out = io.BytesIO()
    doc = SimpleDocTemplate(out, pagesize=A4, rightMargin=18*mm, leftMargin=18*mm, topMargin=16*mm, bottomMargin=16*mm)
    story = []
    _header(story, title, booking)
    story.append(_details_table(rows))
    for path, caption in image_paths or []:
        if path and os.path.isfile(path) and Path(path).suffix.lower() in {'.png','.jpg','.jpeg','.webp'}:
            story.extend([Spacer(1, 8*mm), Paragraph(caption, _styles()['FFNSub']), Image(path, width=155*mm, height=95*mm, kind='proportional')])
    story.extend([Spacer(1, 10*mm), Paragraph('Generated securely by FreightFlow Nexus.', _styles()['Small'])])
    doc.build(story)
    out.seek(0)
    return out.getvalue()


def waybill_pdf(booking):
    return _pdf('WAYBILL / CMR', booking, [
        ('Route', booking.route or '-'), ('Collection', f'{booking.collection_address or "-"}, {booking.collection_city or "-"}'),
        ('Delivery', f'{booking.delivery_address or "-"}, {booking.delivery_city or "-"}'), ('Commodity', booking.commodity or '-'),
        ('Pieces', booking.pieces or '-'), ('Weight', f'{booking.total_weight_kg or booking.total_weight or "-"} kg'),
        ('Supplier', booking.supplier.company_name if booking.supplier else '-'), ('Driver', booking.driver.name if booking.driver else '-'),
        ('Vehicle', booking.vehicle.reg_number if booking.vehicle else '-'), ('Status', booking.status),
    ])


def purchase_order_pdf(booking, po):
    return _pdf('PURCHASE ORDER', booking, [
        ('PO number', po.po_number), ('Gross amount', f'R {(po.gross_amount or 0):,.2f}'),
        ('Platform fee', f'R {(po.platform_fee or 0):,.2f}'), ('Net payable', f'R {(po.net_payable or 0):,.2f}'),
        ('Status', po.status), ('Created', po.created_at or '-'),
    ])


def pod_pdf(booking):
    m = pod_meta(booking)
    evidence = _evidence(booking)
    image_paths = []
    if evidence:
        for f in evidence.files:
            if f.file_type in {'pod','delivery_photo','receiver_signature','driver_signature'}:
                image_paths.append((os.path.abspath(f.file_path), f.file_type.replace('_',' ').title()))
    return _pdf('PROOF OF DELIVERY', booking, [
        ('Delivered at', booking.delivered_at or '-'), ('Receiver', m['receiver'] or '-'), ('Delivery GPS', m['gps'] or '-'),
        ('Delivery notes', m['note'] or '-'), ('Driver', booking.driver.name if booking.driver else '-'),
        ('Vehicle', booking.vehicle.reg_number if booking.vehicle else '-'), ('POD verified', 'Yes' if booking.pod_signed else 'No'),
    ], image_paths)


def completion_report_pdf(booking):
    m = pod_meta(booking)
    return _pdf('DRIVER COMPLETION REPORT', booking, [
        ('Route', booking.route or '-'), ('Status', booking.status), ('Supplier', booking.supplier.company_name if booking.supplier else '-'),
        ('Driver', booking.driver.name if booking.driver else '-'), ('Vehicle', booking.vehicle.reg_number if booking.vehicle else '-'),
        ('Collected', booking.collected_at or '-'), ('Delivered', booking.delivered_at or '-'), ('Receiver', m['receiver'] or '-'),
        ('Delivery GPS', m['gps'] or '-'), ('Delivery notes', m['note'] or '-'),
        ('Receiver signature', m['receiver_signature'] or '-'), ('Driver signature', m['driver_signature'] or '-'),
    ])


def combined_service_pack_pdf(booking, po=None):
    out = io.BytesIO(); doc = SimpleDocTemplate(out, pagesize=A4, rightMargin=18*mm, leftMargin=18*mm, topMargin=16*mm, bottomMargin=16*mm)
    story=[]; m=pod_meta(booking); _header(story, 'COMPLETE PROOF OF SERVICE PACK', booking)
    story.append(_details_table([('Status', booking.status), ('Route', booking.route or '-'), ('Supplier', booking.supplier.company_name if booking.supplier else '-'), ('Driver', booking.driver.name if booking.driver else '-'), ('Vehicle', booking.vehicle.reg_number if booking.vehicle else '-'), ('Receiver', m['receiver'] or '-'), ('Delivery GPS', m['gps'] or '-'), ('Delivered', booking.delivered_at or '-')]))
    sections=[('Waybill / CMR', [('Collection', f'{booking.collection_address or "-"}, {booking.collection_city or "-"}'), ('Delivery', f'{booking.delivery_address or "-"}, {booking.delivery_city or "-"}'), ('Commodity', booking.commodity or '-'), ('Pieces', booking.pieces or '-'), ('Weight', f'{booking.total_weight_kg or booking.total_weight or "-"} kg')]), ('Proof of Delivery', [('Receiver', m['receiver'] or '-'), ('Notes', m['note'] or '-'), ('POD signed', 'Yes' if booking.pod_signed else 'No')]), ('Driver Completion', [('Collected', booking.collected_at or '-'), ('Delivered', booking.delivered_at or '-'), ('Driver signature', m['driver_signature'] or '-'), ('Receiver signature', m['receiver_signature'] or '-')])]
    if po: sections.insert(1, ('Purchase Order', [('PO number', po.po_number), ('Gross amount', f'R {(po.gross_amount or 0):,.2f}'), ('Net payable', f'R {(po.net_payable or 0):,.2f}'), ('Status', po.status)]))
    for title, rows in sections:
        story.extend([PageBreak(), Paragraph(title, _styles()['Heading1']), Spacer(1, 4*mm), _details_table(rows)])
    evidence=_evidence(booking)
    if evidence:
        for f in evidence.files:
            path=os.path.abspath(f.file_path)
            if os.path.isfile(path) and Path(path).suffix.lower() in {'.png','.jpg','.jpeg','.webp'}:
                story.extend([PageBreak(), Paragraph(f.file_type.replace('_',' ').title(), _styles()['Heading1']), Spacer(1,4*mm), Image(path,width=160*mm,height=110*mm,kind='proportional')])
    doc.build(story); out.seek(0); return out.getvalue()


def build_service_pack(booking, po=None):
    memory = io.BytesIO()
    with zipfile.ZipFile(memory, 'w', zipfile.ZIP_DEFLATED) as zf:
        root = booking.ref
        zf.writestr(f'{root}/00-complete-service-pack.pdf', combined_service_pack_pdf(booking, po))
        zf.writestr(f'{root}/01-waybill-cmr.pdf', waybill_pdf(booking))
        zf.writestr(f'{root}/02-proof-of-delivery.pdf', pod_pdf(booking))
        zf.writestr(f'{root}/03-driver-completion-report.pdf', completion_report_pdf(booking))
        if po:
            zf.writestr(f'{root}/04-purchase-order-{po.po_number}.pdf', purchase_order_pdf(booking, po))
            if po.invoice_filename:
                inv = os.path.abspath(os.path.join(INV_DIR, secure_filename(po.invoice_filename)))
                if os.path.isfile(inv): zf.write(inv, f'{root}/05-supplier-invoice/{secure_filename(po.invoice_filename)}')
        evidence = _evidence(booking)
        if evidence:
            for item in evidence.files:
                path = os.path.abspath(item.file_path)
                if os.path.isfile(path): zf.write(path, f'{root}/06-delivery-evidence/{item.file_type}/{secure_filename(item.original_filename)}')
        else:
            for name in pod_files(booking):
                path = os.path.abspath(os.path.join(POD_DIR, name))
                if os.path.isfile(path): zf.write(path, f'{root}/06-delivery-evidence/{name}')
    memory.seek(0)
    return memory
