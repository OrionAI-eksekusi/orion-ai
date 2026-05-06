import os
import json
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT

QUOTE_DIR = "/tmp/quotes"

def _load_profile() -> dict:
    try:
        if os.path.exists("business_profile.json"):
            with open("business_profile.json", "r") as f:
                return json.load(f)
    except:
        pass
    return {}

def generate_quote_pdf(
    customer_name: str,
    customer_phone: str,
    items: list,
    notes: str = "",
    quote_number: str = None
) -> str:
    """
    Generate PDF quotation
    items = [{"name": str, "qty": int, "unit": str, "price": float, "desc": str}]
    Returns: path to PDF file
    """
    os.makedirs(QUOTE_DIR, exist_ok=True)

    if not quote_number:
        quote_number = f"QUO-{datetime.now().strftime('%Y%m%d%H%M%S')}"

    filename = f"{QUOTE_DIR}/{quote_number}.pdf"
    profile = _load_profile()

    # Setup doc
    doc = SimpleDocTemplate(
        filename,
        pagesize=A4,
        rightMargin=2*cm,
        leftMargin=2*cm,
        topMargin=2*cm,
        bottomMargin=2*cm
    )

    styles = getSampleStyleSheet()
    story = []

    # ── Colors ──
    primary = colors.HexColor("#1A3A8F")
    light_blue = colors.HexColor("#6B9FFF")
    dark = colors.HexColor("#020818")
    gray = colors.HexColor("#6B7280")
    light_gray = colors.HexColor("#F3F4F6")

    # ── Header ──
    company_name = profile.get("name", "Bisnis Anda")
    company_field = profile.get("field", "")
    company_email = profile.get("contact", {}).get("email", "")
    company_wa = profile.get("contact", {}).get("whatsapp", "")
    company_location = profile.get("location", "")

    header_data = [
        [
            Paragraph(f"<font size='20' color='#1A3A8F'><b>{company_name}</b></font>", styles["Normal"]),
            Paragraph(f"<font size='16' color='#1A3A8F'><b>QUOTATION</b></font>", ParagraphStyle("right", alignment=TA_RIGHT)),
        ],
        [
            Paragraph(f"<font size='10' color='#6B7280'>{company_field}</font>", styles["Normal"]),
            Paragraph(f"<font size='10' color='#6B7280'>No: {quote_number}</font>", ParagraphStyle("right", alignment=TA_RIGHT)),
        ],
        [
            Paragraph(f"<font size='9' color='#6B7280'>{company_location}</font>", styles["Normal"]),
            Paragraph(f"<font size='10' color='#6B7280'>Tanggal: {datetime.now().strftime('%d %B %Y')}</font>", ParagraphStyle("right", alignment=TA_RIGHT)),
        ],
        [
            Paragraph(f"<font size='9' color='#6B7280'>WA: {company_wa} | Email: {company_email}</font>", styles["Normal"]),
            Paragraph(f"<font size='10' color='#6B7280'>Berlaku: 14 hari</font>", ParagraphStyle("right", alignment=TA_RIGHT)),
        ],
    ]

    header_table = Table(header_data, colWidths=[10*cm, 7*cm])
    header_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    story.append(header_table)
    story.append(HRFlowable(width="100%", thickness=2, color=primary, spaceAfter=12))

    # ── Customer Info ──
    story.append(Paragraph("<font size='10' color='#6B7280'>Kepada Yth,</font>", styles["Normal"]))
    story.append(Paragraph(f"<font size='13' color='#020818'><b>{customer_name}</b></font>", styles["Normal"]))
    if customer_phone:
        story.append(Paragraph(f"<font size='10' color='#6B7280'>{customer_phone}</font>", styles["Normal"]))
    story.append(Spacer(1, 0.5*cm))

    # ── Items Table ──
    table_header = [
        Paragraph("<b>No</b>", styles["Normal"]),
        Paragraph("<b>Produk/Layanan</b>", styles["Normal"]),
        Paragraph("<b>Qty</b>", styles["Normal"]),
        Paragraph("<b>Satuan</b>", styles["Normal"]),
        Paragraph("<b>Harga Satuan</b>", styles["Normal"]),
        Paragraph("<b>Total</b>", styles["Normal"]),
    ]

    table_data = [table_header]
    subtotal = 0

    for i, item in enumerate(items):
        qty = item.get("qty", 1)
        price = item.get("price", 0)
        total = qty * price
        subtotal += total

        table_data.append([
            Paragraph(str(i + 1), styles["Normal"]),
            Paragraph(f"<b>{item.get('name', '')}</b><br/><font size='8' color='#6B7280'>{item.get('desc', '')}</font>", styles["Normal"]),
            Paragraph(str(qty), styles["Normal"]),
            Paragraph(item.get("unit", "pcs"), styles["Normal"]),
            Paragraph(f"Rp {price:,.0f}", styles["Normal"]),
            Paragraph(f"Rp {total:,.0f}", styles["Normal"]),
        ])

    # Total row
    table_data.append([
        Paragraph("", styles["Normal"]),
        Paragraph("", styles["Normal"]),
        Paragraph("", styles["Normal"]),
        Paragraph("", styles["Normal"]),
        Paragraph("<b>TOTAL</b>", styles["Normal"]),
        Paragraph(f"<b>Rp {subtotal:,.0f}</b>", styles["Normal"]),
    ])

    items_table = Table(table_data, colWidths=[1*cm, 7*cm, 1.5*cm, 2*cm, 3*cm, 3*cm])
    items_table.setStyle(TableStyle([
        # Header
        ('BACKGROUND', (0, 0), (-1, 0), primary),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
        ('TOPPADDING', (0, 0), (-1, 0), 8),
        # Rows
        ('ROWBACKGROUNDS', (0, 1), (-1, -2), [colors.white, light_gray]),
        ('FONTSIZE', (0, 1), (-1, -1), 9),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 6),
        ('TOPPADDING', (0, 1), (-1, -1), 6),
        # Total row
        ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor("#EFF6FF")),
        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, -1), (-1, -1), 11),
        # Grid
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#E5E7EB")),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    story.append(items_table)
    story.append(Spacer(1, 0.5*cm))

    # ── Notes ──
    if notes:
        story.append(HRFlowable(width="100%", thickness=0.5, color=gray, spaceAfter=6))
        story.append(Paragraph("<font size='10' color='#6B7280'><b>Catatan:</b></font>", styles["Normal"]))
        story.append(Paragraph(f"<font size='10' color='#6B7280'>{notes}</font>", styles["Normal"]))
        story.append(Spacer(1, 0.3*cm))

    # ── Footer ──
    story.append(HRFlowable(width="100%", thickness=0.5, color=gray, spaceAfter=6))
    story.append(Paragraph(
        f"<font size='9' color='#6B7280'>Quotation ini dibuat otomatis oleh Orion AI • {company_name} • {datetime.now().strftime('%d/%m/%Y %H:%M')}</font>",
        ParagraphStyle("center", alignment=TA_CENTER)
    ))

    doc.build(story)
    return filename


async def generate_quote_from_request(
    customer_name: str,
    customer_phone: str,
    request_text: str
) -> dict:
    """
    Generate quotation dari request text menggunakan AI
    Returns: {"pdf_path": str, "items": list, "quote_number": str}
    """
    from app.services.ai_service import call_llm_direct
    from app.services.ai_provider import call_llm
    import json
    import re

    profile = _load_profile()
    products = profile.get("products", [])

    system_prompt = f"""Kamu adalah asisten bisnis yang membuat quotation.
Bisnis: {profile.get('name', 'Bisnis')}
Produk yang tersedia: {json.dumps(products, ensure_ascii=False)}

Dari request customer, buat quotation dalam format JSON:
{{
  "items": [
    {{
      "name": "nama produk",
      "desc": "deskripsi singkat",
      "qty": 1,
      "unit": "pcs/kg/liter/dll",
      "price": 0
    }}
  ],
  "notes": "catatan tambahan jika ada"
}}

Untuk harga, gunakan harga dari profil bisnis. Jika tidak ada, tulis 0.
Respond HANYA dengan JSON, tanpa penjelasan."""

    try:
        ai_response = await call_llm(system_prompt, request_text)
        clean = ai_response.replace('```json', '').replace('```', '').strip()
        quote_data = json.loads(clean)
    except Exception as e:
        # Default jika AI gagal parse
        quote_data = {
            "items": [{"name": "Produk", "desc": request_text[:50], "qty": 1, "unit": "pcs", "price": 0}],
            "notes": "Harga akan dikonfirmasi lebih lanjut"
        }

    quote_number = f"QUO-{datetime.now().strftime('%Y%m%d%H%M%S')}"

    pdf_path = generate_quote_pdf(
        customer_name=customer_name,
        customer_phone=customer_phone,
        items=quote_data.get("items", []),
        notes=quote_data.get("notes", ""),
        quote_number=quote_number
    )

    return {
        "pdf_path": pdf_path,
        "items": quote_data.get("items", []),
        "quote_number": quote_number,
        "notes": quote_data.get("notes", "")
    }