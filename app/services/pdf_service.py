"""
APEX PDF Quotation Service
Generate dan kirim PDF penawaran otomatis via WA
Fixed: asyncio.to_thread, ReportLab bold, temp file cleanup, price formatting
"""
import asyncio
import os
import httpx
import tempfile
from datetime import datetime

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle,
    Paragraph, Spacer
)

WA_GATEWAY_URL = os.getenv("WA_GATEWAY_URL", "https://worker-production-67d8.up.railway.app")


# ─── GENERATE PDF (sync — dipanggil via to_thread) ────────────────────────────

def _build_pdf(customer_name: str, items: list, notes: str, business_name: str) -> str:
    quote_number = f"QUO-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    date_str     = datetime.now().strftime("%d %B %Y")

    tmp      = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    pdf_path = tmp.name
    tmp.close()

    doc = SimpleDocTemplate(
        pdf_path, pagesize=A4,
        rightMargin=2*cm, leftMargin=2*cm,
        topMargin=2*cm, bottomMargin=2*cm
    )

    header_style = ParagraphStyle(
        "header", fontSize=20, fontName="Helvetica-Bold",
        textColor=colors.HexColor("#1E3A5F"), spaceAfter=4
    )
    sub_style = ParagraphStyle(
        "sub", fontSize=10, fontName="Helvetica",
        textColor=colors.HexColor("#666666"), spaceAfter=2
    )
    normal_style = ParagraphStyle(
        "normal", fontSize=10, fontName="Helvetica", spaceAfter=4
    )
    bold_style = ParagraphStyle(
        "bold", fontSize=10, fontName="Helvetica-Bold", spaceAfter=4
    )

    elements = []
    elements.append(Paragraph(business_name, header_style))
    elements.append(Paragraph(f"Nomor: {quote_number}", sub_style))
    elements.append(Paragraph(f"Tanggal: {date_str}", sub_style))
    elements.append(Spacer(1, 0.5*cm))
    elements.append(Paragraph("Kepada Yth:", normal_style))
    elements.append(Paragraph(customer_name, bold_style))
    elements.append(Spacer(1, 0.5*cm))

    # Table header
    table_data = [[
        Paragraph("No", bold_style),
        Paragraph("Item", bold_style),
        Paragraph("Qty", bold_style),
        Paragraph("Harga Satuan", bold_style),
        Paragraph("Total", bold_style),
    ]]

    total = 0
    has_price = any(item.get("price", 0) > 0 for item in items)

    for i, item in enumerate(items, 1):
        qty   = item.get("qty", 1)
        price = item.get("price", 0)
        subtotal = qty * price
        total += subtotal

        price_str    = f"Rp {price:,.0f}"    if price > 0 else "Konfirmasi"
        subtotal_str = f"Rp {subtotal:,.0f}" if price > 0 else "Konfirmasi"

        table_data.append([
            Paragraph(str(i), normal_style),
            Paragraph(item.get("name", "-"), normal_style),
            Paragraph(str(qty), normal_style),
            Paragraph(price_str, normal_style),
            Paragraph(subtotal_str, normal_style),
        ])

    total_str = f"Rp {total:,.0f}" if has_price else "Akan dikonfirmasi"
    table_data.append([
        Paragraph("", normal_style),
        Paragraph("", normal_style),
        Paragraph("", normal_style),
        Paragraph("TOTAL", bold_style),
        Paragraph(total_str, bold_style),
    ])

    table = Table(table_data, colWidths=[1*cm, 7*cm, 2*cm, 4*cm, 4*cm])
    table.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0),  colors.HexColor("#1E3A5F")),
        ("TEXTCOLOR",     (0, 0), (-1, 0),  colors.white),
        ("FONTSIZE",      (0, 0), (-1, -1), 10),
        ("ALIGN",         (0, 0), (-1, -1), "CENTER"),
        ("ALIGN",         (1, 1), (1, -1),  "LEFT"),
        ("BACKGROUND",    (0, -1), (-1, -1), colors.HexColor("#F0F4FF")),
        ("GRID",          (0, 0), (-1, -2), 0.5, colors.HexColor("#CCCCCC")),
        ("ROWBACKGROUNDS",(0, 1), (-1, -2), [colors.white, colors.HexColor("#F8F9FA")]),
        ("TOPPADDING",    (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))

    elements.append(table)
    elements.append(Spacer(1, 0.5*cm))

    if notes:
        elements.append(Paragraph(f"<i>Catatan: {notes}</i>", normal_style))

    elements.append(Spacer(1, 1*cm))
    elements.append(Paragraph("Terima kasih atas kepercayaan Anda! 🙏", normal_style))

    doc.build(elements)
    return pdf_path


# ─── SEND PDF VIA WA ──────────────────────────────────────────────────────────

async def send_pdf_via_wa(user_id: str, phone: str, pdf_path: str, customer_name: str):
    try:
        async with httpx.AsyncClient(timeout=30) as http:
            await http.post(f"{WA_GATEWAY_URL}/send-message", json={
                "user_id": user_id,
                "phone":   phone,
                "message": (
                    f"Halo {customer_name}! 😊\n\n"
                    f"Berikut quotation yang sudah kami siapkan. "
                    f"Tim kami akan segera mengkonfirmasi harga final ya! 🙏"
                )
            })

            with open(pdf_path, "rb") as f:
                await http.post(
                    f"{WA_GATEWAY_URL}/send-file",
                    files={"file": (f"Quotation-{customer_name}.pdf", f, "application/pdf")},
                    data={"user_id": user_id, "phone": phone}
                )
    finally:
        if os.path.exists(pdf_path):
            os.unlink(pdf_path)


# ─── MAIN ENTRY POINT ─────────────────────────────────────────────────────────

async def generate_and_send_quotation(
    user_id: str,
    phone: str,
    customer_name: str,
    items: list,
    notes: str = "",
    business_name: str = "Orion AI Business"
):
    try:
        pdf_path = await asyncio.to_thread(
            _build_pdf, customer_name, items, notes, business_name
        )
        await send_pdf_via_wa(user_id, phone, pdf_path, customer_name)
        print(f"[PDF] ✅ Quotation sent to {phone}")
        return {"status": "success"}

    except Exception as e:
        print(f"[PDF] ❌ Error: {e}")
        return {"status": "error", "error": str(e)}
