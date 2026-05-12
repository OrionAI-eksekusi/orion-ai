"""
ZENITH — Enterprise Risk Intelligence System
Price Guard AI: Deteksi markup harga vendor otomatis
"""

import os
import json
import sqlite3
import statistics
from datetime import datetime, timedelta
from app.services.ai_provider import call_llm

DB_PATH = os.getenv("DB_PATH", "orion.db")


# ── Init Zenith DB ────────────────────────────────────────
def init_zenith_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Tabel vendor transactions
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
            created_at TEXT DEFAULT (datetime('now'))
        )
    ''')

    # Tabel market price reference
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

    # Tabel risk alerts
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
            status TEXT DEFAULT 'open',
            created_at TEXT DEFAULT (datetime('now')),
            resolved_at TEXT DEFAULT ''
        )
    ''')

    # Tabel vendor profiles
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
            last_transaction TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now')),
            UNIQUE(user_id, vendor_name)
        )
    ''')

    conn.commit()
    conn.close()
    print("[ZENITH] Database initialized")


# ── Price Guard AI ────────────────────────────────────────

async def analyze_price_guard(
    user_id: str,
    vendor_name: str,
    item_description: str,
    unit_price: float,
    quantity: float = 1,
    category: str = "general"
) -> dict:
    """
    Analisa harga vendor vs market price.
    Return risk score dan rekomendasi.
    """
    init_zenith_db()
    total = unit_price * quantity

    # Simpan transaksi
    _save_vendor_transaction(
        user_id=user_id,
        vendor_name=vendor_name,
        item_description=item_description,
        unit_price=unit_price,
        quantity=quantity,
        total_amount=total,
        category=category
    )

    # Cek historical price untuk vendor ini
    historical = _get_vendor_price_history(user_id, item_description)

    # Cek market reference price
    market_ref = _get_market_reference(item_description, category)

    # AI analisis harga
    analysis = await _ai_price_analysis(
        vendor_name=vendor_name,
        item_description=item_description,
        unit_price=unit_price,
        quantity=quantity,
        total=total,
        historical=historical,
        market_ref=market_ref,
        category=category
    )

    # Update vendor profile
    _update_vendor_profile(user_id, vendor_name, total, analysis['risk_score'])

    # Buat alert kalau high risk
    if analysis['risk_level'] in ['HIGH', 'MEDIUM']:
        _create_risk_alert(
            user_id=user_id,
            alert_type='price_guard',
            severity=analysis['risk_level'],
            vendor_name=vendor_name,
            description=analysis['summary'],
            amount=total,
            risk_score=analysis['risk_score']
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
    category: str
) -> dict:
    """AI analisis apakah harga wajar atau ada markup"""

    historical_info = ""
    if historical:
        avg_hist = statistics.mean([h['unit_price'] for h in historical])
        min_hist = min(h['unit_price'] for h in historical)
        max_hist = max(h['unit_price'] for h in historical)
        historical_info = f"""
Histori harga item ini sebelumnya:
- Rata-rata: Rp {avg_hist:,.0f}
- Minimum: Rp {min_hist:,.0f}
- Maximum: Rp {max_hist:,.0f}
- Jumlah transaksi: {len(historical)}
"""

    market_info = ""
    if market_ref:
        market_info = f"""
Referensi harga pasar:
- Min: Rp {market_ref['min_price']:,.0f}
- Max: Rp {market_ref['max_price']:,.0f}
- Rata-rata: Rp {market_ref['avg_price']:,.0f}
"""

    system_prompt = """Kamu adalah AI auditor keuangan senior yang sangat teliti dan berpengalaman.
Analisa apakah harga transaksi ini wajar atau ada indikasi markup/overpricing.

Berikan analisa dalam JSON:
{
    "risk_level": "SAFE/MEDIUM/HIGH",
    "risk_score": 0-100,
    "markup_percentage": angka persentase markup jika ada,
    "summary": "ringkasan analisa 1-2 kalimat",
    "findings": ["temuan 1", "temuan 2"],
    "recommendation": "rekomendasi tindakan",
    "estimated_fair_price": angka harga wajar per unit,
    "potential_savings": angka potensi penghematan
}

Kriteria risk level:
- SAFE: harga wajar, sesuai pasar
- MEDIUM: harga sedikit tinggi (10-30% di atas rata-rata), perlu perhatian
- HIGH: harga jauh di atas wajar (>30%), indikasi markup serius

Respond HANYA dengan JSON."""

    user_message = f"""
Analisa transaksi berikut:
- Vendor: {vendor_name}
- Item: {item_description}
- Kategori: {category}
- Harga satuan: Rp {unit_price:,.0f}
- Jumlah: {quantity}
- Total: Rp {total:,.0f}

{historical_info}
{market_info}

Berikan analisa risk dan apakah harga ini wajar.
"""

    try:
        response = await call_llm(system_prompt, user_message)
        clean = response.replace('```json', '').replace('```', '').strip()
        result = json.loads(clean)
        return result
    except Exception as e:
        print(f"[PRICE GUARD AI ERROR] {e}")
        # Fallback analisis sederhana
        risk_score = 0
        if historical:
            avg = statistics.mean([h['unit_price'] for h in historical])
            if unit_price > avg * 1.5:
                risk_score = 80
            elif unit_price > avg * 1.3:
                risk_score = 50
            elif unit_price > avg * 1.1:
                risk_score = 25

        risk_level = 'HIGH' if risk_score >= 70 else 'MEDIUM' if risk_score >= 30 else 'SAFE'
        return {
            "risk_level": risk_level,
            "risk_score": risk_score,
            "markup_percentage": 0,
            "summary": f"Transaksi {vendor_name} untuk {item_description} senilai Rp {total:,.0f}",
            "findings": ["Analisa manual diperlukan"],
            "recommendation": "Verifikasi harga dengan vendor lain",
            "estimated_fair_price": unit_price,
            "potential_savings": 0
        }


# ── Transaction Anomaly Engine ────────────────────────────

async def detect_transaction_anomalies(user_id: str) -> dict:
    """Deteksi anomali transaksi — split invoice, duplikat, dll"""
    init_zenith_db()

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Ambil semua transaksi user
    c.execute('''
        SELECT vendor_name, item_description, unit_price, total_amount,
               transaction_date, invoice_number, id
        FROM vendor_transactions
        WHERE user_id = ?
        ORDER BY transaction_date DESC
        LIMIT 100
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

    # Deteksi 1: Duplikat invoice
    invoice_numbers = [t[5] for t in transactions if t[5]]
    seen = {}
    for inv in invoice_numbers:
        seen[inv] = seen.get(inv, 0) + 1
    for inv, count in seen.items():
        if count > 1:
            anomalies.append({
                "type": "DUPLICATE_INVOICE",
                "severity": "HIGH",
                "description": f"Invoice {inv} muncul {count} kali — kemungkinan double payment",
                "risk_score": 90
            })

    # Deteksi 2: Transaksi nominal sama berulang (split invoice)
    amounts = [t[3] for t in transactions]
    amount_counts = {}
    for amt in amounts:
        amount_counts[amt] = amount_counts.get(amt, 0) + 1
    for amt, count in amount_counts.items():
        if count >= 3 and amt > 1000000:
            anomalies.append({
                "type": "SPLIT_INVOICE",
                "severity": "MEDIUM",
                "description": f"Transaksi Rp {amt:,.0f} muncul {count}x — indikasi split invoice untuk hindari approval limit",
                "risk_score": 65
            })
            total_risk_amount += amt * count

    # Deteksi 3: Vendor dominan
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
                    "description": f"Vendor '{vendor}' mendominasi {pct:.1f}% dari total pembelian — perlu diversifikasi vendor",
                    "risk_score": 55
                })

    # AI summary
    summary = await _ai_anomaly_summary(anomalies, len(transactions), total_all)

    return {
        "anomalies": anomalies,
        "summary": summary,
        "total_transactions": len(transactions),
        "total_amount": total_all,
        "total_risk_amount": total_risk_amount,
        "risk_count": len(anomalies)
    }


async def _ai_anomaly_summary(anomalies: list, total_tx: int, total_amount: float) -> str:
    if not anomalies:
        return f"✅ Dari {total_tx} transaksi senilai Rp {total_amount:,.0f}, tidak ditemukan anomali yang mencurigakan."

    system_prompt = """Buat ringkasan eksekutif singkat (2-3 kalimat) dari hasil deteksi anomali transaksi.
Gunakan bahasa Indonesia yang profesional dan to the point."""

    user_message = f"""
Total transaksi: {total_tx}
Total nilai: Rp {total_amount:,.0f}
Anomali ditemukan: {json.dumps(anomalies, ensure_ascii=False)}
"""
    try:
        return await call_llm(system_prompt, user_message)
    except:
        return f"⚠️ Ditemukan {len(anomalies)} anomali dari {total_tx} transaksi. Perlu investigasi lebih lanjut."


# ── Executive Dashboard Data ──────────────────────────────

def get_executive_dashboard(user_id: str) -> dict:
    """Data untuk Executive Dashboard"""
    init_zenith_db()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Total pengeluaran
    c.execute('''
        SELECT SUM(total_amount), COUNT(*), AVG(total_amount)
        FROM vendor_transactions WHERE user_id = ?
    ''', (user_id,))
    row = c.fetchone()
    total_spend = row[0] or 0
    total_tx = row[1] or 0
    avg_tx = row[2] or 0

    # Top vendors by spending
    c.execute('''
        SELECT vendor_name, SUM(total_amount) as total, COUNT(*) as count
        FROM vendor_transactions WHERE user_id = ?
        GROUP BY vendor_name
        ORDER BY total DESC LIMIT 5
    ''', (user_id,))
    top_vendors = [{"vendor": r[0], "total": r[1], "count": r[2]}
                   for r in c.fetchall()]

    # Risk alerts summary
    c.execute('''
        SELECT severity, COUNT(*) FROM risk_alerts
        WHERE user_id = ? AND status = 'open'
        GROUP BY severity
    ''', (user_id,))
    alerts = {r[0]: r[1] for r in c.fetchall()}

    # Vendor risk profiles
    c.execute('''
        SELECT vendor_name, risk_level, risk_score, total_amount
        FROM vendor_profiles WHERE user_id = ?
        ORDER BY risk_score DESC LIMIT 5
    ''', (user_id,))
    risky_vendors = [{"vendor": r[0], "risk_level": r[1],
                      "risk_score": r[2], "total": r[3]}
                     for r in c.fetchall()]

    # Monthly trend
    c.execute('''
        SELECT strftime('%Y-%m', transaction_date) as month,
               SUM(total_amount) as total, COUNT(*) as count
        FROM vendor_transactions WHERE user_id = ?
        GROUP BY month ORDER BY month DESC LIMIT 6
    ''', (user_id,))
    monthly = [{"month": r[0], "total": r[1], "count": r[2]}
               for r in c.fetchall()]

    conn.close()

    # Hitung potensi kebocoran
    high_alerts = alerts.get('HIGH', 0)
    medium_alerts = alerts.get('MEDIUM', 0)
    potential_loss = total_spend * 0.15 if high_alerts > 0 else total_spend * 0.05

    return {
        "overview": {
            "total_spend": total_spend,
            "total_transactions": total_tx,
            "avg_transaction": avg_tx,
            "potential_loss": potential_loss,
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
    """Deep analysis satu vendor"""
    init_zenith_db()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute('''
        SELECT item_description, unit_price, total_amount,
               transaction_date, invoice_number
        FROM vendor_transactions
        WHERE user_id = ? AND vendor_name LIKE ?
        ORDER BY transaction_date DESC
    ''', (user_id, f'%{vendor_name}%'))
    transactions = c.fetchall()

    c.execute('''
        SELECT risk_level, risk_score, flags, total_amount, total_transactions
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

    system_prompt = """Kamu adalah auditor vendor senior. Analisa profil vendor dan berikan intelligence report.
Jawab HANYA dengan JSON:
{
    "risk_level": "SAFE/MEDIUM/HIGH",
    "risk_score": 0-100,
    "summary": "ringkasan profil vendor",
    "red_flags": ["flag 1", "flag 2"],
    "positive_signals": ["positif 1"],
    "recommendation": "rekomendasi tindakan",
    "trust_score": 0-100
}"""

    user_message = f"""
Vendor: {vendor_name}
Total transaksi: {len(transactions)}
Total nilai: Rp {total_spend:,.0f}
Harga rata-rata per transaksi: Rp {avg_price:,.0f}
Transaksi terbaru: {[{'item': t[0], 'price': t[1], 'date': t[3]} for t in transactions[:5]]}
"""

    try:
        response = await call_llm(system_prompt, user_message)
        clean = response.replace('```json', '').replace('```', '').strip()
        result = json.loads(clean)
        result['vendor_name'] = vendor_name
        result['total_transactions'] = len(transactions)
        result['total_spend'] = total_spend
        result['transactions'] = [
            {'item': t[0], 'unit_price': t[1],
             'total': t[2], 'date': t[3]} for t in transactions[:10]
        ]
        return result
    except Exception as e:
        return {
            "vendor_name": vendor_name,
            "risk_level": "UNKNOWN",
            "risk_score": 0,
            "summary": f"Vendor {vendor_name} — {len(transactions)} transaksi senilai Rp {total_spend:,.0f}",
            "red_flags": [],
            "positive_signals": [],
            "recommendation": "Lakukan review manual",
            "trust_score": 50,
            "total_transactions": len(transactions),
            "total_spend": total_spend
        }


# ── Helper Functions ──────────────────────────────────────

def _save_vendor_transaction(user_id: str, vendor_name: str,
                              item_description: str, unit_price: float,
                              quantity: float, total_amount: float,
                              category: str = "general",
                              invoice_number: str = ""):
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''
            INSERT INTO vendor_transactions
            (user_id, vendor_name, item_description, unit_price,
             quantity, total_amount, category, invoice_number)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (user_id, vendor_name, item_description, unit_price,
              quantity, total_amount, category, invoice_number))
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
                        amount: float, risk_score: float):
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''
            INSERT INTO risk_alerts
            (user_id, alert_type, severity, vendor_name,
             description, amount, risk_score)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (user_id, alert_type, severity, vendor_name,
              description, amount, risk_score))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[ZENITH] Create alert error: {e}")


def get_risk_alerts(user_id: str, status: str = 'open') -> list:
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''
            SELECT id, alert_type, severity, vendor_name,
                   description, amount, risk_score, created_at
            FROM risk_alerts
            WHERE user_id = ? AND status = ?
            ORDER BY risk_score DESC, created_at DESC
        ''', (user_id, status))
        rows = c.fetchall()
        conn.close()
        return [{
            "id": r[0], "type": r[1], "severity": r[2],
            "vendor": r[3], "description": r[4],
            "amount": r[5], "risk_score": r[6], "date": r[7]
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