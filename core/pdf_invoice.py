"""
Generates a Munwan Car Rental invoice as a PDF using ReportLab.

We use ReportLab over WeasyPrint/wkhtmltopdf because it's:
- Pure Python (no external binaries, no headless Chrome)
- Already a transitive dep (xhtml2pdf), already installed in production
- Fast (PDF in ~50ms vs 2-3s for headless browsers)

The layout is hand-built (no HTML→PDF conversion) for total control over
columns, fonts, and the brand header. If you ever swap engines, the
public function signature `render_invoice_pdf(booking) -> bytes` stays.
"""
from io import BytesIO
from decimal import Decimal

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                TableStyle, KeepTogether)


# Brand palette — matches the website CSS variables
NAVY    = colors.HexColor('#0D1A3A')
BLUE    = colors.HexColor('#1565FF')
INK     = colors.HexColor('#0A0F1E')
MUTED   = colors.HexColor('#6B7280')
LIGHT   = colors.HexColor('#F8FAFC')
BORDER  = colors.HexColor('#E5E7EB')


def render_invoice_pdf(booking) -> bytes:
    """Build the PDF bytes for the given booking. booking must be corporate
    and already have invoice_number, invoice_issued_at, invoice_due_date
    populated (set by booking_submit when hire_type='corporate')."""

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=18*mm, rightMargin=18*mm,
        topMargin=18*mm, bottomMargin=18*mm,
        title=f'Invoice {booking.invoice_number or booking.reference}',
    )
    styles = getSampleStyleSheet()
    body  = ParagraphStyle('body',  parent=styles['Normal'], fontName='Helvetica',     fontSize=9.5, leading=13, textColor=INK)
    small = ParagraphStyle('small', parent=styles['Normal'], fontName='Helvetica',     fontSize=8.5, leading=11, textColor=MUTED)
    h1    = ParagraphStyle('h1',    parent=styles['Heading1'], fontName='Helvetica-Bold', fontSize=22, textColor=NAVY, spaceAfter=2)
    h2    = ParagraphStyle('h2',    parent=styles['Heading2'], fontName='Helvetica-Bold', fontSize=11, textColor=NAVY, spaceAfter=6)
    big   = ParagraphStyle('big',   parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=14, textColor=BLUE)
    invlabel = ParagraphStyle('invlabel', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=9, textColor=MUTED, alignment=2)
    invvalue = ParagraphStyle('invvalue', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=11, textColor=INK, alignment=2)
    addrlbl  = ParagraphStyle('addrlbl', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=8.5, textColor=MUTED)

    story = []

    # ── HEADER: brand left + invoice meta right ─────────────────────
    header_data = [[
        # Left cell — brand block
        [
            Paragraph('Munwan Car Rental', h1),
            Paragraph('Premium Car Rental · Self Drive &amp; Chauffeur Services', small),
            Spacer(1, 8),
            Paragraph('Nairobi, Kenya', body),
            Paragraph('+254 727 745 907', body),
            Paragraph('info@munwancarrental.com', body),
            Paragraph('munwancarrental.com', body),
        ],
        # Right cell — invoice meta
        [
            Paragraph('INVOICE', invlabel),
            Paragraph(booking.invoice_number or booking.reference, invvalue),
            Spacer(1, 8),
            Paragraph('Issued', invlabel),
            Paragraph(
                booking.invoice_issued_at.strftime('%d %b %Y') if booking.invoice_issued_at else '—',
                invvalue),
            Spacer(1, 4),
            Paragraph('Due', invlabel),
            Paragraph(
                booking.invoice_due_date.strftime('%d %b %Y') if booking.invoice_due_date else '—',
                invvalue),
        ],
    ]]
    header = Table(header_data, colWidths=[100*mm, 70*mm])
    header.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('LEFTPADDING', (0,0), (-1,-1), 0),
        ('RIGHTPADDING', (0,0), (-1,-1), 0),
    ]))
    story.append(header)
    story.append(Spacer(1, 12))

    # Coloured rule
    rule = Table([['']], colWidths=[174*mm], rowHeights=[2])
    rule.setStyle(TableStyle([('BACKGROUND', (0,0), (-1,-1), BLUE)]))
    story.append(rule)
    story.append(Spacer(1, 12))

    # ── BILL TO ────────────────────────────────────────────────────
    bill_to_left = [
        Paragraph('BILL TO', addrlbl),
        Spacer(1, 4),
        Paragraph(f'<b>{booking.first_name} {booking.last_name}</b>', body),
        Paragraph(booking.email or '', body),
        Paragraph(booking.phone or '', body),
    ]
    if booking.nationality:
        bill_to_left.append(Paragraph(booking.nationality, body))

    bill_to_right = [
        Paragraph('BOOKING REFERENCE', addrlbl),
        Spacer(1, 4),
        Paragraph(f'<b>{booking.reference}</b>', body),
        Spacer(1, 4),
        Paragraph('SERVICE', addrlbl),
        Paragraph(booking.get_hire_type_display(), body),
    ]
    bill_table = Table([[bill_to_left, bill_to_right]], colWidths=[100*mm, 70*mm])
    bill_table.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('LEFTPADDING', (0,0), (-1,-1), 0),
        ('RIGHTPADDING', (0,0), (-1,-1), 0),
    ]))
    story.append(bill_table)
    story.append(Spacer(1, 18))

    # ── LINE ITEMS ─────────────────────────────────────────────────
    days = int(booking.days or 0) or 1
    vehicle_name = booking.vehicle.name if booking.vehicle else 'Vehicle TBD'
    base = booking.base_price_usd or 0
    driver = booking.driver_fee_usd or 0

    rows = [
        ['DESCRIPTION', 'QTY', 'RATE', 'AMOUNT'],
        [
            Paragraph(
                f'<b>{vehicle_name}</b><br/>'
                f'<font color="#6B7280" size="8.5">'
                f'Pickup: {booking.pickup_date.strftime("%d %b %Y") if booking.pickup_date else "—"} · '
                f'Return: {booking.return_date.strftime("%d %b %Y") if booking.return_date else "—"}'
                f'</font>',
                body),
            f'{days}',
            f'${(Decimal(base) / Decimal(days)).quantize(Decimal("0.01")) if days else base}',
            f'${base}',
        ],
    ]
    if driver and booking.with_driver:
        rows.append([
            Paragraph('<b>Professional Driver</b><br/>'
                      '<font color="#6B7280" size="8.5">Daily driver fee — fuel and allowance included</font>',
                      body),
            f'{days}',
            f'${(Decimal(driver) / Decimal(days)).quantize(Decimal("0.01")) if days else driver}',
            f'${driver}',
        ])
    if booking.baby_seat:
        rows.append([
            Paragraph('<b>Baby Seat</b><br/>'
                      '<font color="#6B7280" size="8.5">One-time fee — fitted at pickup</font>',
                      body),
            '1',
            '$10.00',
            '$10.00',
        ])

    items = Table(rows, colWidths=[90*mm, 18*mm, 30*mm, 32*mm], repeatRows=1)
    items.setStyle(TableStyle([
        # Header row
        ('BACKGROUND', (0,0), (-1,0), NAVY),
        ('TEXTCOLOR',  (0,0), (-1,0), colors.white),
        ('FONTNAME',   (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE',   (0,0), (-1,0), 8.5),
        ('ALIGN',      (1,0), (-1,0), 'RIGHT'),
        ('ALIGN',      (0,0), (0,0),  'LEFT'),
        ('TOPPADDING', (0,0), (-1,0), 8),
        ('BOTTOMPADDING', (0,0), (-1,0), 8),
        # Body rows
        ('VALIGN',     (0,1), (-1,-1), 'TOP'),
        ('ALIGN',      (1,1), (-1,-1), 'RIGHT'),
        ('FONTNAME',   (0,1), (-1,-1), 'Helvetica'),
        ('FONTSIZE',   (0,1), (-1,-1), 9.5),
        ('TEXTCOLOR',  (0,1), (-1,-1), INK),
        ('TOPPADDING', (0,1), (-1,-1), 10),
        ('BOTTOMPADDING', (0,1), (-1,-1), 10),
        ('LINEBELOW', (0,1), (-1,-1), 0.5, BORDER),
    ]))
    story.append(items)
    story.append(Spacer(1, 6))

    # ── TOTALS ─────────────────────────────────────────────────────
    totals_rows = [
        ['', 'Subtotal (USD)', f'${booking.total_usd or 0}'],
    ]
    if booking.total_kes:
        totals_rows.append(['', '≈ KES', f'KES {booking.total_kes:,.0f}'.replace(',', ',')])
    if booking.total_eur:
        totals_rows.append(['', '≈ EUR', f'€{booking.total_eur}'])
    totals_rows.append(['', 'TOTAL DUE', f'${booking.total_usd or 0}'])

    totals = Table(totals_rows, colWidths=[90*mm, 50*mm, 30*mm])
    totals.setStyle(TableStyle([
        ('ALIGN',      (1,0), (-1,-1), 'RIGHT'),
        ('FONTNAME',   (0,0), (-1,-1), 'Helvetica'),
        ('FONTSIZE',   (0,0), (-1,-1), 9.5),
        ('TEXTCOLOR',  (1,0), (1,-2),  MUTED),
        ('TEXTCOLOR',  (2,0), (2,-2),  INK),
        ('TOPPADDING', (0,0), (-1,-1), 4),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        # Total row
        ('BACKGROUND', (1,-1), (-1,-1), LIGHT),
        ('FONTNAME',   (1,-1), (-1,-1), 'Helvetica-Bold'),
        ('FONTSIZE',   (1,-1), (-1,-1), 12),
        ('TEXTCOLOR',  (1,-1), (1,-1),  NAVY),
        ('TEXTCOLOR',  (2,-1), (2,-1),  BLUE),
        ('TOPPADDING', (1,-1), (-1,-1), 8),
        ('BOTTOMPADDING', (1,-1), (-1,-1), 8),
    ]))
    story.append(totals)
    story.append(Spacer(1, 20))

    # ── PAYMENT INSTRUCTIONS ───────────────────────────────────────
    pay_block = [
        Paragraph('PAYMENT INSTRUCTIONS', h2),
        Paragraph(
            '<b>Pay online:</b> Visit '
            f'<font color="#1565FF">munwancarrental.com/?resume={booking.reference}</font> '
            'to settle this invoice by Visa, Mastercard, M-Pesa, or PayPal. '
            f'Payment is due by <b>{booking.invoice_due_date.strftime("%d %b %Y") if booking.invoice_due_date else "pickup date"}</b> '
            f'— one day before vehicle pickup.',
            body),
        Spacer(1, 6),
        Paragraph(
            '<b>Bank transfer:</b> Please WhatsApp us at +254 727 745 907 for '
            'bank account details. Quote invoice number '
            f'<b>{booking.invoice_number or booking.reference}</b> as the reference.',
            body),
        Spacer(1, 10),
        Paragraph('TERMS', h2),
        Paragraph(
            'Vehicle reservation is confirmed only after full payment is received. '
            'Late payment may result in the vehicle being released to another customer. '
            'Cancellations 48+ hours before pickup are refundable in full; '
            'cancellations within 24 hours forfeit 20% of the invoice value.',
            small),
        Spacer(1, 14),
        Paragraph(
            '<i>Thank you for choosing Munwan Car Rental.</i>',
            ParagraphStyle('thanks', parent=body, alignment=1, textColor=NAVY,
                           fontName='Helvetica-Oblique')),
    ]
    for el in pay_block:
        story.append(el)

    doc.build(story)
    pdf = buf.getvalue()
    buf.close()
    return pdf