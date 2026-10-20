import io
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

def generate_po_pdf(po_data: dict) -> bytes:
    """Generates a professional Purchase Order PDF document stream."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=36,
        leftMargin=36,
        topMargin=36,
        bottomMargin=36
    )

    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Heading1'],
        fontSize=20,
        leading=24,
        textColor=colors.HexColor('#1C1917'),
        fontName='Helvetica-Bold'
    )
    
    meta_style = ParagraphStyle(
        'MetaText',
        parent=styles['Normal'],
        fontSize=10,
        leading=14,
        textColor=colors.HexColor('#57534E')
    )

    story = []

    # Header
    story.append(Paragraph("<b>CARLTREN SUPPLY</b> — PURCHASE ORDER", title_style))
    story.append(Paragraph("Hardware, Fasteners & Building Supplies | Operations & Procurement", meta_style))
    story.append(Spacer(1, 12))
    story.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor('#EA580C'), spaceAfter=15))

    # Order & Supplier Meta Table
    meta_data = [
        [
            Paragraph(f"<b>PO Number:</b> {po_data.get('po_number', 'N/A')}", meta_style),
            Paragraph(f"<b>Supplier:</b> {po_data.get('supplier', 'N/A')}", meta_style)
        ],
        [
            Paragraph(f"<b>Created Date:</b> {po_data.get('created_at', 'N/A')}", meta_style),
            Paragraph(f"<b>Status:</b> {str(po_data.get('status', 'PENDING')).upper()}", meta_style)
        ],
        [
            Paragraph(f"<b>Expected Delivery:</b> {po_data.get('expected_delivery', 'N/A')}", meta_style),
            Paragraph(f"<b>Created By:</b> {po_data.get('created_by', 'Copilot AI')}", meta_style)
        ],
    ]
    meta_table = Table(meta_data, colWidths=[270, 270])
    meta_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#F5F5F4')),
        ('PADDING', (0,0), (-1,-1), 8),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
    ]))
    story.append(meta_table)
    story.append(Spacer(1, 20))

    # Line Item Table
    story.append(Paragraph("<b>ORDER LINE ITEMS</b>", styles['Heading3']))
    story.append(Spacer(1, 8))

    unit_cost = float(po_data.get('unit_cost', 0.0))
    qty = int(po_data.get('quantity', 0))
    total_cost = float(po_data.get('total_cost', unit_cost * qty))

    items_data = [
        ["SKU", "Description", "Qty", "Unit Price", "Total Amount"],
        [
            po_data.get('sku', 'N/A'),
            po_data.get('product', 'Hardware Item'),
            str(qty),
            f"${unit_cost:,.2f}",
            f"${total_cost:,.2f}"
        ]
    ]

    item_table = Table(items_data, colWidths=[80, 240, 50, 85, 85])
    item_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#1C1917')),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,0), 9),
        ('ALIGN', (2,0), (-1,-1), 'RIGHT'),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#E7E5E4')),
        ('PADDING', (0,0), (-1,-1), 8),
    ]))
    story.append(item_table)
    story.append(Spacer(1, 25))

    # Reason & Human Authorization Callout
    reason_text = po_data.get('reason', 'Automatic stockout threshold reorder initiated by Stockroom Copilot.')
    story.append(Paragraph(f"<b>Reorder Reason:</b> {reason_text}", meta_style))
    story.append(Spacer(1, 20))

    auth_data = [
        [
            Paragraph("<b>Human Authorization Signature:</b> ___________________________", meta_style),
            Paragraph("<b>Date:</b> _____________", meta_style)
        ]
    ]
    auth_table = Table(auth_data, colWidths=[360, 180])
    story.append(auth_table)

    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()