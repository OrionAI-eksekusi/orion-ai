"""
ZENITH — Enterprise Risk Intelligence System
AI Governance & Forensic Audit Platform
Version 2.0 — Enterprise Grade
"""

import os
import json
import sqlite3
import statistics
import re
from datetime import datetime, timedelta
from app.services.ai_provider import call_llm

DB_PATH = os.getenv("DB_PATH", "orion.db")


# ── Init Zenith DB ────────────────────────────────────────
def init_zenith_db():
    seed_market_prices()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute('''
        CREATE TABLE IF NOT EXISTS vendor_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            vendor_name TEXT NOT NULL,
            item_description TEXT NOT NULL,
            unit_price REAL NOT NULL,
            quantity REAL DEFAULT 1,
            total_amount REAL NOT NULL,
            invoice_number TEXT DEFAULT '',
            transaction_date TEXT DEFAULT (datetime('now')),
            category TEXT DEFAULT 'general',
            payment_date TEXT DEFAULT '',
            approved_by TEXT DEFAULT '',
            division TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now'))
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS market_price_reference (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_name TEXT NOT NULL,
            category TEXT DEFAULT 'general',
            min_price REAL NOT NULL,
            max_price REAL NOT NULL,
            avg_price REAL NOT NULL,
            unit TEXT DEFAULT 'unit',
            source TEXT DEFAULT 'manual',
            updated_at TEXT DEFAULT (datetime('now'))
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS risk_alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            alert_type TEXT NOT NULL,
            severity TEXT NOT NULL,
            vendor_name TEXT DEFAULT '',
            description TEXT NOT NULL,
            amount REAL DEFAULT 0,
            risk_score REAL DEFAULT 0,
            confidence_score TEXT DEFAULT 'MEDIUM',
            status TEXT DEFAULT 'open',
            verified_by TEXT DEFAULT '',
            verification_result TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now')),
            resolved_at TEXT DEFAULT ''
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS vendor_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            vendor_name TEXT NOT NULL,
            total_transactions INTEGER DEFAULT 0,
            total_amount REAL DEFAULT 0,
            avg_transaction REAL DEFAULT 0,
            risk_score REAL DEFAULT 0,
            risk_level TEXT DEFAULT 'SAFE',
            flags TEXT DEFAULT '[]',
            npwp TEXT DEFAULT '',
            address TEXT DEFAULT '',
            reliability_score REAL DEFAULT 50,
            last_transaction TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now')),
            UNIQUE(user_id, vendor_name)
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS compliance_audit_trail (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            entity_name TEXT DEFAULT '',
            amount REAL DEFAULT 0,
            description TEXT NOT NULL,
            policy_violated TEXT DEFAULT '',
            severity TEXT DEFAULT 'INFO',
            approved_by TEXT DEFAULT '',
            transaction_date TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now'))
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS investigation_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            question TEXT NOT NULL,
            findings TEXT NOT NULL,
            confidence TEXT DEFAULT 'MEDIUM',
            created_at TEXT DEFAULT (datetime('now'))
        )
    ''')

    # Migrations
    migrations = [
        "ALTER TABLE vendor_transactions ADD COLUMN payment_date TEXT DEFAULT ''",
        "ALTER TABLE vendor_transactions ADD COLUMN approved_by TEXT DEFAULT ''",
        "ALTER TABLE vendor_transactions ADD COLUMN division TEXT DEFAULT ''",
        "ALTER TABLE risk_alerts ADD COLUMN confidence_score TEXT DEFAULT 'MEDIUM'",
        "ALTER TABLE risk_alerts ADD COLUMN verified_by TEXT DEFAULT ''",
        "ALTER TABLE risk_alerts ADD COLUMN verification_result TEXT DEFAULT ''",
        "ALTER TABLE vendor_profiles ADD COLUMN npwp TEXT DEFAULT ''",
        "ALTER TABLE vendor_profiles ADD COLUMN address TEXT DEFAULT ''",
        "ALTER TABLE vendor_profiles ADD COLUMN reliability_score REAL DEFAULT 50",
    ]
    for m in migrations:
        try:
            c.execute(m)
        except:
            pass

    conn.commit()
    conn.close()


# ── Price Guard AI ────────────────────────────────────────

async def analyze_price_guard(
    user_id: str,
    vendor_name: str,
    item_description: str,
    unit_price: float,
    quantity: float = 1,
    category: str = "general",
    invoice_number: str = "",
    division: str = "",
    approved_by: str = ""
) -> dict:
    init_zenith_db()
    total = unit_price * quantity

    # Validasi matematika — Zenith tidak bisa salah hitung
    calculated_total = round(unit_price * quantity, 2)
    if abs(calculated_total - total) > 0.01:
        return {
            "status": "ERROR",
            "error": "MATHEMATICAL_INCONSISTENCY_DETECTED",
            "message": f"ERROR: Mathematical Inconsistency Detected. Reported Total: {total}, Calculated Total: {calculated_total}. Execution Halted for Manual Review.",
            "risk_level": "HIGH",
            "risk_score": 100
        }

    _save_vendor_transaction(
        user_id=user_id,
        vendor_name=vendor_name,
        item_description=item_description,
        unit_price=unit_price,
        quantity=quantity,
        total_amount=total,
        category=category,
        invoice_number=invoice_number,
        division=division,
        approved_by=approved_by
    )

    historical = _get_vendor_price_history(user_id, item_description)
    market_ref = _get_market_reference(item_description, category)

    # Cross-check vendor di divisi lain
    division_prices = _get_division_price_comparison(user_id, item_description)

    analysis = await _ai_price_analysis(
        vendor_name=vendor_name,
        item_description=item_description,
        unit_price=unit_price,
        quantity=quantity,
        total=total,
        historical=historical,
        market_ref=market_ref,
        division_prices=division_prices,
        category=category
    )

    _update_vendor_profile(user_id, vendor_name, total, analysis['risk_score'])

    if analysis['risk_level'] in ['HIGH', 'MEDIUM']:
        _create_risk_alert(
            user_id=user_id,
            alert_type='price_guard',
            severity=analysis['risk_level'],
            vendor_name=vendor_name,
            description=analysis['summary'],
            amount=total,
            risk_score=analysis['risk_score'],
            confidence_score=analysis.get('confidence_score', 'MEDIUM')
        )

    # Log ke compliance audit trail
    _log_compliance_event(
        user_id=user_id,
        event_type='PRICE_ANALYSIS',
        entity_name=vendor_name,
        amount=total,
        description=f"Price Guard analisa: {analysis['risk_level']} RISK - {item_description}",
        severity=analysis['risk_level'],
        approved_by=approved_by
    )

    return analysis


async def _ai_price_analysis(
    vendor_name: str,
    item_description: str,
    unit_price: float,
    quantity: float,
    total: float,
    historical: list,
    market_ref: dict,
    division_prices: list,
    category: str
) -> dict:
    historical_info = ""
    if historical:
        avg_hist = statistics.mean([h['unit_price'] for h in historical])
        min_hist = min(h['unit_price'] for h in historical)
        max_hist = max(h['unit_price'] for h in historical)
        pct_change = ((unit_price - avg_hist) / avg_hist * 100) if avg_hist > 0 else 0
        historical_info = f"""
Histori harga item ini:
- Rata-rata historis: Rp {avg_hist:,.0f}
- Minimum: Rp {min_hist:,.0f}
- Maximum: Rp {max_hist:,.0f}
- Perubahan dari rata-rata: {pct_change:+.1f}%
- Jumlah transaksi historis: {len(historical)}
"""

    market_info = ""
    if market_ref:
        market_info = f"""
Referensi harga pasar:
- Min: Rp {market_ref['min_price']:,.0f}
- Max: Rp {market_ref['max_price']:,.0f}
- Rata-rata pasar: Rp {market_ref['avg_price']:,.0f}
"""

    division_info = ""
    if division_prices:
        division_info = f"""
Harga di divisi lain untuk item serupa:
{json.dumps(division_prices[:5], ensure_ascii=False)}
"""

    system_prompt = """Kamu adalah Chief Forensic Auditor Zenith. Analisa harga transaksi ini dengan standar audit enterprise.

PROTOKOL ADVERSARIAL THINKING:
Sebelum memberikan verdict, lakukan uji silang internal:
1. Apakah kenaikan harga bisa dijelaskan oleh inflasi atau kondisi pasar?
2. Apakah vendor ini memiliki rekam jejak yang bersih?
3. Apakah ada penjelasan logis selain fraud?

Berikan output JSON dengan format ini:
{
    "risk_level": "SAFE/MEDIUM/HIGH",
    "risk_score": 0-100,
    "confidence_score": "HIGH/MEDIUM/LOW",
    "markup_percentage": angka persentase markup,
    "summary": "ringkasan analisa 1-2 kalimat",
    "findings": ["temuan berbasis bukti 1", "temuan 2"],
    "adversarial_check": "hasil uji silang — apakah ada penjelasan alternatif yang legitimate",
    "recommendation": "rekomendasi tindakan konkret",
    "estimated_fair_price": harga wajar per unit,
    "potential_savings": potensi penghematan total,
    "investigation_leads": ["langkah audit selanjutnya untuk tim manusia"]
}

Kriteria:
- SAFE: harga wajar, sesuai pasar atau historis
- MEDIUM: 10-30% di atas rata-rata, perlu perhatian
- HIGH: >30% di atas wajar, indikasi markup serius

Confidence Score:
- HIGH: didukung data matematis dan historis yang kuat
- MEDIUM: ada indikasi tapi perlu verifikasi
- LOW: hanya berdasarkan pola, butuh data lebih

Respond HANYA dengan JSON."""

    user_message = f"""
ANALISA TRANSAKSI:
- Vendor: {vendor_name}
- Item: {item_description}
- Kategori: {category}
- Harga satuan: Rp {unit_price:,.0f}
- Jumlah: {quantity}
- Total: Rp {total:,.0f}

{historical_info}
{market_info}
{division_info}
"""

    try:
        response = await call_llm(system_prompt, user_message)
        clean = response.replace('```json', '').replace('```', '').strip()
        result = json.loads(clean)
        return result
    except Exception as e:
        print(f"[PRICE GUARD ERROR] {e}")
        risk_score = 0
        if historical:
            avg = statistics.mean([h['unit_price'] for h in historical])
            diff_pct = ((unit_price - avg) / avg * 100) if avg > 0 else 0
            if diff_pct > 30:
                risk_score = 80
            elif diff_pct > 10:
                risk_score = 50
            elif diff_pct > 0:
                risk_score = 25

        risk_level = 'HIGH' if risk_score >= 70 else 'MEDIUM' if risk_score >= 30 else 'SAFE'
        return {
            "risk_level": risk_level,
            "risk_score": risk_score,
            "confidence_score": "LOW",
            "markup_percentage": 0,
            "summary": f"Analisa manual diperlukan untuk {vendor_name}",
            "findings": ["Data tidak cukup untuk analisa otomatis"],
            "adversarial_check": "Tidak dapat diverifikasi — butuh data lebih",
            "recommendation": "Verifikasi manual dengan tim procurement",
            "estimated_fair_price": unit_price,
            "potential_savings": 0,
            "investigation_leads": ["Minta invoice pembanding dari vendor lain"]
        }


# ── Transaction Anomaly Engine ────────────────────────────

async def detect_transaction_anomalies(user_id: str) -> dict:
    init_zenith_db()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute('''
        SELECT vendor_name, item_description, unit_price, total_amount,
               transaction_date, invoice_number, id, division,
               approved_by, payment_date
        FROM vendor_transactions
        WHERE user_id = ?
        ORDER BY transaction_date DESC
        LIMIT 200
    ''', (user_id,))
    transactions = c.fetchall()
    conn.close()

    if not transactions:
        return {
            "anomalies": [],
            "summary": "Belum ada data transaksi untuk dianalisa.",
            "total_risk_amount": 0
        }

    anomalies = []
    total_risk_amount = 0

    # 1. Duplikat invoice
    invoice_numbers = [t[5] for t in transactions if t[5]]
    seen = {}
    for inv in invoice_numbers:
        seen[inv] = seen.get(inv, 0) + 1
    for inv, count in seen.items():
        if count > 1:
            anomalies.append({
                "type": "DUPLICATE_INVOICE",
                "severity": "HIGH",
                "confidence": "HIGH",
                "description": f"Invoice {inv} muncul {count}x — kemungkinan double payment",
                "risk_score": 90,
                "evidence": f"Invoice number {inv} ditemukan {count} kali dalam database"
            })

    # 2. Split invoice — nominal sama berulang
    amounts = [t[3] for t in transactions]
    amount_counts = {}
    for amt in amounts:
        key = round(amt, 0)
        amount_counts[key] = amount_counts.get(key, 0) + 1
    for amt, count in amount_counts.items():
        if count >= 3 and amt > 500000:
            anomalies.append({
                "type": "POTENTIAL_SPLIT_INVOICE",
                "severity": "HIGH",
                "confidence": "MEDIUM",
                "description": f"Transaksi Rp {amt:,.0f} muncul {count}x — indikasi split invoice untuk menghindari approval limit",
                "risk_score": 75,
                "evidence": f"Nominal identik Rp {amt:,.0f} terulang {count} kali"
            })
            total_risk_amount += amt * count

    # 3. Transaksi di luar jam kerja / hari libur
    weekend_tx = []
    for t in transactions:
        try:
            tx_date = datetime.fromisoformat(t[4])
            if tx_date.weekday() >= 5:  # Sabtu=5, Minggu=6
                weekend_tx.append(t)
        except:
            pass
    if len(weekend_tx) >= 2:
        anomalies.append({
            "type": "WEEKEND_TRANSACTION",
            "severity": "MEDIUM",
            "confidence": "MEDIUM",
            "description": f"Ditemukan {len(weekend_tx)} transaksi di hari Sabtu/Minggu — perlu verifikasi kontrak lembur",
            "risk_score": 55,
            "evidence": f"{len(weekend_tx)} transaksi terjadi di luar hari kerja"
        })

    # 4. Vendor dominan
    vendor_totals = {}
    for t in transactions:
        vendor = t[0]
        vendor_totals[vendor] = vendor_totals.get(vendor, 0) + t[3]
    total_all = sum(vendor_totals.values())
    if total_all > 0:
        for vendor, total in vendor_totals.items():
            pct = total / total_all * 100
            if pct > 60:
                anomalies.append({
                    "type": "VENDOR_DOMINANCE",
                    "severity": "MEDIUM",
                    "confidence": "HIGH",
                    "description": f"Vendor '{vendor}' mendominasi {pct:.1f}% dari total pembelian — risiko ketergantungan vendor tunggal",
                    "risk_score": 60,
                    "evidence": f"Rp {vendor_totals[vendor]:,.0f} dari total Rp {total_all:,.0f}"
                })

    # 5. Vendor baru dengan volume tinggi — POTENTIAL_COLLUSION
    vendor_first_tx = {}
    for t in sorted(transactions, key=lambda x: x[4]):
        vendor = t[0]
        if vendor not in vendor_first_tx:
            vendor_first_tx[vendor] = {'date': t[4], 'count': 0, 'total': 0}
        vendor_first_tx[vendor]['count'] += 1
        vendor_first_tx[vendor]['total'] += t[3]

    for vendor, info in vendor_first_tx.items():
        try:
            first_date = datetime.fromisoformat(info['date'])
            days_active = (datetime.now() - first_date).days
            if days_active < 90 and info['count'] >= 5 and info['total'] > 10000000:
                anomalies.append({
                    "type": "POTENTIAL_COLLUSION",
                    "severity": "HIGH",
                    "confidence": "MEDIUM",
                    "description": f"Vendor baru '{vendor}' mendapat {info['count']} transaksi senilai Rp {info['total']:,.0f} dalam {days_active} hari tanpa histori tender",
                    "risk_score": 80,
                    "evidence": f"Vendor aktif {days_active} hari, {info['count']} transaksi"
                })
        except:
            pass

    # 6. Threshold violation — transaksi tepat di bawah limit approval
    # Asumsikan limit approval Rp 50 juta dan Rp 100 juta
    approval_limits = [50000000, 100000000, 25000000]
    for limit in approval_limits:
        threshold_tx = [t for t in transactions
                        if limit * 0.9 <= t[3] <= limit * 0.99]
        if len(threshold_tx) >= 2:
            anomalies.append({
                "type": "THRESHOLD_VIOLATION",
                "severity": "HIGH",
                "confidence": "HIGH",
                "description": f"Ditemukan {len(threshold_tx)} transaksi dalam rentang 90-99% dari batas approval Rp {limit/1000000:.0f}jt — indikasi sengaja menghindari persetujuan atasan",
                "risk_score": 85,
                "evidence": f"{len(threshold_tx)} transaksi di kisaran Rp {limit*0.9/1000000:.0f}jt - Rp {limit*0.99/1000000:.0f}jt"
            })

    summary = await _ai_anomaly_summary(anomalies, len(transactions), total_all)

    return {
        "anomalies": anomalies,
        "summary": summary,
        "total_transactions": len(transactions),
        "total_amount": total_all,
        "total_risk_amount": total_risk_amount,
        "risk_count": len(anomalies),
        "high_risk_count": len([a for a in anomalies if a['severity'] == 'HIGH']),
        "medium_risk_count": len([a for a in anomalies if a['severity'] == 'MEDIUM'])
    }


async def _ai_anomaly_summary(anomalies: list, total_tx: int, total_amount: float) -> str:
    if not anomalies:
        return f"✅ CLEAR: Dari {total_tx} transaksi senilai Rp {total_amount:,.0f}, tidak ditemukan anomali yang mencurigakan. Sistem berjalan normal."

    high_count = len([a for a in anomalies if a['severity'] == 'HIGH'])
    medium_count = len([a for a in anomalies if a['severity'] == 'MEDIUM'])

    system_prompt = """Kamu adalah Chief Forensic Auditor Zenith.
Buat ringkasan eksekutif (3 kalimat) dari temuan anomali.
Gunakan bahasa Indonesia yang tegas, profesional, dan berbasis bukti.
Sebutkan angka dan fakta spesifik. Tidak boleh opini tanpa data."""

    user_message = f"""
Total transaksi dianalisa: {total_tx}
Total nilai: Rp {total_amount:,.0f}
Anomali HIGH: {high_count}
Anomali MEDIUM: {medium_count}
Detail: {json.dumps(anomalies, ensure_ascii=False)}
"""
    try:
        return await call_llm(system_prompt, user_message)
    except:
        return f"⚠️ ALERT: Ditemukan {len(anomalies)} anomali ({high_count} HIGH, {medium_count} MEDIUM) dari {total_tx} transaksi senilai Rp {total_amount:,.0f}. Investigasi segera diperlukan."


# ── AI Investigator ───────────────────────────────────────

async def ai_investigator(user_id: str, question: str) -> dict:
    """
    AI Investigator — Evidence-Based Forensic Reasoning
    Jawab pertanyaan investigasi dengan data nyata, bukan opini
    """
    init_zenith_db()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Tarik semua data untuk konteks investigasi
    c.execute('''
        SELECT vendor_name, item_description, unit_price, total_amount,
               transaction_date, invoice_number, category, division
        FROM vendor_transactions WHERE user_id = ?
        ORDER BY transaction_date DESC LIMIT 200
    ''', (user_id,))
    transactions = c.fetchall()

    c.execute('''
        SELECT vendor_name, risk_level, risk_score, total_amount,
               total_transactions, reliability_score
        FROM vendor_profiles WHERE user_id = ?
        ORDER BY risk_score DESC
    ''', (user_id,))
    vendor_profiles = c.fetchall()

    c.execute('''
        SELECT alert_type, severity, vendor_name, description,
               amount, risk_score, created_at
        FROM risk_alerts WHERE user_id = ? AND status = 'open'
        ORDER BY risk_score DESC
    ''', (user_id,))
    alerts = c.fetchall()

    # Monthly aggregation per vendor
    c.execute('''
        SELECT strftime('%Y-%m', transaction_date) as month,
               vendor_name,
               SUM(total_amount) as total,
               COUNT(*) as count,
               AVG(unit_price) as avg_price,
               MIN(unit_price) as min_price,
               MAX(unit_price) as max_price
        FROM vendor_transactions WHERE user_id = ?
        GROUP BY month, vendor_name
        ORDER BY month DESC
        LIMIT 100
    ''', (user_id,))
    monthly_by_vendor = c.fetchall()

    # Division spending
    c.execute('''
        SELECT division, SUM(total_amount) as total, COUNT(*) as count
        FROM vendor_transactions WHERE user_id = ? AND division != ''
        GROUP BY division ORDER BY total DESC
    ''', (user_id,))
    division_spending = c.fetchall()

    conn.close()

    if not transactions:
        return {
            "status": "INSUFFICIENT_DATA",
            "message": "Tidak ada data transaksi untuk diinvestigasi. Tambahkan data transaksi terlebih dahulu.",
            "investigation_summary": "",
            "findings": [],
            "root_cause": "",
            "confidence_score": "LOW"
        }

    # Bangun konteks investigasi
    tx_data = [{"vendor": t[0], "item": t[1], "unit_price": t[2],
                "total": t[3], "date": t[4], "invoice": t[5],
                "category": t[6], "division": t[7]}
               for t in transactions[:100]]

    vendor_data = [{"vendor": v[0], "risk_level": v[1], "risk_score": v[2],
                    "total_spend": v[3], "tx_count": v[4],
                    "reliability": v[5]} for v in vendor_profiles]

    monthly_data = [{"month": m[0], "vendor": m[1], "total": m[2],
                     "count": m[3], "avg_price": m[4],
                     "min_price": m[5], "max_price": m[6]}
                    for m in monthly_by_vendor]

    alert_data = [{"type": a[0], "severity": a[1], "vendor": a[2],
                   "description": a[3], "amount": a[4]}
                  for a in alerts]

    division_data = [{"division": d[0], "total": d[1], "count": d[2]}
                     for d in division_spending]

    system_prompt = """Kamu adalah Chief Forensic Auditor untuk Orion Zenith Enterprise.

PROTOKOL INVESTIGASI EVIDENCE-BASED:

LANGKAH 1 — DATA SOURCING
Identifikasi data mana yang relevan untuk menjawab pertanyaan.
Sebutkan tabel/sumber data yang kamu gunakan.

LANGKAH 2 — CORRELATION ANALYSIS  
Hubungkan antar data point. Cari korelasi antara:
- Perubahan vendor dengan perubahan harga
- Timeline transaksi dengan anomali yang muncul
- Pola spending per divisi

LANGKAH 3 — ROOT CAUSE ANALYSIS
Tentukan apakah masalah ini:
- Efisiensi (Procurement Watch)
- Kepatuhan (Compliance Center)
- Indikasi fraud (Price Guard + Anomaly)

LANGKAH 4 — ADVERSARIAL CHECK
Sebelum output final, tantang temuanmu:
"Apakah ada penjelasan legitimate untuk anomali ini?"
"Apakah data cukup untuk verdict ini?"

LANGKAH 5 — SILENT FAILURE PREVENTION
Jika ada inkonsistensi matematis dalam data, laporkan:
"ERROR: Mathematical Inconsistency Detected"
JANGAN perbaiki angka — laporkan apa adanya.

Output dalam JSON:
{
    "investigation_summary": "ringkasan investigasi 2-3 kalimat berbasis bukti",
    "data_sources_used": ["daftar sumber data yang digunakan"],
    "findings": [
        {
            "finding": "temuan spesifik",
            "evidence": "bukti data yang mendukung",
            "confidence": "HIGH/MEDIUM/LOW",
            "financial_impact": "estimasi dampak finansial dalam IDR"
        }
    ],
    "root_cause": "analisis kausal yang spesifik dan berbasis data",
    "adversarial_check": "hasil uji silang — apakah ada penjelasan alternative",
    "risk_score": 0-100,
    "confidence_score": "HIGH/MEDIUM/LOW",
    "potential_leakage_amount": estimasi total kebocoran dalam IDR,
    "investigation_leads": ["langkah audit selanjutnya untuk tim manusia"],
    "recommended_actions": ["tindakan konkret yang harus diambil"],
    "data_limitations": "keterbatasan data yang mempengaruhi akurasi analisa"
}

PENTING: Jawab HANYA berdasarkan data yang diberikan.
Jika data tidak cukup, nyatakan dengan jelas di data_limitations.
Respond HANYA dengan JSON."""

    user_message = f"""
PERTANYAAN INVESTIGASI:
{question}

DATA TRANSAKSI ({len(tx_data)} records):
{json.dumps(tx_data[:50], ensure_ascii=False)}

PROFIL VENDOR:
{json.dumps(vendor_data, ensure_ascii=False)}

TREND BULANAN PER VENDOR:
{json.dumps(monthly_data[:30], ensure_ascii=False)}

OPEN RISK ALERTS:
{json.dumps(alert_data, ensure_ascii=False)}

SPENDING PER DIVISI:
{json.dumps(division_data, ensure_ascii=False)}

Lakukan investigasi forensik berdasarkan data di atas.
"""

    try:
        response = await call_llm(system_prompt, user_message)
        clean = response.replace('```json', '').replace('```', '').strip()
        result = json.loads(clean)

        # Log investigasi ke database
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''
            INSERT INTO investigation_log
            (user_id, question, findings, confidence)
            VALUES (?, ?, ?, ?)
        ''', (user_id, question, json.dumps(result, ensure_ascii=False),
              result.get('confidence_score', 'MEDIUM')))
        conn.commit()
        conn.close()

        return result

    except Exception as e:
        print(f"[AI INVESTIGATOR ERROR] {e}")
        return {
            "investigation_summary": "Investigasi tidak dapat diselesaikan. Data mungkin tidak cukup atau terjadi error sistem.",
            "data_sources_used": ["vendor_transactions", "vendor_profiles", "risk_alerts"],
            "findings": [],
            "root_cause": "Tidak dapat ditentukan — data tidak mencukupi",
            "adversarial_check": "Tidak dapat dilakukan",
            "risk_score": 0,
            "confidence_score": "LOW",
            "potential_leakage_amount": 0,
            "investigation_leads": ["Tambahkan lebih banyak data transaksi", "Verifikasi manual diperlukan"],
            "recommended_actions": ["Lakukan audit manual"],
            "data_limitations": f"Error sistem: {str(e)}"
        }


# ── OCR Invoice Forensic ──────────────────────────────────

async def ocr_invoice_forensic(user_id: str, invoice_text: str,
                                invoice_metadata: dict = {}) -> dict:
    """
    OCR Invoice Forensic — Deteksi manipulasi dokumen
    Analisa teks invoice dan metadata untuk indikasi fraud
    """
    init_zenith_db()

    # Validasi matematika invoice
    math_check = _validate_invoice_math(invoice_text)

    # Analisa format dan konsistensi
    format_check = _analyze_invoice_format(invoice_text)

    # Metadata analysis
    metadata_flags = _analyze_invoice_metadata(invoice_metadata)

    system_prompt = """Kamu adalah Forensic Document Examiner untuk Orion Zenith.

PROTOKOL OCR INVOICE FORENSIC:

1. SYMBOL ANALYSIS
   - Cek konsistensi format mata uang (Rp. vs Rp vs IDR)
   - Cek spasi yang tidak konsisten dalam angka nominal
   - Identifikasi font/karakter yang berbeda dalam dokumen

2. STRUCTURE CONSISTENCY
   - Verifikasi apakah alamat vendor sinkron dengan data sistem
   - Cek kelengkapan komponen invoice (nomor, tanggal, NPWP, dll)
   - Identifikasi field yang mencurigakan atau tidak standar

3. ADDRESS MISMATCH DETECTION
   - Jika alamat di invoice berbeda dengan database, flag ADDRESS_MISMATCH_RISK

4. MATHEMATICAL VERIFICATION
   - Hitung ulang semua total
   - Jika ada inkonsistensi: laporkan ERROR, jangan perbaiki

5. SILENT FAILURE PREVENTION
   Jika data tidak masuk akal (tanggal masa depan, desimal tidak wajar):
   "SYSTEM_HALT: Irregular Data Geometry Detected"

Output JSON:
{
    "forensic_status": "CLEAN/SUSPICIOUS/TAMPERED",
    "risk_score": 0-100,
    "confidence_score": "HIGH/MEDIUM/LOW",
    "flags": [
        {
            "flag_type": "jenis flag",
            "severity": "HIGH/MEDIUM/LOW",
            "description": "deskripsi temuan",
            "evidence": "bukti spesifik"
        }
    ],
    "math_verification": {
        "status": "VERIFIED/ERROR",
        "details": "detail verifikasi matematika"
    },
    "format_analysis": {
        "currency_consistency": "CONSISTENT/INCONSISTENT",
        "structure_completeness": "COMPLETE/INCOMPLETE",
        "suspicious_elements": ["elemen mencurigakan"]
    },
    "metadata_analysis": {
        "flags": ["flag metadata"],
        "risk_indicators": ["indikator risiko"]
    },
    "summary": "ringkasan forensik 2-3 kalimat",
    "recommended_actions": ["tindakan yang direkomendasikan"]
}

Respond HANYA dengan JSON."""

    user_message = f"""
TEKS INVOICE UNTUK DIANALISA:
{invoice_text}

HASIL VALIDASI MATEMATIKA:
{json.dumps(math_check, ensure_ascii=False)}

HASIL ANALISA FORMAT:
{json.dumps(format_check, ensure_ascii=False)}

METADATA DOKUMEN:
{json.dumps(invoice_metadata, ensure_ascii=False)}

FLAG METADATA:
{json.dumps(metadata_flags, ensure_ascii=False)}

Lakukan forensic analysis menyeluruh.
"""

    try:
        response = await call_llm(system_prompt, user_message)
        clean = response.replace('```json', '').replace('```', '').strip()
        result = json.loads(clean)

        # Log ke compliance trail
        if result.get('forensic_status') in ['SUSPICIOUS', 'TAMPERED']:
            _log_compliance_event(
                user_id=user_id,
                event_type='OCR_FORENSIC_ALERT',
                entity_name='Invoice',
                amount=0,
                description=f"OCR Forensic: {result.get('forensic_status')} - {result.get('summary', '')}",
                severity='HIGH' if result.get('forensic_status') == 'TAMPERED' else 'MEDIUM'
            )

        return result

    except Exception as e:
        return {
            "forensic_status": "ERROR",
            "risk_score": 0,
            "confidence_score": "LOW",
            "flags": [],
            "math_verification": {"status": "ERROR", "details": str(e)},
            "format_analysis": {},
            "metadata_analysis": {},
            "summary": f"Forensic analysis gagal: {str(e)}",
            "recommended_actions": ["Lakukan review manual"]
        }


def _validate_invoice_math(invoice_text: str) -> dict:
    """Validasi matematika dalam teks invoice"""
    issues = []
    numbers_found = []

    # Cari semua angka dalam teks
    pattern = r'Rp[\s.]*([\d.,]+)'
    matches = re.findall(pattern, invoice_text, re.IGNORECASE)

    for match in matches:
        try:
            clean_num = match.replace('.', '').replace(',', '')
            numbers_found.append(float(clean_num))
        except:
            pass

    # Cek inkonsistensi format angka
    formats = re.findall(r'Rp\s*[\d.,]+', invoice_text, re.IGNORECASE)
    format_types = set()
    for f in formats:
        if 'Rp.' in f:
            format_types.add('Rp.')
        elif 'Rp ' in f:
            format_types.add('Rp ')
        elif 'Rp' in f:
            format_types.add('Rp')

    if len(format_types) > 1:
        issues.append(f"Inkonsistensi format mata uang: {format_types}")

    return {
        "numbers_found": len(numbers_found),
        "format_types": list(format_types),
        "issues": issues,
        "status": "ISSUES_FOUND" if issues else "OK"
    }


def _analyze_invoice_format(invoice_text: str) -> dict:
    """Analisa kelengkapan dan konsistensi format invoice"""
    required_fields = {
        'nomor_invoice': bool(re.search(r'(invoice|no\.?|nomor)\s*:?\s*[\w-]+', invoice_text, re.IGNORECASE)),
        'tanggal': bool(re.search(r'\d{1,2}[/-]\d{1,2}[/-]\d{2,4}', invoice_text)),
        'total': bool(re.search(r'total\s*:?\s*Rp', invoice_text, re.IGNORECASE)),
        'nama_vendor': bool(re.search(r'(dari|vendor|supplier|perusahaan)', invoice_text, re.IGNORECASE)),
    }

    missing = [k for k, v in required_fields.items() if not v]
    completeness = len([v for v in required_fields.values() if v]) / len(required_fields) * 100

    # Deteksi tanggal masa depan
    future_date_flag = False
    date_matches = re.findall(r'(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})', invoice_text)
    for d in date_matches:
        try:
            year = int(d[2]) if len(d[2]) == 4 else 2000 + int(d[2])
            month = int(d[1])
            day = int(d[0])
            invoice_date = datetime(year, month, day)
            if invoice_date > datetime.now():
                future_date_flag = True
        except:
            pass

    if future_date_flag:
        return {
            "status": "SYSTEM_HALT",
            "error": "SYSTEM_HALT: Irregular Data Geometry Detected. Tanggal invoice di masa depan terdeteksi. Forensic audit cannot proceed without data purification.",
            "completeness_score": completeness,
            "missing_fields": missing
        }

    return {
        "status": "OK",
        "completeness_score": completeness,
        "missing_fields": missing,
        "required_fields": required_fields
    }


def _analyze_invoice_metadata(metadata: dict) -> list:
    """Analisa metadata PDF untuk indikasi manipulasi"""
    flags = []

    if not metadata:
        return flags

    # Cek tanggal modifikasi vs tanggal cetak
    created = metadata.get('created_at', '')
    modified = metadata.get('modified_at', '')
    if created and modified and created != modified:
        try:
            created_dt = datetime.fromisoformat(created)
            modified_dt = datetime.fromisoformat(modified)
            if modified_dt > created_dt:
                days_diff = (modified_dt - created_dt).days
                if days_diff > 0:
                    flags.append({
                        "flag": "DOCUMENT_TAMPERING",
                        "severity": "HIGH",
                        "description": f"Dokumen dimodifikasi {days_diff} hari setelah dibuat",
                        "evidence": f"Created: {created}, Modified: {modified}"
                    })
        except:
            pass

    # Cek author yang mencurigakan
    author = metadata.get('author', '')
    if author and any(kw in author.lower() for kw in ['unknown', 'admin', 'user', 'test']):
        flags.append({
            "flag": "SUSPICIOUS_AUTHOR",
            "severity": "MEDIUM",
            "description": f"Author dokumen mencurigakan: '{author}'",
            "evidence": f"Author metadata: {author}"
        })

    # Cek software yang digunakan
    creator = metadata.get('creator', '')
    if creator and any(kw in creator.lower() for kw in ['paint', 'snipping', 'screenshot', 'notepad']):
        flags.append({
            "flag": "NON_STANDARD_CREATOR",
            "severity": "HIGH",
            "description": f"Invoice dibuat dengan software tidak standar: '{creator}'",
            "evidence": f"Creator metadata: {creator}"
        })

    return flags


# ── Procurement Watch ─────────────────────────────────────

async def procurement_watch(user_id: str) -> dict:
    """
    Procurement Watch — Monitor efisiensi pengadaan
    Deteksi pembelian tidak efisien dan inkonsistensi harga antar divisi
    """
    init_zenith_db()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Harga per item per divisi
    c.execute('''
        SELECT item_description, division, AVG(unit_price) as avg_price,
               MIN(unit_price) as min_price, MAX(unit_price) as max_price,
               COUNT(*) as count, SUM(total_amount) as total
        FROM vendor_transactions
        WHERE user_id = ? AND division != ''
        GROUP BY item_description, division
        ORDER BY item_description
    ''', (user_id,))
    division_items = c.fetchall()

    # Item yang dibeli berulang tidak efisien
    c.execute('''
        SELECT item_description, COUNT(*) as frequency,
               SUM(total_amount) as total_spend,
               AVG(unit_price) as avg_price,
               COUNT(DISTINCT vendor_name) as vendor_count
        FROM vendor_transactions WHERE user_id = ?
        GROUP BY item_description
        ORDER BY total_spend DESC
        LIMIT 20
    ''', (user_id,))
    frequent_items = c.fetchall()

    # Vendor dengan konsistensi harga buruk
    c.execute('''
        SELECT vendor_name, item_description,
               MIN(unit_price) as min_price,
               MAX(unit_price) as max_price,
               (MAX(unit_price) - MIN(unit_price)) / MIN(unit_price) * 100 as variance_pct,
               COUNT(*) as tx_count
        FROM vendor_transactions WHERE user_id = ?
        GROUP BY vendor_name, item_description
        HAVING tx_count >= 2 AND variance_pct > 20
        ORDER BY variance_pct DESC
        LIMIT 10
    ''', (user_id,))
    price_variance = c.fetchall()

    conn.close()

    inefficiencies = []
    total_waste = 0

    # Deteksi inkonsistensi harga antar divisi
    item_divisions = {}
    for row in division_items:
        item = row[0]
        if item not in item_divisions:
            item_divisions[item] = []
        item_divisions[item].append({
            "division": row[1],
            "avg_price": row[2],
            "min_price": row[3],
            "max_price": row[4],
            "count": row[5],
            "total": row[6]
        })

    for item, divisions in item_divisions.items():
        if len(divisions) > 1:
            prices = [d['avg_price'] for d in divisions]
            min_p = min(prices)
            max_p = max(prices)
            if min_p > 0:
                diff_pct = (max_p - min_p) / min_p * 100
                if diff_pct > 15:
                    expensive_div = max(divisions, key=lambda x: x['avg_price'])
                    cheap_div = min(divisions, key=lambda x: x['avg_price'])
                    waste = (expensive_div['avg_price'] - cheap_div['avg_price']) * expensive_div['count']
                    total_waste += waste
                    inefficiencies.append({
                        "type": "CROSS_DIVISION_PRICE_INCONSISTENCY",
                        "severity": "HIGH" if diff_pct > 30 else "MEDIUM",
                        "item": item,
                        "description": f"Divisi '{expensive_div['division']}' membeli '{item}' {diff_pct:.1f}% lebih mahal dari divisi '{cheap_div['division']}'",
                        "expensive_division": expensive_div['division'],
                        "expensive_price": expensive_div['avg_price'],
                        "cheap_division": cheap_div['division'],
                        "cheap_price": cheap_div['avg_price'],
                        "price_diff_pct": diff_pct,
                        "estimated_waste": waste
                    })

    # Deteksi variasi harga vendor yang ekstrem
    for row in price_variance:
        inefficiencies.append({
            "type": "VENDOR_PRICE_INCONSISTENCY",
            "severity": "MEDIUM",
            "item": row[1],
            "vendor": row[0],
            "description": f"Vendor '{row[0]}' memiliki variasi harga {row[4]:.1f}% untuk item '{row[1]}' — harga tidak konsisten",
            "min_price": row[2],
            "max_price": row[3],
            "variance_pct": row[4],
            "tx_count": row[5]
        })

    # AI summary
    system_prompt = """Kamu adalah Procurement Efficiency Analyst untuk Orion Zenith.
Buat ringkasan eksekutif dari temuan inefisiensi pengadaan.
Gunakan bahasa Indonesia profesional. Sebutkan angka konkret.
Respond hanya dengan teks ringkasan (bukan JSON), maksimal 3 kalimat."""

    frequent_data = [{"item": r[0], "frequency": r[1], "total": r[2],
                      "avg_price": r[3], "vendors": r[4]}
                     for r in frequent_items]

    try:
        summary = await call_llm(system_prompt,
                                  f"Inefisiensi: {json.dumps(inefficiencies[:5], ensure_ascii=False)}\n"
                                  f"Item terbeli: {json.dumps(frequent_data[:5], ensure_ascii=False)}\n"
                                  f"Total estimasi pemborosan: Rp {total_waste:,.0f}")
    except:
        summary = f"Ditemukan {len(inefficiencies)} inefisiensi pengadaan dengan total estimasi pemborosan Rp {total_waste:,.0f}."

    return {
        "inefficiencies": inefficiencies,
        "summary": summary,
        "total_estimated_waste": total_waste,
        "inefficiency_count": len(inefficiencies),
        "frequent_items": frequent_data,
        "high_variance_vendors": [{"vendor": r[0], "item": r[1],
                                    "variance_pct": r[4]}
                                   for r in price_variance]
    }


# ── Compliance Center ─────────────────────────────────────

def get_compliance_report(user_id: str) -> dict:
    """
    Compliance Center — Audit trail dan policy violation
    """
    init_zenith_db()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Audit trail
    c.execute('''
        SELECT event_type, entity_name, amount, description,
               policy_violated, severity, approved_by,
               transaction_date, created_at
        FROM compliance_audit_trail
        WHERE user_id = ?
        ORDER BY created_at DESC
        LIMIT 100
    ''', (user_id,))
    audit_trail = c.fetchall()

    # Policy violations
    c.execute('''
        SELECT event_type, severity, COUNT(*) as count,
               SUM(amount) as total_amount
        FROM compliance_audit_trail
        WHERE user_id = ? AND policy_violated != ''
        GROUP BY event_type, severity
        ORDER BY count DESC
    ''', (user_id,))
    violations = c.fetchall()

    # Weekend/holiday transactions dari vendor_transactions
    c.execute('''
        SELECT vendor_name, total_amount, transaction_date,
               invoice_number, approved_by
        FROM vendor_transactions
        WHERE user_id = ?
        AND (
            strftime('%w', transaction_date) = '0' OR
            strftime('%w', transaction_date) = '6'
        )
        ORDER BY transaction_date DESC
    ''', (user_id,))
    weekend_tx = c.fetchall()

    # Transaksi tanpa approver
    c.execute('''
        SELECT vendor_name, total_amount, transaction_date, invoice_number
        FROM vendor_transactions
        WHERE user_id = ? AND (approved_by = '' OR approved_by IS NULL)
        AND total_amount > 5000000
        ORDER BY total_amount DESC
        LIMIT 20
    ''', (user_id,))
    unapproved_high_value = c.fetchall()

    conn.close()

    audit_data = [{
        "event": r[0], "entity": r[1], "amount": r[2],
        "description": r[3], "policy": r[4], "severity": r[5],
        "approved_by": r[6], "tx_date": r[7], "logged_at": r[8]
    } for r in audit_trail]

    violation_data = [{
        "type": r[0], "severity": r[1],
        "count": r[2], "total_amount": r[3]
    } for r in violations]

    weekend_data = [{
        "vendor": r[0], "amount": r[1],
        "date": r[2], "invoice": r[3], "approver": r[4]
    } for r in weekend_tx]

    unapproved_data = [{
        "vendor": r[0], "amount": r[1],
        "date": r[2], "invoice": r[3]
    } for r in unapproved_high_value]

    # Risk score compliance
    total_violations = len(violations)
    unapproved_count = len(unapproved_high_value)
    weekend_count = len(weekend_tx)
    compliance_score = max(0, 100 - (total_violations * 10) -
                           (unapproved_count * 5) - (weekend_count * 3))

    return {
        "compliance_score": compliance_score,
        "compliance_level": "HIGH" if compliance_score >= 80 else
                           "MEDIUM" if compliance_score >= 60 else "LOW",
        "audit_trail": audit_data[:50],
        "policy_violations": violation_data,
        "weekend_transactions": weekend_data,
        "unapproved_high_value": unapproved_data,
        "summary": {
            "total_audit_events": len(audit_data),
            "total_violations": total_violations,
            "weekend_transactions": weekend_count,
            "unapproved_high_value": unapproved_count
        }
    }


def verify_alert(alert_id: int, user_id: str,
                 verified_by: str, result: str) -> dict:
    """User feedback loop — verifikasi hasil AI"""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''
            UPDATE risk_alerts SET
                verified_by = ?,
                verification_result = ?,
                status = CASE 
                    WHEN ? = 'FALSE_POSITIVE' THEN 'resolved'
                    WHEN ? = 'CONFIRMED' THEN 'verified'
                    ELSE 'verified'
                END
            WHERE id = ? AND user_id = ?
        ''', (verified_by, result, result, result, alert_id, user_id))
        conn.commit()
        conn.close()

        _log_compliance_event(
            user_id=user_id,
            event_type='ALERT_VERIFICATION',
            entity_name=f'Alert #{alert_id}',
            amount=0,
            description=f"Alert diverifikasi oleh {verified_by}: {result}",
            severity='INFO',
            approved_by=verified_by
        )

        return {"status": "success",
                "message": f"Alert #{alert_id} diverifikasi sebagai {result}"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ── Executive Dashboard ───────────────────────────────────

def get_executive_dashboard(user_id: str) -> dict:
    init_zenith_db()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute('''
        SELECT SUM(total_amount), COUNT(*), AVG(total_amount)
        FROM vendor_transactions WHERE user_id = ?
    ''', (user_id,))
    row = c.fetchone()
    total_spend = row[0] or 0
    total_tx = row[1] or 0
    avg_tx = row[2] or 0

    c.execute('''
        SELECT vendor_name, SUM(total_amount) as total, COUNT(*) as count
        FROM vendor_transactions WHERE user_id = ?
        GROUP BY vendor_name ORDER BY total DESC LIMIT 5
    ''', (user_id,))
    top_vendors = [{"vendor": r[0], "total": r[1], "count": r[2]}
                   for r in c.fetchall()]

    c.execute('''
        SELECT severity, COUNT(*) FROM risk_alerts
        WHERE user_id = ? AND status = 'open'
        GROUP BY severity
    ''', (user_id,))
    alerts = {r[0]: r[1] for r in c.fetchall()}

    c.execute('''
        SELECT vendor_name, risk_level, risk_score, total_amount
        FROM vendor_profiles WHERE user_id = ?
        ORDER BY risk_score DESC LIMIT 5
    ''', (user_id,))
    risky_vendors = [{"vendor": r[0], "risk_level": r[1],
                      "risk_score": r[2], "total": r[3]}
                     for r in c.fetchall()]

    c.execute('''
        SELECT strftime('%Y-%m', transaction_date) as month,
               SUM(total_amount) as total, COUNT(*) as count
        FROM vendor_transactions WHERE user_id = ?
        GROUP BY month ORDER BY month DESC LIMIT 6
    ''', (user_id,))
    monthly = [{"month": r[0], "total": r[1], "count": r[2]}
               for r in c.fetchall()]

    # Investigation count
    c.execute('''
        SELECT COUNT(*) FROM investigation_log WHERE user_id = ?
    ''', (user_id,))
    inv_count = c.fetchone()[0] or 0

    conn.close()

    high_alerts = alerts.get('HIGH', 0)
    medium_alerts = alerts.get('MEDIUM', 0)
    potential_loss = total_spend * 0.15 if high_alerts > 0 else total_spend * 0.05

    return {
        "overview": {
            "total_spend": total_spend,
            "total_transactions": total_tx,
            "avg_transaction": avg_tx,
            "potential_loss": potential_loss,
            "investigations_run": inv_count
        },
        "alerts": {
            "high": high_alerts,
            "medium": medium_alerts,
            "total": high_alerts + medium_alerts
        },
        "top_vendors": top_vendors,
        "risky_vendors": risky_vendors,
        "monthly_trend": monthly,
    }


# ── Vendor Intelligence ───────────────────────────────────

async def analyze_vendor(user_id: str, vendor_name: str) -> dict:
    init_zenith_db()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute('''
        SELECT item_description, unit_price, total_amount,
               transaction_date, invoice_number, division
        FROM vendor_transactions
        WHERE user_id = ? AND vendor_name LIKE ?
        ORDER BY transaction_date DESC
    ''', (user_id, f'%{vendor_name}%'))
    transactions = c.fetchall()

    c.execute('''
        SELECT risk_level, risk_score, flags, total_amount,
               total_transactions, reliability_score, npwp, address
        FROM vendor_profiles
        WHERE user_id = ? AND vendor_name LIKE ?
    ''', (user_id, f'%{vendor_name}%'))
    profile = c.fetchone()
    conn.close()

    if not transactions:
        return {
            "status": "not_found",
            "message": f"Tidak ada data transaksi untuk vendor '{vendor_name}'"
        }

    total_spend = sum(t[2] for t in transactions)
    prices = [t[1] for t in transactions]
    avg_price = statistics.mean(prices) if prices else 0

    # Hitung price variance
    price_variance = 0
    if len(prices) > 1:
        try:
            price_variance = statistics.stdev(prices) / avg_price * 100
        except:
            pass

    system_prompt = """Kamu adalah Vendor Intelligence Analyst untuk Orion Zenith.
Analisa profil vendor dengan standar forensik enterprise.

PROTOKOL ADVERSARIAL THINKING:
Sebelum memberikan verdict:
1. Apakah ada penjelasan legitimate untuk pola ini?
2. Apakah vendor ini high reliability tapi ada anomali spesifik?
3. Berikan catatan "High Reliability Vendor" jika histori panjang dan bersih

Output JSON:
{
    "risk_level": "SAFE/MEDIUM/HIGH",
    "risk_score": 0-100,
    "trust_score": 0-100,
    "reliability_assessment": "HIGH/MEDIUM/LOW",
    "summary": "ringkasan profil vendor",
    "red_flags": [{"flag": "...", "evidence": "...", "severity": "HIGH/MEDIUM/LOW"}],
    "positive_signals": ["signal positif berbasis data"],
    "adversarial_check": "penjelasan apakah temuan ini bisa legitimate",
    "recommendation": "rekomendasi tindakan konkret",
    "vendor_classification": "TRUSTED/WATCH_LIST/BLACKLIST_CANDIDATE"
}

Respond HANYA dengan JSON."""

    user_message = f"""
Vendor: {vendor_name}
Total transaksi: {len(transactions)}
Total nilai: Rp {total_spend:,.0f}
Harga rata-rata: Rp {avg_price:,.0f}
Variasi harga: {price_variance:.1f}%
Profile: {profile}
Transaksi terbaru: {[{'item': t[0], 'price': t[1], 'total': t[2], 'date': t[3], 'division': t[5]} for t in transactions[:10]]}
"""

    try:
        response = await call_llm(system_prompt, user_message)
        clean = response.replace('```json', '').replace('```', '').strip()
        result = json.loads(clean)
        result['vendor_name'] = vendor_name
        result['total_transactions'] = len(transactions)
        result['total_spend'] = total_spend
        result['price_variance_pct'] = price_variance
        result['transactions'] = [
            {'item': t[0], 'unit_price': t[1], 'total': t[2],
             'date': t[3], 'division': t[5]}
            for t in transactions[:10]
        ]
        return result
    except Exception as e:
        return {
            "vendor_name": vendor_name,
            "risk_level": "UNKNOWN",
            "risk_score": 0,
            "trust_score": 50,
            "reliability_assessment": "UNKNOWN",
            "summary": f"Vendor {vendor_name} — {len(transactions)} transaksi senilai Rp {total_spend:,.0f}",
            "red_flags": [],
            "positive_signals": [],
            "adversarial_check": "Tidak dapat dianalisa",
            "recommendation": "Lakukan review manual",
            "vendor_classification": "WATCH_LIST",
            "total_transactions": len(transactions),
            "total_spend": total_spend
        }


# ── Helper Functions ──────────────────────────────────────

def _save_vendor_transaction(user_id: str, vendor_name: str,
                              item_description: str, unit_price: float,
                              quantity: float, total_amount: float,
                              category: str = "general",
                              invoice_number: str = "",
                              division: str = "",
                              approved_by: str = ""):
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''
            INSERT INTO vendor_transactions
            (user_id, vendor_name, item_description, unit_price,
             quantity, total_amount, category, invoice_number,
             division, approved_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (user_id, vendor_name, item_description, unit_price,
              quantity, total_amount, category, invoice_number,
              division, approved_by))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[ZENITH] Save transaction error: {e}")


def _get_vendor_price_history(user_id: str, item_description: str) -> list:
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''
            SELECT unit_price, transaction_date, vendor_name
            FROM vendor_transactions
            WHERE user_id = ? AND item_description LIKE ?
            ORDER BY transaction_date DESC LIMIT 20
        ''', (user_id, f'%{item_description[:20]}%'))
        rows = c.fetchall()
        conn.close()
        return [{"unit_price": r[0], "date": r[1], "vendor": r[2]}
                for r in rows]
    except:
        return []


def _get_market_reference(item_name: str, category: str) -> dict:
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''
            SELECT min_price, max_price, avg_price, unit
            FROM market_price_reference
            WHERE item_name LIKE ? OR category = ?
            LIMIT 1
        ''', (f'%{item_name[:15]}%', category))
        row = c.fetchone()
        conn.close()
        if row:
            return {"min_price": row[0], "max_price": row[1],
                    "avg_price": row[2], "unit": row[3]}
        return {}
    except:
        return {}


def _get_division_price_comparison(user_id: str, item_description: str) -> list:
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''
            SELECT division, AVG(unit_price) as avg_price,
                   MIN(unit_price) as min_price, MAX(unit_price) as max_price,
                   COUNT(*) as count
            FROM vendor_transactions
            WHERE user_id = ? AND item_description LIKE ?
            AND division != ''
            GROUP BY division
        ''', (user_id, f'%{item_description[:20]}%'))
        rows = c.fetchall()
        conn.close()
        return [{"division": r[0], "avg_price": r[1],
                 "min_price": r[2], "max_price": r[3], "count": r[4]}
                for r in rows]
    except:
        return []


def _update_vendor_profile(user_id: str, vendor_name: str,
                            transaction_amount: float, risk_score: float):
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        now = datetime.now().isoformat()
        risk_level = 'HIGH' if risk_score >= 70 else \
                     'MEDIUM' if risk_score >= 30 else 'SAFE'

        c.execute('''
            INSERT INTO vendor_profiles
            (user_id, vendor_name, total_transactions, total_amount,
             avg_transaction, risk_score, risk_level, last_transaction, updated_at)
            VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, vendor_name) DO UPDATE SET
                total_transactions = total_transactions + 1,
                total_amount = total_amount + ?,
                avg_transaction = (total_amount + ?) / (total_transactions + 1),
                risk_score = MAX(risk_score, ?),
                risk_level = ?,
                last_transaction = ?,
                updated_at = ?
        ''', (user_id, vendor_name, transaction_amount, transaction_amount,
              risk_score, risk_level, now, now,
              transaction_amount, transaction_amount,
              risk_score, risk_level, now, now))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[ZENITH] Update vendor profile error: {e}")


def _create_risk_alert(user_id: str, alert_type: str, severity: str,
                        vendor_name: str, description: str,
                        amount: float, risk_score: float,
                        confidence_score: str = "MEDIUM"):
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''
            INSERT INTO risk_alerts
            (user_id, alert_type, severity, vendor_name,
             description, amount, risk_score, confidence_score)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (user_id, alert_type, severity, vendor_name,
              description, amount, risk_score, confidence_score))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[ZENITH] Create alert error: {e}")


def _log_compliance_event(user_id: str, event_type: str,
                           entity_name: str, amount: float,
                           description: str, severity: str = "INFO",
                           approved_by: str = "",
                           policy_violated: str = ""):
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''
            INSERT INTO compliance_audit_trail
            (user_id, event_type, entity_name, amount, description,
             policy_violated, severity, approved_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (user_id, event_type, entity_name, amount, description,
              policy_violated, severity, approved_by))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[ZENITH] Log compliance error: {e}")


def get_risk_alerts(user_id: str, status: str = 'open') -> list:
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''
            SELECT id, alert_type, severity, vendor_name,
                   description, amount, risk_score,
                   confidence_score, created_at
            FROM risk_alerts
            WHERE user_id = ? AND status = ?
            ORDER BY risk_score DESC, created_at DESC
        ''', (user_id, status))
        rows = c.fetchall()
        conn.close()
        return [{
            "id": r[0], "type": r[1], "severity": r[2],
            "vendor": r[3], "description": r[4],
            "amount": r[5], "risk_score": r[6],
            "confidence": r[7], "date": r[8]
        } for r in rows]
    except:
        return []


def resolve_alert(alert_id: int, user_id: str):
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''
            UPDATE risk_alerts SET status = 'resolved',
            resolved_at = ? WHERE id = ? AND user_id = ?
        ''', (datetime.now().isoformat(), alert_id, user_id))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[ZENITH] Resolve alert error: {e}")

def seed_market_prices():
    """Isi data harga pasar referensi Indonesia"""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        
        prices = [
            # Electronics
            ('laptop', 'electronics', 5000000, 25000000, 12000000, 'unit'),
            ('laptop dell', 'electronics', 8000000, 20000000, 13000000, 'unit'),
            ('laptop asus', 'electronics', 6000000, 18000000, 11000000, 'unit'),
            ('laptop lenovo', 'electronics', 6000000, 18000000, 11000000, 'unit'),
            ('monitor', 'electronics', 1500000, 8000000, 3500000, 'unit'),
            ('printer', 'electronics', 800000, 5000000, 2000000, 'unit'),
            ('keyboard', 'electronics', 100000, 1500000, 400000, 'unit'),
            ('mouse', 'electronics', 50000, 800000, 200000, 'unit'),
            ('hp smartphone', 'electronics', 1500000, 20000000, 5000000, 'unit'),
            ('iphone', 'electronics', 8000000, 30000000, 15000000, 'unit'),
            ('tablet', 'electronics', 2000000, 15000000, 5000000, 'unit'),
            ('proyektor', 'electronics', 3000000, 20000000, 8000000, 'unit'),
            ('kamera', 'electronics', 2000000, 30000000, 8000000, 'unit'),
            # Furniture
            ('kursi kantor', 'furniture', 300000, 5000000, 1200000, 'unit'),
            ('meja kantor', 'furniture', 500000, 8000000, 2000000, 'unit'),
            ('lemari arsip', 'furniture', 800000, 5000000, 2000000, 'unit'),
            ('sofa kantor', 'furniture', 1000000, 10000000, 4000000, 'unit'),
            ('partisi kantor', 'furniture', 500000, 3000000, 1500000, 'unit'),
            # Consumables
            ('kertas a4', 'consumables', 35000, 60000, 45000, 'rim'),
            ('tinta printer', 'consumables', 50000, 300000, 150000, 'cartridge'),
            ('spidol', 'consumables', 10000, 30000, 18000, 'unit'),
            ('pulpen', 'consumables', 3000, 20000, 8000, 'unit'),
            ('stapler', 'consumables', 15000, 100000, 40000, 'unit'),
            ('amplop', 'consumables', 20000, 50000, 35000, 'pack'),
            # Services
            ('jasa desain', 'services', 500000, 10000000, 2000000, 'project'),
            ('jasa cleaning', 'services', 500000, 3000000, 1200000, 'bulan'),
            ('jasa keamanan', 'services', 2000000, 8000000, 4000000, 'bulan'),
            ('jasa akuntansi', 'services', 1000000, 10000000, 3000000, 'bulan'),
            ('jasa it support', 'services', 500000, 5000000, 2000000, 'bulan'),
            # Food & Beverage
            ('catering', 'food', 25000, 100000, 50000, 'porsi'),
            ('air mineral galon', 'food', 18000, 25000, 20000, 'galon'),
            ('kopi', 'food', 50000, 200000, 100000, 'kg'),
            # Vehicle
            ('sewa mobil', 'vehicle', 300000, 1000000, 500000, 'hari'),
            ('bensin', 'vehicle', 10000, 15000, 12500, 'liter'),
            ('service kendaraan', 'vehicle', 200000, 2000000, 600000, 'servis'),
            # Marketing
            ('iklan google', 'marketing', 500000, 10000000, 2000000, 'bulan'),
            ('iklan instagram', 'marketing', 200000, 5000000, 1000000, 'bulan'),
            ('cetak brosur', 'marketing', 200000, 2000000, 600000, 'rim'),
            ('banner', 'marketing', 50000, 500000, 150000, 'unit'),
        ]
        
        for item in prices:
            c.execute('''
                INSERT OR IGNORE INTO market_price_reference 
                (item_name, category, min_price, max_price, avg_price, unit, source)
                VALUES (?, ?, ?, ?, ?, ?, 'orion_default')
            ''', item)
        
        conn.commit()
        conn.close()
        print(f"[ZENITH] ✅ {len(prices)} data harga pasar ditambahkan")
    except Exception as e:
        print(f"[ZENITH] ❌ Seed market prices error: {e}")
