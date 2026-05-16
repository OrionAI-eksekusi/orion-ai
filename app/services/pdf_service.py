"""
APEX PDF Quotation Service
Generate dan kirim PDF penawaran otomatis via WA
"""
import os
import httpx
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.units import cm
import tempfile

WA_GATEWAY_URL = os.getenv("WA_GATEWAY_URL", "https://worker-production-67d8.up.railway.app")

async def generate_and_send_quotation(
    user_id: str,
    phone: str,
    customer_name: str,
    items: list,
    notes: str = "",
    business_name: str = "Orion AI Business"
):
    """
    Generate PDF quotation dan kirim via WA otomatis
    items = [{"name": "Produk A", "qty": 2, "price": 500000}]
    """
    try:
        # Generate PDF
        pdf_path = await create_quotation_pdf(
            customer_name=customer_name,
            items=items,
            notes=notes,
            business_name=business_name
        )

        # Kirim via WA
        await send_pdf_via_wa(user_id, phone, pdf_path, customer_name)

        print(f"[PDF] ✅ Quotation sent to {phone}")
        return {"status": "success", "pdf_path": pdf_path}

    except Exception as e:
        print(f"[PDF] ❌ Error: {e}")
        return {"status": "error", "error": str(e)}

async def create_quotation_pdf(
    customer_name: str,
    items: list,
    notes: str,
    business_name: str
) -> str:
    """Generate PDF quotation menggunakan ReportLab"""

    quote_number = f"QUO-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    date_str = datetime.now().strftime("%d %B %Y")

    # Temp file
    tmp = tempfile.NamedTemporaryFile(suffix='.pdf', delete=False)
    pdf_path = tmp.name
    tmp.close()

    doc = SimpleDocTemplate(pdf_path, pagesize=A4,
                            rightMargin=2*cm, leftMargin=2*cm,
                            topMargin=2*cm, bottomMargin=2*cm)

    styles = getSampleStyleSheet()
    elements = []

    # Header
    header_style = ParagraphStyle('header', fontSize=20, fontName='Helvetica-Bold',
                                   textColor=colors.HexColor('#1E3A5F'), spaceAfter=4)
    sub_style = ParagraphStyle('sub', fontSize=10, fontName='Helvetica',
                                textColor=colors.HexColor('#666666'), spaceAfter=2)
    normal_style = ParagraphStyle('normal', fontSize=10, fontName='Helvetica', spaceAfter=4)

    elements.append(Paragraph(business_name, header_style))
    elements.append(Paragraph(f"Nomor: {quote_number}", sub_style))
    elements.append(Paragraph(f"Tanggal: {date_str}", sub_style))
    elements.append(Spacer(1, 0.5*cm))

    # Customer info
    elements.append(Paragraph(f"Kepada Yth:", normal_style))
    elements.append(Paragraph(f"<b>{customer_name}</b>", normal_style))
    elements.append(Spacer(1, 0.5*cm))

    # Items table
    table_data = [['No', 'Item', 'Qty', 'Harga Satuan', 'Total']]
    total = 0

    for i, item in enumerate(items, 1):
        qty = item.get('qty', 1)
        price = item.get('price', 0)
        subtotal = qty * price
        total += subtotal
        table_data.append([
            str(i),
            item.get('name', ''),
            str(qty),
            f"Rp {price:,.0f}",
            f"Rp {subtotal:,.0f}"
        ])

    # Total row
    table_data.append(['', '', '', '<b>TOTAL</b>', f'<b>Rp {total:,.0f}</b>'])

    table = Table(table_data, colWidths=[1*cm, 7*cm, 2*cm, 4*cm, 4*cm])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1E3A5F')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('ALIGN', (1, 1), (1, -1), 'LEFT'),
        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
        ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#F0F4FF')),
        ('GRID', (0, 0), (-1, -2), 0.5, colors.HexColor('#CCCCCC')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -2), [colors.white, colors.HexColor('#F8F9FA')]),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))

    elements.append(table)
    elements.append(Spacer(1, 0.5*cm))

    if notes:
        elements.append(Paragraph(f"<i>Catatan: {notes}</i>", normal_style))

    elements.append(Spacer(1, 1*cm))
    elements.append(Paragraph("Terima kasih atas kepercayaan Anda! 🙏", normal_style))

    doc.build(elements)
    return pdf_path

async def send_pdf_via_wa(user_id: str, phone: str, pdf_path: str, customer_name: str):
    """Kirim PDF via WA Gateway"""
    async with httpx.AsyncClient(timeout=30) as client:
        # Kirim pesan dulu
        await client.post(f"{WA_GATEWAY_URL}/send-message", json={
            "user_id": user_id,
            "phone": phone,
            "message": f"Halo {customer_name}! 😊 Berikut quotation yang sudah kami siapkan untuk kamu. Silakan cek file PDF di bawah ini ya!"
        })

        # Kirim file PDF
        with open(pdf_path, 'rb') as f:
            files = {'file': (f'Quotation-{customer_name}.pdf', f, 'application/pdf')}
            data = {'user_id': user_id, 'phone': phone}
            await client.post(f"{WA_GATEWAY_URL}/send-file", files=files, data=data)

        # Cleanup
        os.unlink(pdf_path)