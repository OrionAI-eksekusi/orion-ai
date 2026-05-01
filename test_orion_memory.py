import sys, os, tempfile, re
from datetime import datetime

TEMP_DB = tempfile.mktemp(suffix=".db")
os.environ["DB_PATH"] = TEMP_DB
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.services.memory_service import (
    init_memory_db, is_valid_phone, extract_name_from_message,
    sanitize_name, get_customer_memory, update_customer_memory,
    update_customer_name, get_all_customers, build_customer_context,
)

PASS, FAIL = "✅ PASS", "❌ FAIL"
results = []

def check(label, condition, detail=""):
    status = PASS if condition else FAIL
    results.append((status, label, detail))
    print(f"  {'✅' if condition else '❌'} {label}" + (f" → {detail}" if detail else ""))

def section(title):
    print(f"\n{'═'*55}\n  {title}\n{'═'*55}")

init_memory_db()

section("1. VALIDASI PHONE")
check("Phone valid normal",     is_valid_phone("628123456789"))
check("Tolak status@broadcast", not is_valid_phone("status@broadcast"))
check("Tolak 'status'",         not is_valid_phone("status"))
check("Tolak empty string",     not is_valid_phone(""))
check("Tolak None",             not is_valid_phone(None))
check("Tolak broadcast",        not is_valid_phone("broadcast"))
check("Tolak tanpa angka",      not is_valid_phone("abcdefg"))

section("2. EXTRACT NAMA — POSITIF")
cases_pos = [
    ("nama saya Budi", "Budi"), ("Nama Saya Siti", "Siti"),
    ("namaku Reza", "Reza"), ("nama ku Ahmad", "Ahmad"),
    ("panggil saya Deni", "Deni"), ("panggil aku Rina", "Rina"),
    ("Halo, perkenalkan saya Dewi", "Dewi"), ("perkenalkan, Hendra", "Hendra"),
    ("hi, saya Fitra", "Fitra"), ("halo saya Nanda", "Nanda"),
    ("my name is Kevin", "Kevin"), ("call me Tono", "Tono"),
    ("NAMA SAYA ANDI", "Andi"),
]
for msg, expected in cases_pos:
    r = extract_name_from_message(msg)
    check(f'"{msg}"', r == expected, f'got="{r}" expected="{expected}"')

section("3. EXTRACT NAMA — NEGATIF")
cases_neg = ["saya mau pesan","saya lagi cari produk","saya ingin tanya harga",
             "aku mau beli","ini pesanan saya","halo kak","ada promo?","ok siap","","ok"]
for msg in cases_neg:
    r = extract_name_from_message(msg)
    check(f'"{msg}" → kosong', r == '', f'got="{r}"')

section("4. SANITIZE NAMA")
check("Kapitalisasi",       sanitize_name("budi") == "Budi")
check("Trim whitespace",    sanitize_name("  Reza  ") == "Reza")
check("Hapus HTML/script",  sanitize_name("Budi<script>") == "Budi")
check("Nama kosong",        sanitize_name("") == "")
check("Max 30 char",        len(sanitize_name("A"*100)) <= 30)

section("5. CRUD DATABASE")
phone = "628123456789"
check("Customer baru → None", get_customer_memory(phone) is None)
update_customer_memory(phone, "halo kak", "Halo! Ada yang bisa dibantu?")
mem = get_customer_memory(phone)
check("Tersimpan",            mem is not None)
check("message_count = 1",    mem["message_count"] == 1)
update_customer_memory(phone, "nama saya Budi", "Halo Budi!")
mem = get_customer_memory(phone)
check("Nama = Budi",          mem["name"] == "Budi", f'got="{mem["name"]}"')
check("message_count = 2",    mem["message_count"] == 2)
update_customer_memory(phone, "saya mau tanya harga", "Mau tanya apa Budi?")
mem = get_customer_memory(phone)
check("Nama tetap Budi",      mem["name"] == "Budi")
check("message_count = 3",    mem["message_count"] == 3)

section("6. HISTORY CAP")
phone2 = "628999888777"
for i in range(25):
    update_customer_memory(phone2, f"pesan ke-{i}", f"reply ke-{i}")
mem2 = get_customer_memory(phone2)
check(f"History max 20 (ada {len(mem2['history'])})", len(mem2["history"]) <= 20)
check("message_count = 25",   mem2["message_count"] == 25)

section("7. BLOCKED PHONE")
for bp in ["status@broadcast", "status", "broadcast"]:
    update_customer_memory(bp, "test", "test")
phones_in_db = [c["phone"] for c in get_all_customers(100)]
check("Blocked tidak masuk DB", not any(
    bp in phones_in_db for bp in ["status@broadcast","status","broadcast"]
))

section("8. BUILD CONTEXT")
phone3 = "6281111111111"
update_customer_memory(phone3, "nama saya Sari", "Halo Sari!")
ctx = build_customer_context(phone3)
check("Context tidak kosong",       bool(ctx))
check("Mengandung nama Sari",       "Sari" in ctx)
check("Mengandung phone",           phone3 in ctx)
check("Invalid phone → kosong",     build_customer_context("status@broadcast") == "")

total = len(results)
passed = sum(1 for r in results if r[0] == PASS)
failed = total - passed
print(f"\n{'═'*55}")
print(f"  Total: {total} | ✅ Pass: {passed} | ❌ Fail: {failed}")
if failed:
    print("\n  GAGAL:")
    for s, l, d in results:
        if s == FAIL:
            print(f"    ❌ {l}" + (f" → {d}" if d else ""))
os.unlink(TEMP_DB)
print(f"\n{'═'*55}")
print(f"  {'🎉 SEMUA PASSED! Siap live.' if not failed else f'⚠️ {failed} test gagal!'}")
print(f"{'═'*55}\n")
sys.exit(0 if not failed else 1)
