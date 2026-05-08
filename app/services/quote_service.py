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


def _load_profile(user_id: str = "default") -> dict:
    """Load business profile per user dari database atau file"""
    try:
        # Coba load dari database per user dulu
        profile_path = f"profiles/{user_id}_business.json"
        if os.path.exists(profile_path):
            with open(profile_path, "r") as f:
                return json.load(f)

        # Fallback ke WA gateway profile
        wa_profile_paths = [
            "/app/business_profile.json",
            "business_profile.json",
            "../orion-wa-gateway/business_profile.json",
        ]
        for path in wa_profile_paths:
            if os.path.exists(path):
                with open(path, "r") as f:
                    return json.load(f)
    except:
        pass

    # Default profile kalau tidak ada
    return {
        "name": "Bisnis Anda",
        "field": "",
        "description": "",
        "products": [],
        "contact": {"email": "", "whatsapp": ""},
        "location": "Indonesia",
        "working_hours": "Senin-Sabtu, 08.00-17.00 WIB"
    }


def generate_quote_pdf(
    customer_name: str,
    customer_phone: str,
    items: list,
    notes: str = "",
    quote_number: str = None,
    user_id: str = "default"
) -> str:
    """
    Generate PDF quotation per user
    items = [{"name": str, "qty": int, "unit": str, "price": float, "desc": str}]
    Returns: path to PDF file
    """
    os.makedirs(QUOTE_DIR, exist_ok=True)

    if not quote_number:
        quote_number = f"QUO-{datetime.now().strftime('%Y%m%d%H%M%S')}"

    filename = f"{QUOTE_DIR}/{quote_number}.pdf"
    profile = _load_profile(user_id)

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
    gray = colors.HexColor("#6B7280")
    light_gray = colors.HexColor("#F3F4F6")

    # ── Company Info ──
    company_name = profile.get("name", "Bisnis Anda")
    company_field = profile.get("field", "")
    company_email = profile.get("contact", {}).get("email", "")
    company_wa = profile.get("contact", {}).get("whatsapp", "")
    company_location = profile.get("location", "")

    header_data = [
        [
            Paragraph(f"<font size='20' color='#1A3A8F'><b>{company_name}</b></font>",
                      styles["Normal"]),
            Paragraph(f"<font size='16' color='#1A3A8F'><b>QUOTATION</b></font>",
                      ParagraphStyle("right", alignment=TA_RIGHT)),
        ],
        [
            Paragraph(f"<font size='10' color='#6B7280'>{company_field}</font>",
                      styles["Normal"]),
            Paragraph(f"<font size='10' color='#6B7280'>No: {quote_number}</font>",
                      ParagraphStyle("right", alignment=TA_RIGHT)),
        ],
        [
            Paragraph(f"<font size='9' color='#6B7280'>{company_location}</font>",
                      styles["Normal"]),
            Paragraph(f"<font size='10' color='#6B7280'>Tanggal: {datetime.now().strftime('%d %B %Y')}</font>",
                      ParagraphStyle("right", alignment=TA_RIGHT)),
        ],
        [
            Paragraph(f"<font size='9' color='#6B7280'>WA: {company_wa} | Email: {company_email}</font>",
                      styles["Normal"]),
            Paragraph(f"<font size='10' color='#6B7280'>Berlaku: 14 hari</font>",
                      ParagraphStyle("right", alignment=TA_RIGHT)),
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
    story.append(Paragraph(
        "<font size='10' color='#6B7280'>Kepada Yth,</font>", styles["Normal"]))
    story.append(Paragraph(
        f"<font size='13' color='#020818'><b>{customer_name}</b></font>", styles["Normal"]))
    if customer_phone:
        story.append(Paragraph(
            f"<font size='10' color='#6B7280'>{customer_phone}</font>", styles["Normal"]))
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
            Paragraph(
                f"<b>{item.get('name', '')}</b><br/>"
                f"<font size='8' color='#6B7280'>{item.get('desc', '')}</font>",
                styles["Normal"]),
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
        ('BACKGROUND', (0, 0), (-1, 0), primary),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
        ('TOPPADDING', (0, 0), (-1, 0), 8),
        ('ROWBACKGROUNDS', (0, 1), (-1, -2), [colors.white, light_gray]),
        ('FONTSIZE', (0, 1), (-1, -1), 9),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 6),
        ('TOPPADDING', (0, 1), (-1, -1), 6),
        ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor("#EFF6FF")),
        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, -1), (-1, -1), 11),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#E5E7EB")),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    story.append(items_table)
    story.append(Spacer(1, 0.5*cm))

    # ── Notes ──
    if notes:
        story.append(HRFlowable(width="100%", thickness=0.5, color=gray, spaceAfter=6))
        story.append(Paragraph(
            "<font size='10' color='#6B7280'><b>Catatan:</b></font>", styles["Normal"]))
        story.append(Paragraph(
            f"<font size='10' color='#6B7280'>{notes}</font>", styles["Normal"]))
        story.append(Spacer(1, 0.3*cm))

    # ── Payment Info ──
    payment = profile.get("payment", {})
    if payment:
        story.append(HRFlowable(width="100%", thickness=0.5, color=gray, spaceAfter=6))
        story.append(Paragraph(
            "<font size='10' color='#6B7280'><b>Info Pembayaran:</b></font>",
            styles["Normal"]))
        if payment.get("bank"):
            story.append(Paragraph(
                f"<font size='10' color='#6B7280'>Bank: {payment['bank']} — "
                f"A/N: {payment.get('account_name', '')} — "
                f"No: {payment.get('account_number', '')}</font>",
                styles["Normal"]))
        story.append(Spacer(1, 0.3*cm))

    # ── How to Order ──
    how_to_order = profile.get("how_to_order", "")
    if how_to_order:
        story.append(Paragraph(
            f"<font size='9' color='#6B7280'><b>Cara Order:</b> {how_to_order}</font>",
            styles["Normal"]))
        story.append(Spacer(1, 0.3*cm))

    # ── Footer ──
    story.append(HRFlowable(width="100%", thickness=0.5, color=gray, spaceAfter=6))
    story.append(Paragraph(
        f"<font size='9' color='#6B7280'>"
        f"Quotation ini dibuat otomatis oleh Orion AI • "
        f"{company_name} • "
        f"{datetime.now().strftime('%d/%m/%Y %H:%M')}"
        f"</font>",
        ParagraphStyle("center", alignment=TA_CENTER)
    ))

    doc.build(story)
    return filename


async def generate_quote_from_request(
    customer_name: str,
    customer_phone: str,
    request_text: str,
    user_id: str = "default"
) -> dict:
    """
    Generate quotation dari request text menggunakan AI — per user
    Returns: {"pdf_path": str, "items": list, "quote_number": str}
    """
    from app.services.ai_provider import call_llm

    profile = _load_profile(user_id)
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
      "unit": "pcs/bulan/paket/dll",
      "price": 0
    }}
  ],
  "notes": "catatan tambahan jika ada"
}}

Untuk harga, gunakan harga dari profil bisnis di atas.
Jika tidak ada harga yang cocok, tulis 0.
Respond HANYA dengan JSON tanpa penjelasan."""

    try:
        ai_response = await call_llm(system_prompt, request_text)
        clean = ai_response.replace('```json', '').replace('```', '').strip()
        quote_data = json.loads(clean)
    except Exception as e:
        print(f"[QUOTE AI ERROR] {e}")
        quote_data = {
            "items": [{
                "name": "Produk/Layanan",
                "desc": request_text[:50],
                "qty": 1,
                "unit": "paket",
                "price": 0
            }],
            "notes": "Harga akan dikonfirmasi lebih lanjut. Hubungi kami untuk detail."
        }

    quote_number = f"QUO-{datetime.now().strftime('%Y%m%d%H%M%S')}"

    pdf_path = generate_quote_pdf(
        customer_name=customer_name,
        customer_phone=customer_phone,
        items=quote_data.get("items", []),
        notes=quote_data.get("notes", ""),
        quote_number=quote_number,
        user_id=user_id
    )

    return {
        "pdf_path": pdf_path,
        "items": quote_data.get("items", []),
        "quote_number": quote_number,
        "notes": quote_data.get("notes", "")
    }