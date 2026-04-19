# -*- coding: utf-8 -*-
"""
Unified Business Dashboard — บอสอู๊ด
รวม 3 ระบบ: สวนยาง | ห้องเช่า | สงกราน
Push → pong-openclaw/farm-dashboard → GitHub Pages
"""
import subprocess, json, os, sys, base64, urllib.request, urllib.error
from datetime import datetime, date

RUBBER_SHEET_ID   = "12N5-WXFkoKg06K7F5rGA0bfjHJJZ06cIJ8oKy1WsmJ8"
RENTAL_SHEET_ID   = "1IWF5gZ_w0EqbMu5uAHMF4w3I6PAgxbKb_aMeRQNDXgE"
SONGKRAN_SHEET_ID = "1iSSKpiBX9bUN1mQb7Vj6e32m8woUhJ5M9Vs54lvFoTA"
ACCOUNT    = "pong.openclaw.sandbox@gmail.com"

# ── Cross-platform paths (Windows local หรือ Linux GitHub Actions) ──
_HERE = os.path.dirname(os.path.abspath(__file__))
OUT_PATH = os.path.join(_HERE, "unified_index.html")
CHARTJS  = os.path.join(_HERE, "chart.min.js")
XLSXJS   = os.path.join(_HERE, "xlsx.min.js")
def _load_token():
    # 1) Environment variable (best practice)
    t = os.environ.get("GITHUB_TOKEN", "").strip()
    if t: return t
    # 2) Local file (fallback) — C:\Users\USER\RubberFarm\.github_token
    token_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".github_token")
    if os.path.exists(token_file):
        with open(token_file, "r", encoding="utf-8") as f:
            return f.read().strip()
    raise RuntimeError("❌ ไม่พบ GITHUB_TOKEN — ตั้ง env var หรือสร้างไฟล์ .github_token")

def _load_service_account():
    """โหลด Google Service Account JSON
    - GitHub Actions: env var GOOGLE_SERVICE_ACCOUNT_JSON
    - Local fallback: .google_service_account.json
    Returns dict หรือ None
    """
    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    if raw:
        try: return json.loads(raw)
        except: pass
    sa_file = os.path.join(_HERE, ".google_service_account.json")
    if os.path.exists(sa_file):
        with open(sa_file, encoding="utf-8") as f:
            try: return json.load(f)
            except: pass
    return None

GITHUB_TOKEN      = _load_token()
_SERVICE_ACCOUNT  = _load_service_account()
_SA_TOKEN_CACHE   = {"token": None, "expires": 0}

def _get_sa_access_token():
    """สร้าง OAuth2 access token จาก Service Account (ไม่ต้องใช้ library พิเศษ)"""
    import time, hmac, hashlib
    now = int(time.time())
    if _SA_TOKEN_CACHE["token"] and now < _SA_TOKEN_CACHE["expires"] - 60:
        return _SA_TOKEN_CACHE["token"]
    sa = _SERVICE_ACCOUNT
    # JWT header + payload
    header  = base64.urlsafe_b64encode(json.dumps({"alg":"RS256","typ":"JWT"}).encode()).rstrip(b'=')
    payload = base64.urlsafe_b64encode(json.dumps({
        "iss": sa["client_email"],
        "scope": "https://www.googleapis.com/auth/spreadsheets.readonly",
        "aud": "https://oauth2.googleapis.com/token",
        "exp": now + 3600, "iat": now
    }).encode()).rstrip(b'=')
    # Sign with RSA private key
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding
        private_key = serialization.load_pem_private_key(sa["private_key"].encode(), password=None)
        sig = private_key.sign(header + b'.' + payload, padding.PKCS1v15(), hashes.SHA256())
        sig_b64 = base64.urlsafe_b64encode(sig).rstrip(b'=')
        jwt_token = header + b'.' + payload + b'.' + sig_b64
    except ImportError:
        # cryptography ไม่ได้ติดตั้ง — ใช้ subprocess openssl
        import tempfile, subprocess as sp
        with tempfile.NamedTemporaryFile(delete=False, suffix='.pem', mode='w') as kf:
            kf.write(sa["private_key"]); kf_name = kf.name
        msg = header + b'.' + payload
        with tempfile.NamedTemporaryFile(delete=False) as mf:
            mf.write(msg); mf_name = mf.name
        r = sp.run(['openssl','dgst','-sha256','-sign',kf_name,mf_name], capture_output=True)
        os.unlink(kf_name); os.unlink(mf_name)
        sig_b64 = base64.urlsafe_b64encode(r.stdout).rstrip(b'=')
        jwt_token = header + b'.' + payload + b'.' + sig_b64
    # Exchange JWT for access token
    data = (f"grant_type=urn%3Aietf%3Aparams%3Aoauth%3Agrant-type%3Ajwt-bearer"
            f"&assertion={jwt_token.decode()}").encode()
    req = urllib.request.Request("https://oauth2.googleapis.com/token",
                                 data=data, method="POST",
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        tok = json.loads(resp.read())
    _SA_TOKEN_CACHE["token"] = tok["access_token"]
    _SA_TOKEN_CACHE["expires"] = now + tok.get("expires_in", 3600)
    return tok["access_token"]
GITHUB_REPO     = "pong-openclaw/farm-dashboard"
GITHUB_FILE     = "index.html"
GITHUB_BRANCH   = "main"
PASSWORD_HASH   = "dd6b85dbb17b7acbc9edc4274d21ea331fbb36a55b62392dd1c278683e76c699"

import urllib.parse as _uparse

def gog_get(sheet_id, range_):
    """ดึงข้อมูลจาก Google Sheets
    - ถ้ามี Service Account → ใช้ Sheets API v4 (Sheet ยัง private, ปลอดภัย ✅)
    - ถ้าไม่มี → fallback ใช้ Docker (local only)
    """
    if _SERVICE_ACCOUNT:
        return _sheets_api_get(sheet_id, range_)
    return _docker_get(sheet_id, range_)

def _sheets_api_get(sheet_id, range_):
    """Google Sheets API v4 — ใช้ Service Account (Sheet ยัง private ได้)"""
    try:
        import urllib.parse
        encoded = urllib.parse.quote(range_, safe='')
        url = (f"https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}"
               f"/values/{encoded}")
        token = _get_sa_access_token()
        req = urllib.request.Request(url, headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {token}"
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data.get("values", [])
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")[:200]
        print(f"  ⚠️ Sheets API error {e.code} [{range_}]: {body}")
        return []
    except Exception as e:
        print(f"  ⚠️ Sheets API [{range_}]: {e}")
        return []

def _docker_get(sheet_id, range_):
    """Docker fallback — ใช้ได้เฉพาะเครื่องปองที่มี OpenClaw Docker"""
    cmd = ['docker','exec','openclaw','//bin/sh','-c',
           f'gog sheets get "{sheet_id}" "{range_}" --json -a {ACCOUNT} --no-input']
    res = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8')
    if res.returncode != 0:
        print(f"  ⚠️ {range_}: {res.stderr[:80]}")
        return []
    try:
        return json.loads(res.stdout).get("values", [])
    except:
        return []

# ═══════════════════════════════════════════════════════════════════════════
# 🆕 Generic Business Framework — เพิ่มธุรกิจใหม่ได้ไม่จำกัด
# ───────────────────────────────────────────────────────────────────────────
# วิธีเพิ่มธุรกิจใหม่:
#   1. สร้าง Google Sheet ใหม่ มี 2 tab: "รายรับ" และ "รายจ่าย"
#      - หัวคอลัมน์: วันที่ | รายการ | จำนวน | หมายเหตุ
#      - วันที่ format: YYYY-MM-DD
#   2. แชร์ Sheet ให้ pong.openclaw.sandbox@gmail.com (Editor)
#   3. เพิ่ม dict ใน GENERIC_BUSINESSES ด้านล่าง — จบ!
# ───────────────────────────────────────────────────────────────────────────
GENERIC_BUSINESSES = [
    # ตัวอย่าง (uncomment เมื่อพร้อม):
    # {"key":"coffee", "name":"ร้านกาแฟ", "emoji":"☕",
    #  "color":"#6d4c41", "bg":"linear-gradient(135deg,#3e2723,#8d6e63)",
    #  "sheet_id":"ใส่_SHEET_ID_ที่นี่"},
]

EXPECTED_SCHEMAS = {
    "rubber":   ["วันที่","น้ำหนักรวม_กก","น้ำหนักสุทธิ_กก","ราคา_บาทต่อกก","ส่วนแบ่งเจ้าของ_บาท"],
    "rooms":    ["ห้อง"],
    "income":   ["วันที่"],
    "cost":     ["ปี","สินค้า","รายการ","ต้นทุน (บาท)"],
    "stock":    ["ปี","สินค้า","จำนวน","หน่วย","มูลค่า (฿)"],
}
def validate_schema(name, rows, expected):
    if not rows:
        print(f"  ⚠️ schema[{name}]: ไม่มีข้อมูล — ข้าม")
        return
    if not expected: return
    header = [str(x).strip() for x in rows[0]]
    missing = [c for c in expected if c not in header]
    if missing:
        print(f"  ⚠️ schema[{name}]: ขาดคอลัมน์ {missing} (จริง: {header})")
    else:
        print(f"  ✅ schema[{name}] OK")

def ensure_repo():
    api = f"https://api.github.com/repos/{GITHUB_REPO}"
    hdrs = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}
    req = urllib.request.Request(api, headers=hdrs)
    try:
        with urllib.request.urlopen(req): return True
    except urllib.error.HTTPError as e:
        if e.code == 404:
            org = GITHUB_REPO.split('/')[0]
            data = json.dumps({"name":"farm-dashboard","private":False,"auto_init":True}).encode()
            r2 = urllib.request.Request(f"https://api.github.com/orgs/{org}/repos",
                 data=data, headers={**hdrs,"Content-Type":"application/json"}, method="POST")
            try:
                with urllib.request.urlopen(r2): print("✅ สร้าง repo farm-dashboard"); return True
            except:
                r3 = urllib.request.Request("https://api.github.com/user/repos",
                     data=data, headers={**hdrs,"Content-Type":"application/json"}, method="POST")
                try:
                    with urllib.request.urlopen(r3): print("✅ สร้าง repo farm-dashboard (user)"); return True
                except Exception as e2:
                    print(f"⚠️ สร้าง repo ไม่ได้: {e2}"); return False
    return True

# ─── ดึงข้อมูล ─────────────────────────────────────────────────────────────
print("📥 สวนยาง...")
rubber_rows  = gog_get(RUBBER_SHEET_ID, "ชีต1!A1:M500")
print("📥 ห้องเช่า...")
rooms_rows   = gog_get(RENTAL_SHEET_ID, "ห้องพัก!A1:J20")
income_rows  = gog_get(RENTAL_SHEET_ID, "รายรับ!A1:F200")
water_rows   = gog_get(RENTAL_SHEET_ID, "น้ำไฟ_ห้อง3!A1:J50")
print("📥 สงกราน...")
cost_rows    = gog_get(SONGKRAN_SHEET_ID, "ต้นทุน!A1:G100")
sales_rows   = gog_get(SONGKRAN_SHEET_ID, "ยอดขายรายวัน!A1:I30")
summary_rows = gog_get(SONGKRAN_SHEET_ID, "สรุปรายปี!A1:H20")
stock_rows   = gog_get(SONGKRAN_SHEET_ID, "สต็อกคงเหลือ!A1:F50")

print("🛡️ ตรวจสอบ schema...")
validate_schema("rubber",  rubber_rows,  EXPECTED_SCHEMAS["rubber"])
validate_schema("rooms",   rooms_rows,   EXPECTED_SCHEMAS["rooms"])
validate_schema("income",  income_rows,  EXPECTED_SCHEMAS["income"])
validate_schema("cost",    cost_rows,    EXPECTED_SCHEMAS["cost"])
validate_schema("stock",   stock_rows,   EXPECTED_SCHEMAS["stock"])

# ─── Process Rubber ────────────────────────────────────────────────────────
def _thai_date(dt):
    return f"{dt.day:02d}/{dt.month:02d}/{dt.year+543}"

def _col(row, idx, default=0):
    try: return float(row[idx]) if len(row)>idx and row[idx] else default
    except: return default

rubber_records = []
for row in rubber_rows[1:]:
    if not row or not row[0]: continue
    try:
        dt  = datetime.strptime(row[0], "%Y-%m-%d")
        adv = _col(row,12); nw = _col(row,2)
        if nw==0 and adv==0: continue
        rubber_records.append({"date_raw":row[0],"year":dt.year,"month":dt.month,
            "yearmonth":f"{dt.year}-{dt.month:02d}","date_th":_thai_date(dt),
            "tw":_col(row,1),"nw":nw,"price":_col(row,3),"sale":_col(row,4),
            "owner":_col(row,8),"tapper":_col(row,9),"repay":_col(row,7),
            "adv":adv,"moisture":_col(row,10)})
    except: pass

def agg(recs):
    n = len(recs)
    return {"count":n,"sale":sum(r["sale"] for r in recs),"owner":sum(r["owner"] for r in recs),
            "tapper":sum(r["tapper"] for r in recs),"nw":sum(r["nw"] for r in recs),
            "repay":sum(r["repay"] for r in recs),"adv":sum(r["adv"] for r in recs),
            "price":sum(r["price"] for r in recs)/n if n else 0,
            "moisture":sum(r["moisture"] for r in recs)/n if n else 0}

by_year={}; by_month={}
for r in rubber_records:
    by_year.setdefault(r["year"],[]).append(r)
    by_month.setdefault(r["yearmonth"],[]).append(r)

r_year_data  = {y:agg(v) for y,v in sorted(by_year.items())}
r_month_data = {m:agg(v) for m,v in sorted(by_month.items())}
r_years      = sorted(set(r["year"] for r in rubber_records))
r_last_date  = rubber_records[-1]["date_th"] if rubber_records else "-"
print(f"  ✅ ยาง {len(rubber_records)} รอบ")

# ─── Process Rental ────────────────────────────────────────────────────────
rooms = []
for row in rooms_rows[1:]:
    if not row or not row[0]: continue
    rooms.append({"name":row[0],"tenant":row[1] if len(row)>1 else "-",
        "rent":float(row[2]) if len(row)>2 and row[2] else 0,
        "collect_day":row[3] if len(row)>3 else "",
        "deposit":float(row[4]) if len(row)>4 and row[4] else 0,
        "start_date":row[5] if len(row)>5 else "",
        "end_date":row[6] if len(row)>6 else "-",
        "contract":row[7] if len(row)>7 else "",
        "status":row[8] if len(row)>8 else "","note":row[9] if len(row)>9 else ""})

incomes = []
for row in income_rows[1:]:
    if not row or not row[0]: continue
    try:
        incomes.append({"date":row[0],"room":row[1] if len(row)>1 else "",
            "type":row[2] if len(row)>2 else "",
            "amount":float(row[3]) if len(row)>3 and row[3] else 0,
            "status":row[4] if len(row)>4 else "","note":row[5] if len(row)>5 else ""})
    except: pass

water_bills = []
for row in water_rows[1:]:
    if not row or not row[0] or row[0]=='ตัวอย่าง': continue
    try:
        water_bills.append({"month":row[0],
            "water_unit":float(row[3]) if len(row)>3 and row[3] else 0,
            "water_cost":float(row[4]) if len(row)>4 and row[4] else 0,
            "elec_unit":float(row[7]) if len(row)>7 and row[7] else 0,
            "elec_cost":float(row[8]) if len(row)>8 and row[8] else 0,
            "total":float(row[9]) if len(row)>9 and row[9] else 0})
    except: pass

today = date.today()
total_rent    = sum(r["rent"] for r in rooms)
total_deposit = sum(r["deposit"] for r in rooms)
occupied      = sum(1 for r in rooms if r["status"]=="เช่าอยู่")
total_income  = sum(i["amount"] for i in incomes)

expiring = []
for r in rooms:
    if r["end_date"] and r["end_date"]!="-":
        for fs in ["%d/%m/%Y","%d/%m/%y","%Y-%m-%d"]:
            try:
                end = datetime.strptime(r["end_date"], fs).date()
                dl = (end-today).days
                if dl<=60: expiring.append({"room":r["name"],"date":r["end_date"],"days":dl})
                break
            except: pass

re_alerts = []
for r in rooms:
    cd=r["collect_day"]
    d=16 if "16" in cd else (18 if "18" in cd else (1 if "1" in cd else 0))
    if d:
        nc = date(today.year,today.month,d) if today.day<d else \
             date(today.year+(1 if today.month==12 else 0),(today.month%12)+1,d)
        dt2=(nc-today).days
        if dt2<=5: re_alerts.append({"room":r["name"],"date":str(nc),"days":dt2,"amount":r["rent"]})
print(f"  ✅ ห้องเช่า {len(rooms)} ห้อง")

# ─── Process Songkran ──────────────────────────────────────────────────────
costs_sk = []
for row in cost_rows[1:]:
    if not row or not row[0]: continue
    try:
        costs_sk.append({"year":row[0],"product":row[1] if len(row)>1 else "",
            "item":row[2] if len(row)>2 else "",
            "cost":float(row[3]) if len(row)>3 and row[3] else 0,
            "unit":row[4] if len(row)>4 else "","qty":row[5] if len(row)>5 else ""})
    except: pass

sales_sk = []
for row in sales_rows[1:]:
    if not row or not row[0]: continue
    try:
        amt=float(row[5]) if len(row)>5 and row[5] else 0
        if amt>0:
            sales_sk.append({"year":row[0],"date":row[1] if len(row)>1 else "",
                "product":row[2] if len(row)>2 else "","qty":row[3] if len(row)>3 else "",
                "unit":row[4] if len(row)>4 else "","revenue":amt,
                "leftover":row[6] if len(row)>6 else ""})
    except: pass

summaries_sk = []
for row in summary_rows[1:]:
    if not row or not row[0] or not row[1]: continue
    if row[1] in ['💡 วิเคราะห์ปีหน้า','']: continue
    try:
        summaries_sk.append({"year":row[0],"product":row[1] if len(row)>1 else "",
            "revenue":float(row[2]) if len(row)>2 and row[2] else 0,
            "cost":float(row[3]) if len(row)>3 and row[3] else 0,
            "profit":float(row[4]) if len(row)>4 and row[4] else 0,
            "pct":row[5] if len(row)>5 else "",
            "stock":float(row[6]) if len(row)>6 and row[6] else 0,
            "note":row[7] if len(row)>7 else ""})
    except: pass

# ── สต็อกคงเหลือ: อ่านจาก Google Sheet (tab "สต็อกคงเหลือ") ──
# ปองแก้ข้อมูลได้จาก Sheet โดยตรง — ไม่ต้องแตะโค้ด
sk_stock_items = []
for row in stock_rows[1:]:
    if not row or len(row)<5 or not row[1]: continue
    try:
        qty_raw = row[2] if len(row)>2 else ""
        try: qty = float(qty_raw)
        except: qty = qty_raw
        val_raw = row[4] if len(row)>4 else "0"
        val = float(val_raw) if val_raw else 0
        sk_stock_items.append({
            "year": row[0] if len(row)>0 else "",
            "item": row[1],
            "qty":  qty,
            "unit": row[3] if len(row)>3 else "",
            "value": val,
            "note": row[5] if len(row)>5 else ""
        })
    except Exception as e:
        print(f"  ⚠️ skip stock row: {row} ({e})")

# Fallback ถ้า Sheet ว่าง (กันพัง)
if not sk_stock_items:
    print("  ⚠️ tab 'สต็อกคงเหลือ' ว่าง — ใช้ข้อมูล fallback")
    sk_stock_items = [
        {"year":"2569","item":"กระเป๋าเล็ก",  "qty":13,"unit":"ชิ้น","value":91,  "note":""},
        {"year":"2569","item":"กระเป๋ากลาง",  "qty":6, "unit":"ชิ้น","value":60,  "note":""},
        {"year":"2569","item":"กระเป๋าใหญ่",  "qty":44,"unit":"ชิ้น","value":880, "note":""},
        {"year":"2569","item":"แว่น",          "qty":4, "unit":"ชิ้น","value":36,  "note":""},
        {"year":"2569","item":"กระป๋อง",       "qty":2, "unit":"ชิ้น","value":22,  "note":""},
        {"year":"2569","item":"แป้งสี",        "qty":11,"unit":"กส.", "value":3300,"note":""},
        {"year":"2569","item":"แป้งขาว",       "qty":10,"unit":"กก.", "value":60,  "note":""},
    ]
print(f"  ✅ สต็อก {len(sk_stock_items)} รายการ (รวม {sum(s['value'] for s in sk_stock_items):,.0f} ฿)")
sk_stock_items_j = json.dumps(sk_stock_items, ensure_ascii=False)

sk_total_row     = next((s for s in summaries_sk if s["product"]=="รวมทั้งหมด"), None)
sk_total_revenue = sk_total_row["revenue"] if sk_total_row else sum(s["revenue"] for s in sales_sk)
sk_total_cost    = sk_total_row["cost"]    if sk_total_row else 0
sk_total_profit  = sk_total_row["profit"]  if sk_total_row else 0
sk_total_stock   = sum(item["value"] for item in sk_stock_items)
sk_pct           = sk_total_row["pct"]     if sk_total_row else ""
print(f"  ✅ สงกราน {len(summaries_sk)} สินค้า")

# ─── Process Generic Businesses (เปิดพื้นที่สำหรับธุรกิจใหม่) ──────────────
def _parse_generic_rows(rows):
    out = []
    for row in rows[1:] if rows else []:
        if not row or not row[0]: continue
        try:
            out.append({
                "date":   row[0],
                "item":   row[1] if len(row)>1 else "",
                "amount": float(row[2]) if len(row)>2 and row[2] else 0,
                "note":   row[3] if len(row)>3 else ""
            })
        except: pass
    return out

generic_biz = []
for cfg in GENERIC_BUSINESSES:
    print(f"📥 {cfg['emoji']} {cfg['name']}...")
    sid = cfg["sheet_id"]
    rev_rows = gog_get(sid, "รายรับ!A1:D500")
    exp_rows = gog_get(sid, "รายจ่าย!A1:D500")
    validate_schema(f"{cfg['key']}_rev", rev_rows, ["วันที่","รายการ","จำนวน"])
    validate_schema(f"{cfg['key']}_exp", exp_rows, ["วันที่","รายการ","จำนวน"])
    revs = _parse_generic_rows(rev_rows)
    exps = _parse_generic_rows(exp_rows)
    generic_biz.append({**cfg, "revenues": revs, "expenses": exps})
    print(f"  ✅ {cfg['name']} — รายรับ {len(revs)} รายการ, รายจ่าย {len(exps)} รายการ")

generic_biz_j = json.dumps(generic_biz, ensure_ascii=False)

# ─── Build dynamic HTML/JS fragments for generic businesses ────────────────
generic_tab_buttons = "".join(
    f'<button id="btn-{b["key"]}" class="tab-btn" onclick="switchTab(\'{b["key"]}\')" '
    f'style="background:{b["bg"]};color:white">{b["emoji"]} {b["name"]}</button>\n  '
    for b in generic_biz
)
generic_tab_divs = "".join(
    f'''
<div id="tab-{b["key"]}" style="display:none">
<header style="background:{b["bg"]};color:white;padding:20px 28px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:12px">
  <div>
    <h1>{b["emoji"]} {b["name"]}</h1>
    <p>รายรับ · รายจ่าย · กำไรสุทธิ</p>
  </div>
</header>
<div class="container">
  <div class="biz-kpi-row" id="gb-{b["key"]}-kpi"></div>
  <div class="charts-grid" style="margin-top:20px">
    <div class="chart-card wide"><h3>📈 รายรับ vs รายจ่าย รายเดือน (฿)</h3><canvas id="gb-{b["key"]}-monthChart"></canvas></div>
  </div>
  <div class="charts-grid">
    <div class="chart-card"><h3>📊 เปรียบเทียบรายปี (฿)</h3><canvas id="gb-{b["key"]}-yearChart"></canvas></div>
    <div class="chart-card"><h3>🥧 สัดส่วนรายจ่าย</h3><canvas id="gb-{b["key"]}-expPie"></canvas></div>
  </div>
  <div class="section" style="margin-top:20px">
    <h3>📋 ธุรกรรมล่าสุด</h3>
    <div style="overflow-x:auto"><table id="gb-{b["key"]}-tbl"></table></div>
  </div>
</div>
</div>
''' for b in generic_biz
)
generic_keys_js = json.dumps([b["key"] for b in generic_biz])

# ─── Load libs ─────────────────────────────────────────────────────────────
with open(CHARTJS, encoding="utf-8") as f: chartjs = f.read()
with open(XLSXJS,  encoding="utf-8") as f: xlsxjs  = f.read()
built_at = datetime.now().strftime("%d/%m/%Y %H:%M")
updated_by = "ปอง"
update_stamp = f'<span style="display:inline-flex;align-items:center;gap:4px;background:rgba(255,255,255,.15);padding:2px 10px;border-radius:12px;font-size:.82em">🕒 อัปเดตโดย <b>{updated_by}</b> · {built_at}</span>'

# ─── JSON payloads ─────────────────────────────────────────────────────────
r_data_j   = json.dumps(rubber_records, ensure_ascii=False)
r_year_j   = json.dumps(r_year_data,    ensure_ascii=False)
r_month_j  = json.dumps(r_month_data,   ensure_ascii=False)
r_years_j  = json.dumps(r_years)
rooms_j    = json.dumps(rooms,          ensure_ascii=False)
incomes_j  = json.dumps(incomes,        ensure_ascii=False)
water_j    = json.dumps(water_bills,    ensure_ascii=False)
exp_j      = json.dumps(expiring,       ensure_ascii=False)
ral_j      = json.dumps(re_alerts,      ensure_ascii=False)
sk_sum_j   = json.dumps([s for s in summaries_sk if s["product"]!="รวมทั้งหมด"], ensure_ascii=False)
sk_sales_j = json.dumps(sales_sk,       ensure_ascii=False)
sk_costs_j = json.dumps(costs_sk,       ensure_ascii=False)

fmt_thb = lambda n: f"{n:,.0f}"

# ─── HTML ──────────────────────────────────────────────────────────────────
html = f"""<!DOCTYPE html>
<html lang="th">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0,viewport-fit=cover">
<title>Boss Business Hub — บอสอู๊ด</title>
<!-- 📱 PWA -->
<link rel="manifest" href="manifest.json">
<meta name="theme-color" content="#1a1a2e">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="BossHub">
<link rel="icon" type="image/svg+xml" href="icon.svg">
<link rel="apple-touch-icon" href="icon.svg">
<script>{chartjs}</script>
<script>{xlsxjs}</script>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:'Leelawadee UI','Leelawadee','Tahoma','Myanmar Text',sans-serif;background:#f0f2f5;color:#333}}
.mm{{display:block;font-size:.75em;color:#aaa;font-family:'Myanmar Text','Noto Sans Myanmar',sans-serif;margin-top:1px;font-weight:normal}}

/* ── Tab Nav ── */
.tab-nav{{background:#1a1a2e;padding:0;display:flex;overflow-x:auto;position:sticky;top:0;z-index:100;box-shadow:0 2px 8px rgba(0,0,0,.4)}}
.tab-btn{{padding:14px 24px;border:none;cursor:pointer;font-family:inherit;font-size:.95em;font-weight:bold;color:rgba(255,255,255,.5);background:transparent;border-bottom:3px solid transparent;transition:all .2s;white-space:nowrap;flex-shrink:0}}
.tab-btn:hover{{color:white;background:rgba(255,255,255,.05)}}
.tab-btn.active{{color:white;border-bottom-color:white}}
.tab-btn.t-overview.active{{border-bottom-color:#ffd54f;color:#ffd54f}}
.tab-btn.t-rubber.active{{border-bottom-color:#66bb6a;color:#a5d6a7}}
.tab-btn.t-rental.active{{border-bottom-color:#64b5f6;color:#90caf9}}
.tab-btn.t-songkran.active{{border-bottom-color:#f48fb1;color:#f48fb1}}

/* ── Overview ── */
#tab-overview header{{background:linear-gradient(135deg,#1a1a2e,#37474f);color:white;padding:20px 28px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:12px}}
.biz-group{{background:white;border-radius:12px;padding:20px;box-shadow:0 2px 8px rgba(0,0,0,.08);margin-bottom:20px}}
.biz-group h3{{font-size:1em;font-weight:bold;margin-bottom:14px;padding-bottom:8px;border-bottom:3px solid #f0f2f5;display:flex;align-items:center;gap:8px}}
.biz-group.rubber h3{{border-color:#4CAF50;color:#2e7d32}}
.biz-group.rental h3{{border-color:#1976D2;color:#1565C0}}
.biz-group.songkran h3{{border-color:#E91E63;color:#880E4F}}
.biz-kpi-row{{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px}}
.biz-kpi{{border-radius:10px;padding:14px;text-align:center}}
.biz-kpi .bk-num{{font-size:1.3em;font-weight:bold;margin-bottom:4px}}
.biz-kpi .bk-label{{font-size:.75em;color:#888}}
.biz-kpi.green{{background:#f1f8e9}}.biz-kpi.green .bk-num{{color:#2e7d32}}
.biz-kpi.blue{{background:#e3f2fd}}.biz-kpi.blue .bk-num{{color:#1565C0}}
.biz-kpi.orange{{background:#fff3e0}}.biz-kpi.orange .bk-num{{color:#e65100}}
.biz-kpi.purple{{background:#f3e5f5}}.biz-kpi.purple .bk-num{{color:#6a1b9a}}
.biz-kpi.pink{{background:#fce4ec}}.biz-kpi.pink .bk-num{{color:#880E4F}}
.biz-kpi.red{{background:#ffebee}}.biz-kpi.red .bk-num{{color:#b71c1c}}
.biz-kpi.gray{{background:#f5f5f5}}.biz-kpi.gray .bk-num{{color:#555}}
.ov-summary-table th{{background:#37474f;color:white;padding:10px 14px;text-align:center;white-space:nowrap}}
.ov-summary-table td{{padding:10px 14px;border-bottom:1px solid #f0f2f5;text-align:center;font-size:.9em}}
.ov-summary-table tr:last-child td{{background:#f5f5f5;font-weight:bold}}

/* ── Shared ── */
.container{{max-width:1300px;margin:0 auto;padding:20px}}
.btn{{padding:9px 18px;border:none;border-radius:8px;font-family:inherit;font-size:.9em;cursor:pointer;font-weight:bold;transition:all .2s}}
.btn-pdf{{background:#fff;color:#c62828}}.btn-pdf:hover{{background:#ffebee}}
.btn-excel{{background:#1b5e20;color:white}}.btn-excel:hover{{background:#388e3c}}
.kpi-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(155px,1fr));gap:14px;margin-bottom:20px}}
.kpi{{background:white;border-radius:12px;padding:18px;box-shadow:0 2px 8px rgba(0,0,0,.08);border-left:4px solid #4CAF50}}
.kpi .num{{font-size:1.4em;font-weight:bold;color:#2e7d32}}
.kpi .label{{color:#888;font-size:.8em;margin-top:3px}}
.kpi.blue{{border-color:#2196F3}}.kpi.blue .num{{color:#1565C0}}
.kpi.orange{{border-color:#ff9800}}.kpi.orange .num{{color:#e65100}}
.kpi.purple{{border-color:#9c27b0}}.kpi.purple .num{{color:#6a1b9a}}
.kpi.red{{border-color:#f44336}}.kpi.red .num{{color:#b71c1c}}
.kpi.pink{{border-color:#E91E63}}.kpi.pink .num{{color:#880E4F}}
.section{{background:white;border-radius:12px;padding:18px;box-shadow:0 2px 8px rgba(0,0,0,.08);margin-bottom:20px}}
.section h3{{font-size:.95em;color:#555;margin-bottom:14px;padding-bottom:8px;border-bottom:2px solid #f0f2f5}}
.charts-grid{{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:20px}}
.chart-card{{background:white;border-radius:12px;padding:18px;box-shadow:0 2px 8px rgba(0,0,0,.08);position:relative;min-height:240px}}
.chart-card.wide{{grid-column:1/-1}}
.chart-card canvas{{max-height:320px!important;width:100%!important}}
.chart-card.wide canvas{{max-height:380px!important;width:100%!important}}
.chart-card h3{{font-size:.9em;color:#555;margin-bottom:12px;padding-bottom:8px;border-bottom:2px solid #f0f2f5}}
table{{width:100%;border-collapse:collapse;font-size:.85em}}
td{{padding:8px 12px;border-bottom:1px solid #f0f2f5;text-align:center}}
tfoot td{{font-weight:bold}}
tr:hover td{{background:#f9f9f9}}
.badge{{display:inline-block;padding:1px 7px;border-radius:20px;font-size:.78em}}
.no-data{{text-align:center;color:#aaa;padding:30px;font-size:.9em}}

/* ── Rubber ── */
#tab-rubber header{{background:linear-gradient(135deg,#2e7d32,#66bb6a);color:white;padding:20px 28px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:12px}}
.filterbar{{background:white;border-radius:12px;padding:16px 20px;margin-bottom:20px;box-shadow:0 2px 8px rgba(0,0,0,.08);display:flex;gap:16px;align-items:center;flex-wrap:wrap}}
.filterbar label{{font-size:.9em;color:#555;font-weight:bold}}
.filterbar select{{padding:7px 12px;border:1px solid #ddd;border-radius:8px;font-family:inherit;font-size:.9em}}
.view-btns{{display:flex;gap:6px;margin-left:auto}}
.vbtn{{padding:7px 16px;border:2px solid #4CAF50;border-radius:8px;background:white;color:#2e7d32;cursor:pointer;font-family:inherit;font-size:.85em;font-weight:bold}}
.vbtn.active{{background:#4CAF50;color:white}}
#tab-rubber th{{background:#2e7d32;color:white;padding:9px 12px;text-align:center;white-space:nowrap}}
tfoot.r-foot td{{background:#f1f8e9}}
.insight{{background:#e8f5e9;border-left:4px solid #4CAF50;border-radius:8px;padding:14px 18px;margin-bottom:20px}}
.insight h3{{color:#2e7d32;margin-bottom:8px;font-size:.95em}}
.insight ul{{padding-left:18px;line-height:2;color:#444;font-size:.9em}}
.badge.high{{background:#e8f5e9;color:#2e7d32}}.badge.low{{background:#fff3e0;color:#e65100}}

/* ── Rental ── */
#tab-rental header{{background:linear-gradient(135deg,#1565C0,#42A5F5);color:white;padding:20px 28px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:12px}}
#tab-rental th{{background:#1565C0;color:white;padding:9px 12px;text-align:center;white-space:nowrap}}
tfoot.re-foot td{{background:#e3f2fd}}
tr:hover.re-row td{{background:#f0f8ff}}
.rooms-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:14px}}
.room-card{{border-radius:10px;padding:16px;border:2px solid #e3f2fd}}
.room-card.occupied{{border-color:#4CAF50;background:#f9fff9}}
.room-card.vacant{{border-color:#ff9800;background:#fff8f0}}
.room-card h4{{font-size:1em;font-weight:bold;margin-bottom:8px;color:#1565C0}}
.room-card .rent{{font-size:1.4em;font-weight:bold;color:#2e7d32;margin:4px 0}}
.room-card .detail{{font-size:.82em;color:#666;line-height:1.7}}
.sbadge{{display:inline-block;padding:2px 10px;border-radius:20px;font-size:.75em;font-weight:bold}}
.sbadge.ok{{background:#e8f5e9;color:#2e7d32}}.sbadge.warn{{background:#fff3e0;color:#e65100}}
.alert-box{{background:#fff8e1;border-left:4px solid #ffc107;border-radius:8px;padding:12px 16px;margin-bottom:8px;font-size:.88em}}
.alert-box.danger{{background:#ffebee;border-color:#f44336}}

/* ── Songkran ── */
#tab-songkran header{{background:linear-gradient(135deg,#880E4F,#E91E63);color:white;padding:20px 28px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:12px}}
#tab-songkran th{{background:#880E4F;color:white;padding:9px 12px;text-align:center;white-space:nowrap}}
tfoot.sk-foot td{{background:#fce4ec}}
.profit-pos{{color:#2e7d32;font-weight:bold}}.profit-neg{{color:#b71c1c;font-weight:bold}}
.tip-box{{background:#fff8e1;border-left:4px solid #ffc107;border-radius:8px;padding:12px 16px;margin-bottom:8px;font-size:.88em;line-height:1.8}}
.stock-badge{{display:inline-block;padding:2px 8px;border-radius:20px;font-size:.78em;background:#e8f5e9;color:#2e7d32}}

/* ── Mobile ── */
@media(max-width:700px){{
  .tab-btn{{padding:12px 16px;font-size:.85em}}
  .container{{padding:12px}}
  header{{padding:14px 16px!important}}
  header h1{{font-size:1.15em!important}}
  .kpi-grid{{grid-template-columns:1fr 1fr}}
  .kpi{{padding:12px}}
  .kpi .num{{font-size:1.2em}}
  .charts-grid{{grid-template-columns:1fr}}
  .chart-card.wide{{grid-column:1}}
  .filterbar{{flex-direction:column;align-items:stretch;gap:10px}}
  .filterbar select{{width:100%}}
  .view-btns{{margin-left:0;width:100%}}
  .vbtn{{flex:1;text-align:center}}
  table{{font-size:.78em}}
  th,td{{padding:7px 5px!important}}
  #r-mainTable.view-round th:nth-child(2),#r-mainTable.view-round td:nth-child(2),
  #r-mainTable.view-round th:nth-child(3),#r-mainTable.view-round td:nth-child(3),
  #r-mainTable.view-round th:nth-child(5),#r-mainTable.view-round td:nth-child(5),
  #r-mainTable.view-round th:nth-child(8),#r-mainTable.view-round td:nth-child(8),
  #r-mainTable.view-round th:nth-child(9),#r-mainTable.view-round td:nth-child(9),
  #r-mainTable.view-round th:nth-child(10),#r-mainTable.view-round td:nth-child(10){{display:none}}
  #r-mainTable.view-agg th:nth-child(2),#r-mainTable.view-agg td:nth-child(2),
  #r-mainTable.view-agg th:nth-child(6),#r-mainTable.view-agg td:nth-child(6),
  #r-mainTable.view-agg th:nth-child(9),#r-mainTable.view-agg td:nth-child(9),
  #r-mainTable.view-agg th:nth-child(10),#r-mainTable.view-agg td:nth-child(10){{display:none}}
}}
</style>
</head>
<body>

<!-- 🔒 Password Gate -->
<div id="lockscreen" style="position:fixed;top:0;left:0;width:100%;height:100%;background:linear-gradient(135deg,#0d0d1a,#1a1a2e);display:flex;align-items:center;justify-content:center;z-index:99999;font-family:'Leelawadee UI','Tahoma',sans-serif">
  <div style="background:white;border-radius:20px;padding:40px 36px;text-align:center;width:340px;box-shadow:0 20px 60px rgba(0,0,0,.5)">
    <div style="font-size:2.5em;margin-bottom:10px">🌿🏠🎊</div>
    <h2 style="color:#1a1a2e;margin-bottom:6px;font-size:1.25em">Dashboard บอสอู๊ด</h2>
    <p style="color:#666;font-size:.85em;margin-bottom:6px">สวนยาง · ห้องเช่า · สงกราน</p>
    <p style="color:#999;font-size:.8em;margin-bottom:24px">กรุณาใส่รหัสผ่านเพื่อเข้าใช้งาน</p>
    <input id="pwInput" type="password" placeholder="รหัสผ่าน"
      style="width:100%;padding:13px;border:2px solid #e0e0e0;border-radius:10px;font-size:1.1em;text-align:center;outline:none;transition:.2s;font-family:inherit"
      onfocus="this.style.borderColor='#1a1a2e'" onblur="this.style.borderColor='#e0e0e0'"
      onkeydown="if(event.key==='Enter')checkPw()">
    <button onclick="checkPw()"
      style="width:100%;margin-top:14px;padding:13px;background:#1a1a2e;color:white;border:none;border-radius:10px;font-size:1em;cursor:pointer;font-weight:bold;font-family:inherit">
      🔓 เข้าสู่ระบบ
    </button>
    <p id="pwErr" style="color:#e53935;margin-top:14px;font-size:.85em;display:none">❌ รหัสผ่านไม่ถูกต้อง</p>
  </div>
</div>
<script>
(function(){{if(sessionStorage.getItem('uni_auth')==='ok')document.getElementById('lockscreen').style.display='none';}})();
async function checkPw(){{
  const pw=document.getElementById('pwInput').value;if(!pw)return;
  const buf=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(pw));
  const hex=Array.from(new Uint8Array(buf)).map(b=>b.toString(16).padStart(2,'0')).join('');
  if(hex==='{PASSWORD_HASH}'){{sessionStorage.setItem('uni_auth','ok');document.getElementById('lockscreen').style.display='none';document.getElementById('pwInput').value='';}}
  else{{const e=document.getElementById('pwErr');e.style.display='block';document.getElementById('pwInput').value='';setTimeout(()=>e.style.display='none',3000);}}
}}
</script>

<!-- Tab Nav -->
<nav class="tab-nav">
  <button id="btn-overview"  class="tab-btn t-overview active"  onclick="switchTab('overview')">📊 ภาพรวม</button>
  <button id="btn-rubber"    class="tab-btn t-rubber"            onclick="switchTab('rubber')">🌿 สวนยาง</button>
  <button id="btn-rental"    class="tab-btn t-rental"            onclick="switchTab('rental')">🏠 ห้องเช่า</button>
  <button id="btn-songkran"  class="tab-btn t-songkran"          onclick="switchTab('songkran')">🎊 สงกราน</button>
  {generic_tab_buttons}
</nav>

<!-- ════════════════════════════════════════════════════
     TAB: ภาพรวม
════════════════════════════════════════════════════ -->
<div id="tab-overview">
<header>
  <div>
    <h1>📊 ภาพรวมธุรกิจทั้งหมด — บอสอู๊ด</h1>
    <p>สวนยาง · ห้องเช่า · สงกราน {update_stamp}</p>
  </div>
</header>
<div class="container">

  <!-- 🧠 Quick Insights -->
  <div id="ov-insights" style="background:linear-gradient(135deg,#fffbeb,#fef3c7);border-left:5px solid #f59e0b;border-radius:12px;padding:18px 22px;margin-bottom:20px"></div>

  <!-- 📄 Action buttons -->
  <div style="text-align:right;margin-bottom:14px">
    <button onclick="openAnnualReport()" style="background:#1a1a2e;color:white;border:none;padding:10px 20px;border-radius:8px;cursor:pointer;font-weight:600;font-size:.92em">
      📄 พิมพ์รายงานประจำปี (PDF)
    </button>
  </div>

  <!-- กราฟเปรียบเทียบ -->
  <div class="charts-grid" style="margin-bottom:20px">
    <div class="chart-card wide"><h3>💹 รายได้/กำไรเปรียบเทียบ แต่ละธุรกิจ แต่ละปี (฿)</h3><canvas id="ov-compareChart"></canvas></div>
  </div>
  <div class="charts-grid">
    <div class="chart-card"><h3>🥧 สัดส่วนรายได้รวม แต่ละธุรกิจ</h3><canvas id="ov-pieChart"></canvas></div>
    <div class="chart-card"><h3>📅 รายรับรวมทุกธุรกิจ รายเดือน (฿)</h3><canvas id="ov-monthChart"></canvas></div>
  </div>

  <!-- 📈 Trend 12 เดือนล่าสุด -->
  <div class="charts-grid" style="margin-top:20px">
    <div class="chart-card wide"><h3>📈 แนวโน้ม 12 เดือน + ทำนาย 3 เดือนข้างหน้า (เส้นประ) — สวนยาง + ห้องเช่า</h3><canvas id="ov-trend12Chart"></canvas></div>
  </div>

  <!-- 💰 Cash Flow Statement รายเดือน (12 เดือน) -->
  <div class="section" style="margin-top:20px">
    <h3>💰 งบกระแสเงินสด (Cash Flow) — 12 เดือนล่าสุด</h3>
    <div style="overflow-x:auto"><table class="ov-summary-table" id="ov-cashflow"></table></div>
  </div>

  <!-- KPI ธุรกิจ -->
  <div class="biz-group rubber">
    <h3>🌿 สวนยางพารา</h3>
    <div class="biz-kpi-row" id="ov-rubberKpi"></div>
  </div>
  <div class="biz-group rental">
    <h3>🏠 ห้องเช่า</h3>
    <div class="biz-kpi-row" id="ov-rentalKpi"></div>
  </div>
  <div class="biz-group songkran">
    <h3>🎊 สงกราน</h3>
    <div class="biz-kpi-row" id="ov-songkranKpi"></div>
  </div>

  <!-- Generic Businesses KPI (auto) -->
  <div id="ov-genericKpiContainer"></div>

  <!-- 🎯 Goals & Budget Tracking -->
  <div class="section" style="margin-top:20px">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">
      <h3 style="margin:0">🎯 เป้าหมายรายได้ ปี <span id="ov-goalYear"></span></h3>
      <button onclick="goalsSetup()" style="background:#6366f1;color:white;border:none;padding:7px 14px;border-radius:6px;cursor:pointer;font-size:.85em;font-weight:600">⚙️ ตั้งเป้า</button>
    </div>
    <div id="ov-goals"></div>
  </div>

  <!-- 🧮 Thai Tax Estimator -->
  <div class="section" style="margin-top:20px">
    <h3>🧮 ประมาณการภาษีเงินได้บุคคลธรรมดา ปี <span id="ov-taxYear"></span></h3>
    <div id="ov-taxCard"></div>
  </div>

  <!-- 🏆 Business Health Score -->
  <div class="section" style="margin-top:20px">
    <h3>🏆 คะแนนสุขภาพธุรกิจ (Business Health Score)</h3>
    <p style="color:#666;font-size:.88em;margin-bottom:12px">
      วัดจาก 4 มิติ: 📈 ความสามารถทำกำไร · 🚀 การเติบโต YoY · 🎯 ความสม่ำเสมอ · 💰 กระแสเงินสด —
      เกรด <b style="color:#059669">A</b> ดีเยี่ยม · <b style="color:#0284c7">B</b> ดี · <b style="color:#ea580c">C</b> พอใช้ · <b style="color:#dc2626">D</b> ต้องปรับ
    </p>
    <div id="ov-healthCards" class="charts-grid" style="grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:14px"></div>
  </div>

  <!-- ตารางสรุป -->
  <div class="section">
    <h3>📋 ตารางสรุปทุกธุรกิจ</h3>
    <div style="overflow-x:auto"><table class="ov-summary-table" id="ov-table"></table></div>
  </div>
</div>
</div>

<!-- ════════════════════════════════════════════════════
     TAB: สวนยาง
════════════════════════════════════════════════════ -->
<div id="tab-rubber" style="display:none">
<header>
  <div>
    <h1>🌿 สวนยางพารา <span style="font-size:.65em;opacity:.8;font-weight:normal">ရာဘာဥယျာဉ်</span></h1>
    <p>เจ้าของสวน (ဥယျာဉ်ပိုင်ရှင်) | ข้อมูลล่าสุด: {r_last_date} {update_stamp}</p>
  </div>
  <div style="display:flex;gap:8px;flex-wrap:wrap">
    <button class="btn btn-pdf" onclick="exportPDF()">🖨️ PDF</button>
    <button class="btn btn-excel" onclick="exportExcel()">📊 Excel</button>
  </div>
</header>
<div class="container">
  <div class="filterbar">
    <label>📅 ปี:</label>
    <select id="r-yearFilter" onchange="rApplyFilter()">
      <option value="all">ทั้งหมด</option>
    </select>
    <label>📆 มุมมอง:</label>
    <div class="view-btns">
      <button class="vbtn active" id="r-vRound" onclick="rSetView('round')">รายรอบ</button>
      <button class="vbtn" id="r-vMonth" onclick="rSetView('month')">รายเดือน</button>
      <button class="vbtn" id="r-vYear"  onclick="rSetView('year')">รายปี</button>
    </div>
    <span style="margin-left:auto;font-size:.78em;color:#999">🔄 Google Sheet</span>
  </div>
  <div class="kpi-grid" id="r-kpiGrid"></div>
  <div class="insight" id="r-insightBox"></div>
  <div class="charts-grid">
    <div class="chart-card wide"><h3 id="r-chart1Title">💰 เจ้าของสวน vs คนตัด (บาท) <span style="font-weight:normal;font-size:.8em;opacity:.7">ဥယျာဉ်ပိုင်ရှင် နှင့် ရာဘာဖြတ်သူ</span></h3><canvas id="r-moneyChart"></canvas></div>
    <div class="chart-card"><h3>📈 ราคายาง (บาท/กก.)</h3><canvas id="r-priceChart"></canvas></div>
    <div class="chart-card"><h3>⚖️ น้ำหนักสุทธิ (กก.)</h3><canvas id="r-weightChart"></canvas></div>
    <div class="chart-card"><h3>💧 ความชื้นเฉลี่ย (%)</h3><canvas id="r-moistureChart"></canvas></div>
    <div class="chart-card"><h3>🏦 รายได้สะสมเจ้าของสวน <span style="font-weight:normal;font-size:.8em;opacity:.7">စုစုပေါင်းဝင်ငွေ</span></h3><canvas id="r-cumulChart"></canvas></div>
  </div>
  <div class="section">
    <h3 id="r-tableTitle">📋 ข้อมูล</h3>
    <div style="overflow-x:auto"><table id="r-mainTable">
      <thead id="r-tableHead"></thead>
      <tbody id="r-tableBody"></tbody>
      <tfoot id="r-tableFoot" class="r-foot"></tfoot>
    </table></div>
  </div>
</div>
</div>

<!-- ════════════════════════════════════════════════════
     TAB: ห้องเช่า
════════════════════════════════════════════════════ -->
<div id="tab-rental" style="display:none">
<header>
  <div>
    <h1>🏠 ห้องเช่า — บอสอู๊ด</h1>
    <p>ห้องทั้งหมด {len(rooms)} ห้อง {update_stamp}</p>
  </div>
</header>
<div class="container">
  <!-- Filter Bar -->
  <div class="filterbar" style="border-left:4px solid #1976D2">
    <label>📅 ปี:</label>
    <select id="re-yearFilter" onchange="reFilterYear()" style="border-color:#90caf9">
      <option value="all">ทั้งหมด</option>
    </select>
    <label>🏠 ห้อง:</label>
    <select id="re-roomFilter" onchange="reFilterYear()" style="border-color:#90caf9">
      <option value="all">ทุกห้อง</option>
    </select>
    <span style="margin-left:auto;font-size:.78em;color:#999">🔄 Google Sheet</span>
  </div>
  <!-- KPI (JS-driven) -->
  <div class="kpi-grid" id="re-kpiGrid"></div>
  <div id="re-alertSection"></div>
  <div class="section">
    <h3>🏠 สถานะห้องทั้งหมด</h3>
    <div class="rooms-grid" id="re-roomsGrid"></div>
  </div>
  <div class="charts-grid">
    <div class="chart-card"><h3 id="re-chartTitle">💰 รายรับรายเดือน (฿)</h3><canvas id="re-incomeChart"></canvas></div>
    <div class="chart-card"><h3>🏠 สัดส่วนค่าเช่าแต่ละห้อง</h3><canvas id="re-pieChart"></canvas></div>
  </div>
  <div class="section">
    <h3 id="re-tableTitle">📋 ประวัติรายรับ</h3>
    <div style="overflow-x:auto"><table>
      <thead><tr><th>วันที่</th><th>ห้อง</th><th>ประเภท</th><th>จำนวน (฿)</th><th>สถานะ</th><th>หมายเหตุ</th></tr></thead>
      <tbody id="re-incomeBody"></tbody>
      <tfoot id="re-incomeFoot" class="re-foot"></tfoot>
    </table></div>
  </div>
  <div class="section">
    <h3>💡 ค่าน้ำ+ค่าไฟ ห้อง 3</h3>
    <div style="overflow-x:auto"><table>
      <thead><tr><th>เดือน</th><th>หน่วยน้ำ</th><th>ค่าน้ำ (฿)</th><th>หน่วยไฟ</th><th>ค่าไฟ (฿)</th><th>รวม (฿)</th></tr></thead>
      <tbody id="re-waterBody"></tbody>
    </table></div>
  </div>
</div>
</div>

<!-- ════════════════════════════════════════════════════
     TAB: สงกราน
════════════════════════════════════════════════════ -->
<div id="tab-songkran" style="display:none">
<header>
  <div>
    <h1>🎊 สงกราน — บอสอู๊ด</h1>
    <p>วิเคราะห์กำไร/ขาดทุน ทุกสินค้า {update_stamp}</p>
  </div>
</header>
<div class="container">
  <div class="kpi-grid">
    <div class="kpi" style="border-color:#4CAF50"><div class="num" style="color:#2e7d32">{sk_total_revenue:,.0f} ฿</div><div class="label">ยอดขายรวม</div></div>
    <div class="kpi blue"><div class="num">{sk_total_cost:,.0f} ฿</div><div class="label">ต้นทุนรวม</div></div>
    <div class="kpi {'green' if sk_total_profit>=0 else 'red'}" style="border-color:{'#4CAF50' if sk_total_profit>=0 else '#f44336'}"><div class="num" style="color:{'#2e7d32' if sk_total_profit>=0 else '#b71c1c'}">{sk_total_profit:,.0f} ฿</div><div class="label">กำไรสุทธิ</div></div>
    <div class="kpi pink"><div class="num">{sk_pct}</div><div class="label">%กำไร</div></div>
    <div class="kpi orange"><div class="num">{sk_total_stock:,.0f} ฿</div><div class="label">สต็อกยกปีหน้า</div></div>
  </div>
  <div class="charts-grid">
    <div class="chart-card"><h3>💰 กำไร/ขาดทุน แต่ละสินค้า (฿)</h3><canvas id="sk-profitChart"></canvas></div>
    <div class="chart-card"><h3>📊 ต้นทุน vs รายได้</h3><canvas id="sk-costRevenueChart"></canvas></div>
  </div>
  <div class="section">
    <h3>📋 สรุปกำไร/ขาดทุน รายสินค้า</h3>
    <div style="overflow-x:auto"><table>
      <thead><tr><th>สินค้า</th><th>ยอดขาย (฿)</th><th>ต้นทุน (฿)</th><th>กำไร/ขาดทุน (฿)</th><th>%กำไร</th><th>สต็อกเหลือ (฿)</th><th>หมายเหตุ</th></tr></thead>
      <tbody id="sk-summaryBody"></tbody>
      <tfoot class="sk-foot"><tr><td>รวม</td><td>{sk_total_revenue:,.0f}</td><td>{sk_total_cost:,.0f}</td>
        <td class="{'profit-pos' if sk_total_profit>=0 else 'profit-neg'}">{sk_total_profit:+,.0f}</td>
        <td>{sk_pct}</td><td>{sk_total_stock:,.0f}</td><td></td></tr></tfoot>
    </table></div>
  </div>
  <div class="section">
    <h3>📅 ยอดขายรายวัน</h3>
    <div style="overflow-x:auto"><table>
      <thead><tr><th>วันที่</th><th>สินค้า</th><th>จำนวน</th><th>ยอดขาย (฿)</th><th>หมายเหตุ</th></tr></thead>
      <tbody id="sk-salesBody"></tbody>
    </table></div>
  </div>
  <!-- สินค้าคงเหลือ -->
  <div class="section">
    <h3>📦 สต็อกยกไปปีหน้า (มูลค่า {sk_total_stock:,.0f} ฿)</h3>
    <div style="overflow-x:auto"><table>
      <thead><tr><th>สินค้า</th><th>จำนวน</th><th>มูลค่า (฿)</th></tr></thead>
      <tbody id="sk-stockBody"></tbody>
      <tfoot id="sk-stockFoot" class="sk-foot"></tfoot>
    </table></div>
  </div>

  <!-- รายละเอียดต้นทุน — กราฟ -->
  <div class="section">
    <h3>🛒 วิเคราะห์ต้นทุน</h3>
    <div class="charts-grid" style="grid-template-columns:1fr 1fr;gap:16px">
      <div class="chart-card" style="padding:16px">
        <h3 style="font-size:.95rem;margin-bottom:8px">🥧 สัดส่วนต้นทุนแต่ละสินค้า</h3>
        <canvas id="sk-costDoughnut" style="max-height:280px"></canvas>
      </div>
      <div class="chart-card" style="padding:16px">
        <h3 style="font-size:.95rem;margin-bottom:8px">💰 ยอดขาย vs ต้นทุน (฿)</h3>
        <canvas id="sk-revCostChart" style="max-height:280px"></canvas>
      </div>
    </div>
    <div class="chart-card" style="padding:16px;margin-top:16px">
      <h3 style="font-size:.95rem;margin-bottom:8px">📈 %กำไรแต่ละสินค้า — สินค้าไหนคุ้มค่าที่สุด?</h3>
      <p style="font-size:.82em;color:#666;margin:-4px 0 8px">เขียว = กำไร | แดง = ขาดทุน (ยังขายไม่หมด/ลงทุนเพิ่ม)</p>
      <canvas id="sk-marginChart" style="max-height:220px"></canvas>
    </div>
    <div class="chart-card" style="padding:16px;margin-top:16px">
      <h3 style="font-size:.95rem;margin-bottom:8px">📊 รายการที่แพงที่สุด (ต้นทุนแต่ละรายการ)</h3>
      <canvas id="sk-costItemBar" style="max-height:320px"></canvas>
    </div>
    <details style="margin-top:16px">
      <summary style="cursor:pointer;font-weight:bold;padding:8px 0;color:#880E4F">▶ ดูตารางรายละเอียดต้นทุน</summary>
      <div style="overflow-x:auto;margin-top:8px"><table>
        <thead><tr><th>สินค้า</th><th>รายการ</th><th>จำนวน</th><th>หน่วย</th><th>ต้นทุน (฿)</th></tr></thead>
        <tbody id="sk-costBody"></tbody>
        <tfoot id="sk-costFoot" class="sk-foot"></tfoot>
      </table></div>
    </details>
  </div>

  <div class="section">
    <h3>💡 วิเคราะห์ & คำแนะนำปีหน้า</h3>
    <div id="sk-tipsBox"></div>
  </div>
</div>
</div>

<!-- ════════ Generic Businesses (Auto-Generated) ════════ -->
{generic_tab_divs}

<!-- 🤖 AI Chat Bubble + Panel -->
<button id="ai-bubble" onclick="aiToggle()" title="ถาม AI"
  style="position:fixed;bottom:20px;right:20px;z-index:9000;width:60px;height:60px;border-radius:50%;border:none;background:linear-gradient(135deg,#6366f1,#8b5cf6);color:white;font-size:1.8em;cursor:pointer;box-shadow:0 6px 20px rgba(99,102,241,.4);transition:.2s">
  🤖
</button>
<div id="ai-panel" style="display:none;position:fixed;bottom:90px;right:20px;z-index:9001;width:380px;max-width:calc(100vw - 40px);height:520px;max-height:calc(100vh - 120px);background:white;border-radius:16px;box-shadow:0 10px 40px rgba(0,0,0,.25);overflow:hidden;flex-direction:column;font-family:inherit">
  <div style="background:linear-gradient(135deg,#6366f1,#8b5cf6);color:white;padding:14px 18px;display:flex;align-items:center;justify-content:space-between">
    <div>
      <div style="font-weight:700">🤖 AI Assistant</div>
      <div style="font-size:.75em;opacity:.85">Gemini 2.5 Flash · ถามได้ทุกเรื่องในระบบ</div>
    </div>
    <button onclick="aiToggle()" style="background:rgba(255,255,255,.2);border:none;color:white;width:28px;height:28px;border-radius:50%;cursor:pointer;font-size:1em">✕</button>
  </div>
  <div id="ai-messages" style="flex:1;overflow-y:auto;padding:14px 16px;background:#f7f8fc;font-size:.9em;line-height:1.55"></div>
  <div id="ai-quick" style="padding:8px 12px;background:#fff;border-top:1px solid #e5e7eb;display:flex;gap:6px;flex-wrap:wrap"></div>
  <div style="padding:10px 12px;background:#fff;border-top:1px solid #e5e7eb;display:flex;gap:8px">
    <input id="ai-input" type="text" placeholder="ถาม AI เช่น 'เดือนไหนยอดสูงสุด?'"
      style="flex:1;padding:10px 12px;border:1.5px solid #e5e7eb;border-radius:8px;font-size:.9em;font-family:inherit;outline:none"
      onkeydown="if(event.key==='Enter')aiAsk()">
    <button onclick="aiAsk()" style="background:#6366f1;color:white;border:none;padding:10px 18px;border-radius:8px;cursor:pointer;font-weight:600">ส่ง</button>
  </div>
</div>

<script>
// ═══════════════════════════════════════════════════════
// DATA
// ═══════════════════════════════════════════════════════
const rAllData   = {r_data_j};
const rYearData  = {r_year_j};
const rMonthData = {r_month_j};
const rAllYears  = {r_years_j};
const reRooms    = {rooms_j};
const reIncomes  = {incomes_j};
const reWater    = {water_j};
const reExpiring = {exp_j};
const reAlerts   = {ral_j};
const skSummaries  = {sk_sum_j};
const skSales      = {sk_sales_j};
const skCosts      = {sk_costs_j};
const skStockItems = {sk_stock_items_j};
const skTotalRevenue = {sk_total_revenue};
const skTotalCost    = {sk_total_cost};
const skTotalProfit  = {sk_total_profit};
const skTotalStock   = {sk_total_stock};
const GENERIC_BIZ    = {generic_biz_j};
const GENERIC_KEYS   = {generic_keys_js};

const fmt  = n => (+n||0).toLocaleString('th-TH',{{minimumFractionDigits:0,maximumFractionDigits:0}});
const fmtD = n => (+n||0).toLocaleString('th-TH',{{minimumFractionDigits:2,maximumFractionDigits:2}});
const fmtP = n => (+n||0).toFixed(2);
// Professional Accounting Format — ติดลบแสดงเป็น (1,100) สีแดง, ศูนย์แสดง "-"
const fmtAcc = (n, decimals=0) => {{
  const v = +n||0;
  if (v === 0) return '<span style="color:#9ca3af">-</span>';
  const abs = Math.abs(v).toLocaleString('th-TH',{{minimumFractionDigits:decimals,maximumFractionDigits:decimals}});
  return v < 0
    ? `<span style="color:#dc2626">(${{abs}})</span>`
    : `<span style="color:#059669">${{abs}}</span>`;
}};
// Colored delta (สำหรับ YoY %) — บวกเขียว ลบแดง พร้อมลูกศร
const fmtDelta = (pct) => {{
  const v = +pct||0;
  if (!isFinite(v) || v === 0) return '<span style="color:#9ca3af">—</span>';
  const arrow = v > 0 ? '▲' : '▼';
  const color = v > 0 ? '#059669' : '#dc2626';
  return `<span style="color:${{color}};font-weight:600">${{arrow}} ${{Math.abs(v).toFixed(1)}}%</span>`;
}};

// ═══════════════════════════════════════════════════════
// OVERVIEW
// ═══════════════════════════════════════════════════════
function initOverview() {{
  const thisYear = new Date().getFullYear();       // 2026
  const lastYear = thisYear - 1;                   // 2025

  // ── สวนยาง ──
  const rubberAll  = rAllData.reduce((s,d)=>s+d.owner,0);
  const rubberThis = rAllData.filter(d=>d.year===thisYear).reduce((s,d)=>s+d.owner,0);
  const rubberLast = rAllData.filter(d=>d.year===lastYear).reduce((s,d)=>s+d.owner,0);
  const rubberAvgPrice = rAllData.length ? rAllData.reduce((s,d)=>s+d.price,0)/rAllData.length : 0;

  const rubberYoY = rubberLast>0 ? ((rubberThis-rubberLast)/rubberLast*100) : 0;
  document.getElementById('ov-rubberKpi').innerHTML = `
    <div class="biz-kpi green"><div class="bk-num">${{fmt(rubberAll)}} ฿</div><div class="bk-label">รายได้สะสมทั้งหมด</div></div>
    <div class="biz-kpi green"><div class="bk-num">${{fmt(rubberThis)}} ฿</div><div class="bk-label">ปีนี้ (${{thisYear+543}}) <br>${{fmtDelta(rubberYoY)}} YoY</div></div>
    <div class="biz-kpi gray"><div class="bk-num">${{fmt(rubberLast)}} ฿</div><div class="bk-label">ปีที่แล้ว (${{lastYear+543}})</div></div>
    <div class="biz-kpi orange"><div class="bk-num">${{rAllData.length}} รอบ</div><div class="bk-label">จำนวนรอบทั้งหมด</div></div>
    <div class="biz-kpi orange"><div class="bk-num">${{rubberAvgPrice.toFixed(2)}} ฿/กก.</div><div class="bk-label">ราคาเฉลี่ยตลอดกาล</div></div>
  `;

  // ── ห้องเช่า ──
  const rentalAll  = reIncomes.reduce((s,i)=>s+i.amount,0);
  const rentalThis = reIncomes.filter(i=>i.date.startsWith(String(thisYear))).reduce((s,i)=>s+i.amount,0);
  const rentalLast = reIncomes.filter(i=>i.date.startsWith(String(lastYear))).reduce((s,i)=>s+i.amount,0);
  const monthlyRent= reRooms.reduce((s,r)=>s+r.rent,0);
  const occupied   = reRooms.filter(r=>r.status==='เช่าอยู่').length;

  const rentalYoY = rentalLast>0 ? ((rentalThis-rentalLast)/rentalLast*100) : 0;
  document.getElementById('ov-rentalKpi').innerHTML = `
    <div class="biz-kpi blue"><div class="bk-num">${{fmt(rentalAll)}} ฿</div><div class="bk-label">รายรับสะสมทั้งหมด</div></div>
    <div class="biz-kpi blue"><div class="bk-num">${{fmt(rentalThis)}} ฿</div><div class="bk-label">ปีนี้ (${{thisYear+543}}) <br>${{fmtDelta(rentalYoY)}} YoY</div></div>
    <div class="biz-kpi gray"><div class="bk-num">${{fmt(rentalLast)}} ฿</div><div class="bk-label">ปีที่แล้ว (${{lastYear+543}})</div></div>
    <div class="biz-kpi purple"><div class="bk-num">${{fmt(monthlyRent)}} ฿/เดือน</div><div class="bk-label">รายรับเต็มที่/เดือน</div></div>
    <div class="biz-kpi blue"><div class="bk-num">${{occupied}}/${{reRooms.length}}</div><div class="bk-label">ห้องที่เช่าอยู่</div></div>
  `;

  // ── สงกราน (ใช้ค่าจาก sheet แถว "รวมทั้งหมด" ซึ่งรวมมูลค่าสต็อกแล้ว) ──
  const skRev    = skTotalRevenue;
  const skCost   = skTotalCost;
  const skProfit = skTotalProfit;
  const skStock  = skTotalStock;
  const skPct    = skRev>0 ? ((skProfit/skRev)*100).toFixed(1)+'%' : '-';

  document.getElementById('ov-songkranKpi').innerHTML = `
    <div class="biz-kpi pink"><div class="bk-num">${{fmt(skRev)}} ฿</div><div class="bk-label">ยอดขายรวม (2569)</div></div>
    <div class="biz-kpi pink"><div class="bk-num">${{fmt(skCost)}} ฿</div><div class="bk-label">ต้นทุนรวม</div></div>
    <div class="biz-kpi ${{skProfit>=0?'green':'red'}}"><div class="bk-num">${{fmt(skProfit)}} ฿</div><div class="bk-label">กำไรสุทธิ</div></div>
    <div class="biz-kpi orange"><div class="bk-num">${{skPct}}</div><div class="bk-label">%กำไร</div></div>
    <div class="biz-kpi gray"><div class="bk-num">${{fmt(skStock)}} ฿</div><div class="bk-label">สต็อกยกปีหน้า</div></div>
  `;

  // ── กราฟเปรียบเทียบรายปี ──
  const compareLabels = [`${{lastYear+543}} (${{lastYear}})`, `${{thisYear+543}} (${{thisYear}})`];
  new Chart(document.getElementById('ov-compareChart'), {{
    type: 'bar',
    data: {{
      labels: compareLabels,
      datasets: [
        {{ label:'🌿 สวนยาง (เจ้าของสวน)', data:[rubberLast,rubberThis], backgroundColor:'rgba(76,175,80,.8)', borderColor:'rgba(76,175,80,1)', borderWidth:1 }},
        {{ label:'🏠 ห้องเช่า (ค่าเช่า)', data:[rentalLast,rentalThis], backgroundColor:'rgba(21,101,192,.8)', borderColor:'rgba(21,101,192,1)', borderWidth:1 }},
        {{ label:'🎊 สงกราน (กำไร)', data:[0,skProfit], backgroundColor:'rgba(233,30,99,.7)', borderColor:'rgba(233,30,99,1)', borderWidth:1 }},
      ]
    }},
    options: {{
      responsive: true,
      
      plugins: {{ legend: {{ position:'top' }} }},
      scales: {{ y: {{ beginAtZero:true, ticks: {{ callback: v => fmt(v) }} }} }}
    }}
  }});

  // ── กราฟ Pie รายได้รวมทุกธุรกิจ ──
  new Chart(document.getElementById('ov-pieChart'), {{
    type: 'doughnut',
    data: {{
      labels: ['🌿 สวนยาง', '🏠 ห้องเช่า', '🎊 สงกราน (กำไร)'],
      datasets: [{{ data:[rubberAll, rentalAll, Math.max(skProfit,0)],
        backgroundColor:['rgba(76,175,80,.85)','rgba(21,101,192,.85)','rgba(233,30,99,.85)'],borderWidth:2 }}]
    }},
    options:{{ responsive:true, plugins:{{ legend:{{ position:'bottom' }} }} }}
  }});

  // ── กราฟรายเดือนรวมทุกธุรกิจ (Stacked) ──
  const stackRubberMap = {{}};
  const stackRentalMap = {{}};
  const stackSkMap     = {{}};
  rAllData.forEach(d=>{{ const m=d.date_raw.substring(0,7); stackRubberMap[m]=(stackRubberMap[m]||0)+d.owner; }});
  reIncomes.forEach(i=>{{ const m=i.date.substring(0,7); if(m) stackRentalMap[m]=(stackRentalMap[m]||0)+i.amount; }});
  // สงกราน → map ปีพุทธ → เมษา ของปี ค.ศ.
  skSales.forEach(s=>{{
    if(!s.year) return;
    const yr = parseInt(s.year) - 543;
    if(isNaN(yr)) return;
    const m = yr + '-04';
    stackSkMap[m] = (stackSkMap[m]||0) + (s.revenue||0);
  }});
  const mKeys = [...new Set([...Object.keys(stackRubberMap),...Object.keys(stackRentalMap),...Object.keys(stackSkMap)])].sort();
  new Chart(document.getElementById('ov-monthChart'), {{
    type: 'bar',
    data: {{
      labels: mKeys,
      datasets: [
        {{ label:'🌿 สวนยาง', data:mKeys.map(m=>stackRubberMap[m]||0),
          backgroundColor:'rgba(76,175,80,.85)', borderColor:'rgba(76,175,80,1)', borderWidth:1 }},
        {{ label:'🏠 ห้องเช่า', data:mKeys.map(m=>stackRentalMap[m]||0),
          backgroundColor:'rgba(21,101,192,.85)', borderColor:'rgba(21,101,192,1)', borderWidth:1 }},
        {{ label:'🎊 สงกราน', data:mKeys.map(m=>stackSkMap[m]||0),
          backgroundColor:'rgba(233,30,99,.8)', borderColor:'rgba(233,30,99,1)', borderWidth:1 }},
      ]
    }},
    options:{{ responsive:true,
      plugins:{{ legend:{{ position:'top' }} }},
      scales:{{ x:{{ stacked:true }}, y:{{ stacked:true, ticks:{{ callback:v=>fmt(v) }} }} }}
    }}
  }});

  // ── ตารางสรุป ──
  const tbl = document.getElementById('ov-table');
  tbl.innerHTML = `
    <thead><tr>
      <th>ธุรกิจ</th>
      <th>รายได้/กำไรสะสม (฿)</th>
      <th>ปีที่แล้ว (${{lastYear+543}}) (฿)</th>
      <th>ปีนี้ (${{thisYear+543}}) (฿)</th>
      <th>สถานะ</th>
    </tr></thead>
    <tbody>
      <tr>
        <td><b>🌿 สวนยาง</b></td>
        <td>${{fmt(rubberAll)}}</td>
        <td>${{fmt(rubberLast)}}</td>
        <td>${{fmt(rubberThis)}}</td>
        <td><span class="sbadge ok">Active</span></td>
      </tr>
      <tr>
        <td><b>🏠 ห้องเช่า</b></td>
        <td>${{fmt(rentalAll)}}</td>
        <td>${{fmt(rentalLast)}}</td>
        <td>${{fmt(rentalThis)}}</td>
        <td><span class="sbadge ok">Active ${{occupied}}/${{reRooms.length}}</span></td>
      </tr>
      <tr>
        <td><b>🎊 สงกราน</b></td>
        <td>${{fmt(skProfit)}} (กำไร)</td>
        <td>—</td>
        <td>${{fmt(skProfit)}}</td>
        <td><span class="sbadge ok">Seasonal</span></td>
      </tr>
    </tbody>
    <tfoot><tr>
      <td><b>รวมทั้งหมด</b></td>
      <td><b>${{fmt(rubberAll+rentalAll+Math.max(skProfit,0))}}</b></td>
      <td><b>${{fmt(rubberLast+rentalLast)}}</b></td>
      <td><b>${{fmt(rubberThis+rentalThis+Math.max(skProfit,0))}}</b></td>
      <td></td>
    </tr></tfoot>
  `;

  // ══════════ 📈 Trend 12 เดือนล่าสุด + 💰 Cash Flow ══════════
  // สร้างรายการ 12 เดือนล่าสุด (YYYY-MM) ย้อนหลังจากเดือนปัจจุบัน
  const now = new Date();
  const months12 = [];
  for (let i=11; i>=0; i--) {{
    const d = new Date(now.getFullYear(), now.getMonth()-i, 1);
    months12.push(`${{d.getFullYear()}}-${{String(d.getMonth()+1).padStart(2,'0')}}`);
  }}
  const thMonthShort = (ym) => {{
    const [y,m] = ym.split('-');
    const names = ['ม.ค.','ก.พ.','มี.ค.','เม.ย.','พ.ค.','มิ.ย.','ก.ค.','ส.ค.','ก.ย.','ต.ค.','พ.ย.','ธ.ค.'];
    return `${{names[+m-1]}} ${{(+y+543)%100}}`;
  }};
  // รวม inflow รายเดือน
  const rubberMonthMap = {{}}, rentalMonthMap = {{}};
  rAllData.forEach(d=>{{ const m=d.date_raw.substring(0,7); rubberMonthMap[m]=(rubberMonthMap[m]||0)+d.owner; }});
  reIncomes.forEach(i=>{{ const m=i.date.substring(0,7); if(m) rentalMonthMap[m]=(rentalMonthMap[m]||0)+i.amount; }});
  const rubber12 = months12.map(m => rubberMonthMap[m]||0);
  const rental12 = months12.map(m => rentalMonthMap[m]||0);
  const total12  = months12.map((_,i) => rubber12[i]+rental12[i]);

  // 📈 Linear Regression Forecasting — ทำนาย 3 เดือนข้างหน้า
  // ใช้เฉพาะข้อมูลที่ไม่ใช่ 0 (เดือนที่ไม่มีข้อมูล exclude เพื่อไม่บิดเบือนเทรนด์)
  const _linReg = (vals) => {{
    const pts = vals.map((y,i)=>({{x:i,y}})).filter(p=>p.y>0);
    if (pts.length < 3) return null;  // ข้อมูลน้อย — ไม่ทำนาย
    const n = pts.length;
    const sx = pts.reduce((s,p)=>s+p.x,0), sy = pts.reduce((s,p)=>s+p.y,0);
    const sxy = pts.reduce((s,p)=>s+p.x*p.y,0), sxx = pts.reduce((s,p)=>s+p.x*p.x,0);
    const slope = (n*sxy - sx*sy) / (n*sxx - sx*sx);
    const intercept = (sy - slope*sx) / n;
    return x => Math.max(0, slope*x + intercept);
  }};
  const _forecast = (vals, steps=3) => {{
    const fn = _linReg(vals);
    if (!fn) return [];
    const out = [];
    for (let i=0; i<steps; i++) out.push(fn(vals.length + i));
    return out;
  }};
  // ทำนาย 3 เดือนข้างหน้า + label เดือน
  const futureMonths = [];
  for (let i=1; i<=3; i++) {{
    const d = new Date(now.getFullYear(), now.getMonth()+i, 1);
    futureMonths.push(`${{d.getFullYear()}}-${{String(d.getMonth()+1).padStart(2,'0')}}`);
  }}
  const allLabels = months12.concat(futureMonths).map(thMonthShort);
  const padNulls = (arr, head, tail) => Array(head).fill(null).concat(arr).concat(Array(tail).fill(null));
  // Forecast ค่าจริงเดือนสุดท้ายเป็นจุดเริ่ม → ดูต่อเนื่อง
  const rubberFc = _forecast(rubber12, 3);
  const rentalFc = _forecast(rental12, 3);
  const totalFc  = rubberFc.length===3 && rentalFc.length===3 ? rubberFc.map((v,i)=>v+rentalFc[i]) : [];
  // dataset สำหรับ forecast: null 12 ตัวแรก + ค่าจริงเดือนสุดท้าย + ค่าทำนาย → ลากต่อเนื่อง
  const fcDataset = (real, fc, color) => fc.length===0 ? null : {{
    label: 'ทำนาย', data: padNulls([real[real.length-1]].concat(fc), 11, 0),
    borderColor: color, backgroundColor: 'transparent', borderDash: [8,5], pointStyle: 'triangle', pointRadius: 5, tension: .3, fill: false
  }};

  // กราฟ Trend 12 เดือน + 3 เดือนทำนาย (เส้นประ)
  const trendDatasets = [
    {{ label:'🌿 สวนยาง', data:padNulls(rubber12,0,3), borderColor:'rgba(76,175,80,1)', backgroundColor:'rgba(76,175,80,.15)', fill:true, tension:.3 }},
    {{ label:'🏠 ห้องเช่า', data:padNulls(rental12,0,3), borderColor:'rgba(21,101,192,1)', backgroundColor:'rgba(21,101,192,.15)', fill:true, tension:.3 }},
    {{ label:'💰 รวม', data:padNulls(total12,0,3), borderColor:'rgba(55,71,79,1)', backgroundColor:'rgba(55,71,79,.05)', borderDash:[6,4], tension:.3, fill:false }},
  ];
  const fcRubber = fcDataset(rubber12, rubberFc, 'rgba(76,175,80,.9)');
  const fcRental = fcDataset(rental12, rentalFc, 'rgba(21,101,192,.9)');
  const fcTotal  = fcDataset(total12, totalFc, 'rgba(55,71,79,.9)');
  if (fcRubber) trendDatasets.push({{...fcRubber, label:'🌿 ทำนาย'}});
  if (fcRental) trendDatasets.push({{...fcRental, label:'🏠 ทำนาย'}});
  if (fcTotal)  trendDatasets.push({{...fcTotal,  label:'💰 ทำนาย'}});

  new Chart(document.getElementById('ov-trend12Chart'), {{
    type: 'line',
    data: {{
      labels: allLabels,
      datasets: trendDatasets
    }},
    options: {{
      responsive: true,
      
      plugins: {{
        legend: {{ position:'top' }},
        tooltip: {{ callbacks: {{ label: ctx => ` ${{ctx.dataset.label}}: ${{fmt(ctx.parsed.y)}} ฿` }} }}
      }},
      scales: {{ y: {{ beginAtZero:true, ticks: {{ callback: v => fmt(v) }} }} }}
    }}
  }});

  // ตาราง Cash Flow (รายเดือน 12 เดือน)
  const cf = document.getElementById('ov-cashflow');
  let cfRows = '';
  let sumIn=0, sumOut=0;
  months12.forEach((m,i) => {{
    const inflow = total12[i];           // เข้า (จริง ๆ ยังไม่มี outflow — reserve for future)
    const outflow = 0;                    // TODO: เชื่อมต้นทุนจริงเมื่อมีข้อมูล
    const net = inflow - outflow;
    sumIn += inflow; sumOut += outflow;
    cfRows += `<tr>
      <td>${{thMonthShort(m)}}</td>
      <td>${{fmtAcc(inflow)}}</td>
      <td>${{fmtAcc(-outflow)}}</td>
      <td><b>${{fmtAcc(net)}}</b></td>
    </tr>`;
  }});
  cf.innerHTML = `
    <thead><tr>
      <th>เดือน</th>
      <th>กระแสเงินเข้า (฿)</th>
      <th>กระแสเงินออก (฿)</th>
      <th>สุทธิ (฿)</th>
    </tr></thead>
    <tbody>${{cfRows}}</tbody>
    <tfoot><tr>
      <td><b>รวม 12 เดือน</b></td>
      <td><b>${{fmtAcc(sumIn)}}</b></td>
      <td><b>${{fmtAcc(-sumOut)}}</b></td>
      <td><b>${{fmtAcc(sumIn-sumOut)}}</b></td>
    </tr></tfoot>
  `;

  // ══════════ 🏆 Business Health Score ══════════
  // ฟังก์ชันคำนวณคะแนน 4 มิติ (แต่ละมิติ 0-100)
  const _clamp = (v, lo=0, hi=100) => Math.max(lo, Math.min(hi, v));
  const _scoreYoY = pct => _clamp((pct + 20) / 40 * 100);  // -20%→0, +20%→100
  const _scoreStability = (monthlyVals) => {{
    if (monthlyVals.length < 3) return 50;  // ข้อมูลน้อย: กลาง ๆ
    const mean = monthlyVals.reduce((s,v)=>s+v,0) / monthlyVals.length;
    if (mean === 0) return 0;
    const variance = monthlyVals.reduce((s,v)=>s+(v-mean)**2, 0) / monthlyVals.length;
    const cv = Math.sqrt(variance) / mean;  // coefficient of variation
    return _clamp(100 - cv * 100);  // CV 0→100, CV 1→0
  }};
  const _grade = score => {{
    if (score >= 85) return {{letter:'A', label:'แข็งแกร่ง', color:'#059669', bg:'#d1fae5'}};
    if (score >= 70) return {{letter:'B', label:'ดี',         color:'#0284c7', bg:'#dbeafe'}};
    if (score >= 55) return {{letter:'C', label:'พอใช้',     color:'#ea580c', bg:'#fed7aa'}};
    return            {{letter:'D', label:'ต้องปรับ',         color:'#dc2626', bg:'#fee2e2'}};
  }};
  const _rec = (g, biz) => {{
    if (g.letter==='A') return `🌟 <b>${{biz}}</b> อยู่ในเกณฑ์แข็งแกร่ง — รักษามาตรฐานปัจจุบัน`;
    if (g.letter==='B') return `👍 <b>${{biz}}</b> ผลประกอบการดี — มองหาโอกาสขยายเพิ่ม`;
    if (g.letter==='C') return `⚠️ <b>${{biz}}</b> พอใช้ — พิจารณาลดต้นทุนหรือเพิ่มยอดขาย`;
    return `🚨 <b>${{biz}}</b> ต้องปรับด่วน — ทบทวน strategy ทั้งระบบ`;
  }};

  // เก็บ score ของแต่ละธุรกิจ
  const healthData = [];

  // ─── สวนยาง ───
  {{
    const profitability = rubberAll>0
      ? _clamp((rAllData.reduce((s,d)=>s+d.owner,0) / rAllData.reduce((s,d)=>s+(d.sale||d.owner),0)) * 100 * 1.5)
      : 50;
    const growth = _scoreYoY(rubberYoY);
    const monthlyVals = Object.values(rubberMonthMap);
    const stability = _scoreStability(monthlyVals);
    const cashflow = monthlyVals.length>0 ? _clamp(monthlyVals.filter(v=>v>0).length / monthlyVals.length * 100) : 50;
    const total = (profitability + growth + stability + cashflow) / 4;
    healthData.push({{key:'rubber', name:'🌿 สวนยาง', color:'#4caf50',
      profitability, growth, stability, cashflow, total}});
  }}

  // ─── ห้องเช่า ───
  {{
    const totalPossible = monthlyRent * 12;
    const profitability = totalPossible>0 ? _clamp(rentalThis / totalPossible * 100) : 50;
    const growth = _scoreYoY(rentalYoY);
    const monthlyVals = Object.values(rentalMonthMap);
    const stability = _scoreStability(monthlyVals);
    const occupancyRate = reRooms.length>0 ? (occupied/reRooms.length*100) : 0;
    const cashflow = _clamp(occupancyRate);
    const total = (profitability + growth + stability + cashflow) / 4;
    healthData.push({{key:'rental', name:'🏠 ห้องเช่า', color:'#1565c0',
      profitability, growth, stability, cashflow, total}});
  }}

  // ─── สงกราน ───
  {{
    const profitability = skRev>0 ? _clamp((skProfit/skRev)*100 * 2.5) : 50;  // 40%→100
    const growth = 50;  // ปีเดียว ยังเทียบ YoY ไม่ได้
    const stability = 50;  // seasonal — ไม่ใช้ monthly
    const cashflow = skProfit>0 ? 100 : (skProfit===0 ? 50 : 0);
    const total = (profitability + growth + stability + cashflow) / 4;
    healthData.push({{key:'songkran', name:'🎊 สงกราน', color:'#e91e63',
      profitability, growth, stability, cashflow, total}});
  }}

  // ─── Generic businesses ───
  GENERIC_BIZ.forEach(b => {{
    const rTot = b.revenues.reduce((s,r)=>s+r.amount,0);
    const eTot = b.expenses.reduce((s,r)=>s+r.amount,0);
    const profit = rTot - eTot;
    const profitability = rTot>0 ? _clamp(profit/rTot*100 * 2) : 50;
    const rThis = b.revenues.filter(r=>r.date.startsWith(String(thisYear))).reduce((s,r)=>s+r.amount,0);
    const rLast = b.revenues.filter(r=>r.date.startsWith(String(lastYear))).reduce((s,r)=>s+r.amount,0);
    const yoy = rLast>0 ? ((rThis-rLast)/rLast*100) : 0;
    const growth = _scoreYoY(yoy);
    const mmap2 = {{}};
    b.revenues.forEach(r=>{{const m=r.date.substring(0,7);mmap2[m]=(mmap2[m]||0)+r.amount;}});
    const monthlyVals = Object.values(mmap2);
    const stability = _scoreStability(monthlyVals);
    const posMonths = Object.keys(mmap2).filter(m => {{
      const e = b.expenses.filter(x=>x.date.startsWith(m)).reduce((s,x)=>s+x.amount,0);
      return mmap2[m] - e > 0;
    }}).length;
    const cashflow = monthlyVals.length>0 ? _clamp(posMonths/monthlyVals.length*100) : 50;
    const total = (profitability + growth + stability + cashflow) / 4;
    healthData.push({{key:b.key, name:`${{b.emoji}} ${{b.name}}`, color:b.color,
      profitability, growth, stability, cashflow, total}});
  }});

  // ══════════ 🧠 Quick Insights (auto-generated) ══════════
  const insights = [];
  // 1) ธุรกิจไหนทำเงินเยอะสุดปีนี้
  const earnersThis = [
    {{name:'🌿 สวนยาง',  v: rubberThis}},
    {{name:'🏠 ห้องเช่า', v: rentalThis}},
    {{name:'🎊 สงกราน',  v: skProfit}},
    ...GENERIC_BIZ.map(b => ({{
      name: `${{b.emoji}} ${{b.name}}`,
      v: b.revenues.filter(r=>r.date.startsWith(String(thisYear))).reduce((s,r)=>s+r.amount,0)
    }}))
  ].filter(e => e.v > 0).sort((a,b)=>b.v-a.v);
  if (earnersThis.length > 0) {{
    insights.push(`💰 ปีนี้ <b>${{earnersThis[0].name}}</b> ทำเงินสูงสุด <b>${{fmt(earnersThis[0].v)}} ฿</b>`);
  }}

  // 2) เดือน peak (รายได้รวมสูงสุด 12 เดือนล่าสุด)
  if (months12.length === 12) {{
    let peakIdx = 0;
    for (let i=1; i<12; i++) if (total12[i] > total12[peakIdx]) peakIdx = i;
    if (total12[peakIdx] > 0) {{
      insights.push(`📈 เดือน Peak 12 เดือนล่าสุด: <b>${{thMonthShort(months12[peakIdx])}}</b> รายได้รวม <b>${{fmt(total12[peakIdx])}} ฿</b>`);
    }}
  }}

  // 3) YoY ของแต่ละธุรกิจ
  if (rubberLast > 0) {{
    const ydiff = rubberYoY;
    const emoji = ydiff > 0 ? '🚀' : '📉';
    insights.push(`${{emoji}} สวนยางปีนี้ <b>${{ydiff>=0?'+':''}}${{ydiff.toFixed(1)}}%</b> เทียบกับปีที่แล้ว (${{fmt(rubberLast)}} → ${{fmt(rubberThis)}} ฿)`);
  }}
  if (rentalLast > 0) {{
    const ydiff = rentalYoY;
    const emoji = ydiff > 0 ? '🚀' : '📉';
    insights.push(`${{emoji}} ห้องเช่าปีนี้ <b>${{ydiff>=0?'+':''}}${{ydiff.toFixed(1)}}%</b> เทียบกับปีที่แล้ว (${{fmt(rentalLast)}} → ${{fmt(rentalThis)}} ฿)`);
  }}

  // 4) ห้องที่ว่าง (ไม่มี tenant)
  const vacantRooms = reRooms.filter(r => r.status !== 'เช่าอยู่');
  if (vacantRooms.length > 0) {{
    insights.push(`🏚️ มีห้องว่าง <b>${{vacantRooms.length}} ห้อง</b>: ${{vacantRooms.map(r=>r.name).join(', ')}} — เสียโอกาสรายได้ <b>${{fmt(vacantRooms.reduce((s,r)=>s+r.rent,0))}} ฿/เดือน</b>`);
  }}

  // 5) ห้องใกล้หมดสัญญา (60 วัน)
  if (reExpiring.length > 0) {{
    insights.push(`⚠️ ห้องใกล้หมดสัญญา (60 วัน): <b>${{reExpiring.map(e=>e.room+' ('+e.days+' วัน)').join(', ')}}</b>`);
  }}

  // 6) ธุรกิจ Health Grade D
  // (จะ generate หลัง healthData ถูกสร้าง — render ทีหลัง)

  // 7) ราคายางเฉลี่ย
  if (rubberAvgPrice > 0) {{
    insights.push(`💵 ราคายางเฉลี่ยตลอดกาล <b>${{rubberAvgPrice.toFixed(2)}} ฿/กก.</b> (${{rAllData.length}} รอบ)`);
  }}

  // ─── Render Health Cards ───
  const healthCont = document.getElementById('ov-healthCards');
  let healthHtml = '';
  healthData.forEach(h => {{
    const g = _grade(h.total);
    const bar = (label, val, color) => `
      <div style="margin-bottom:6px">
        <div style="display:flex;justify-content:space-between;font-size:.78em;color:#555">
          <span>${{label}}</span><span><b>${{Math.round(val)}}</b>/100</span>
        </div>
        <div style="background:#f1f5f9;height:6px;border-radius:3px;overflow:hidden">
          <div style="width:${{val}}%;height:100%;background:${{color}};transition:width .6s"></div>
        </div>
      </div>`;
    healthHtml += `
      <div style="background:white;border-radius:12px;padding:18px;border:2px solid ${{g.bg}};box-shadow:0 2px 8px rgba(0,0,0,.04)">
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px">
          <div>
            <div style="font-weight:700;font-size:1.05em;color:#1a1a2e">${{h.name}}</div>
            <div style="font-size:.78em;color:#666;margin-top:2px">คะแนนรวม <b>${{Math.round(h.total)}}/100</b></div>
          </div>
          <div style="background:${{g.bg}};color:${{g.color}};width:54px;height:54px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-weight:900;font-size:1.6em">${{g.letter}}</div>
        </div>
        <div style="text-align:center;color:${{g.color}};font-weight:600;font-size:.88em;margin-bottom:12px">${{g.label}}</div>
        ${{bar('📈 ความสามารถทำกำไร', h.profitability, h.color)}}
        ${{bar('🚀 การเติบโต YoY', h.growth, h.color)}}
        ${{bar('🎯 ความสม่ำเสมอ', h.stability, h.color)}}
        ${{bar('💰 กระแสเงินสด', h.cashflow, h.color)}}
        <div style="margin-top:10px;padding:8px 10px;background:${{g.bg}}66;border-radius:8px;font-size:.78em;line-height:1.5">${{_rec(g, h.name)}}</div>
      </div>`;
  }});
  healthCont.innerHTML = healthHtml;

  // เพิ่ม insight: ธุรกิจ Grade D (จาก healthData)
  const gradeD = healthData.filter(h => h.total < 55);
  if (gradeD.length > 0) {{
    insights.push(`🚨 ธุรกิจที่ต้องปรับด่วน (Grade D): <b>${{gradeD.map(g=>g.name).join(', ')}}</b>`);
  }}
  const gradeA = healthData.filter(h => h.total >= 85);
  if (gradeA.length > 0) {{
    insights.push(`🌟 ธุรกิจแข็งแกร่ง (Grade A): <b>${{gradeA.map(g=>g.name).join(', ')}}</b>`);
  }}

  // ══════════ 🎯 Goals & Budget Tracking ══════════
  document.getElementById('ov-goalYear').textContent = thisYear+543;
  const goalsKey = `bosshub_goals_${{thisYear}}`;
  const goals = JSON.parse(localStorage.getItem(goalsKey) || '{{}}');

  // ค่าเริ่มต้น: ใช้ปีที่แล้ว × 1.1 ถ้ายังไม่ได้ตั้ง
  const defaultGoal = (last) => last > 0 ? Math.round(last * 1.1 / 1000) * 1000 : 0;
  const allBiz = [
    {{key:'rubber',  name:'🌿 สวนยาง',   actual: rubberThis, last: rubberLast, color:'#4caf50'}},
    {{key:'rental',  name:'🏠 ห้องเช่า', actual: rentalThis, last: rentalLast, color:'#1565c0'}},
    {{key:'songkran',name:'🎊 สงกราน',   actual: skProfit,   last: 0,          color:'#e91e63'}},
    ...GENERIC_BIZ.map(b => {{
      const a = b.revenues.filter(r=>r.date.startsWith(String(thisYear))).reduce((s,r)=>s+r.amount,0);
      const l = b.revenues.filter(r=>r.date.startsWith(String(lastYear))).reduce((s,r)=>s+r.amount,0);
      return {{key:b.key, name:`${{b.emoji}} ${{b.name}}`, actual:a, last:l, color:b.color}};
    }})
  ];

  const goalsHtml = allBiz.map(b => {{
    const goal = goals[b.key] || defaultGoal(b.last);
    if (goal === 0) {{
      return `<div style="background:#f9fafb;border-radius:10px;padding:14px 16px;margin-bottom:8px">
        <div style="display:flex;justify-content:space-between"><b>${{b.name}}</b><span style="color:#999;font-size:.85em">ยังไม่ได้ตั้งเป้า — กด ⚙️ ตั้งเป้า</span></div>
      </div>`;
    }}
    const pct = goal>0 ? (b.actual/goal*100) : 0;
    const barColor = pct >= 100 ? '#059669' : (pct >= 90 ? '#3b82f6' : (pct >= 70 ? '#f59e0b' : '#dc2626'));
    const status = pct >= 100 ? '🎉 ทะลุเป้า!' : (pct >= 90 ? '🟢 ใกล้เป้า' : (pct >= 70 ? '🟡 ตามแผน' : '🔴 ต่ำกว่าแผน'));
    return `
      <div style="background:white;border-radius:10px;padding:14px 16px;margin-bottom:10px;border-left:4px solid ${{b.color}};box-shadow:0 1px 3px rgba(0,0,0,.04)">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
          <div><b>${{b.name}}</b> <span style="color:#666;font-size:.85em;margin-left:6px">${{status}}</span></div>
          <div style="font-size:.95em"><b>${{fmt(b.actual)}}</b> / ${{fmt(goal)}} ฿ <span style="color:${{barColor}};font-weight:700;margin-left:6px">${{pct.toFixed(1)}}%</span></div>
        </div>
        <div style="background:#f1f5f9;height:10px;border-radius:5px;overflow:hidden">
          <div style="width:${{Math.min(pct,100)}}%;height:100%;background:${{barColor}};transition:width .8s"></div>
        </div>
      </div>`;
  }}).join('');
  document.getElementById('ov-goals').innerHTML = goalsHtml;
  window._goalsBiz = allBiz; window._goalsKey = goalsKey;

  // ══════════ 🧮 Thai Tax Estimator ══════════
  document.getElementById('ov-taxYear').textContent = thisYear+543;
  // รายได้สุทธิรวม (เงินได้พึงประเมินจากธุรกิจของปอง)
  // หมายเหตุ: ใช้รายได้-รายจ่ายแบบประมาณการ ปองอาจปรับให้ตรงกับการยื่นจริง
  const incomeRubber  = rubberThis;  // รายได้ส่วนเจ้าของจากยาง
  const incomeRental  = rentalThis;  // รายได้จากห้องเช่า
  const incomeSongkran= skProfit > 0 ? skProfit : 0;  // กำไรสุทธิ
  const incomeGeneric = GENERIC_BIZ.reduce((s,b) => {{
    const r = b.revenues.filter(x=>x.date.startsWith(String(thisYear))).reduce((s,x)=>s+x.amount,0);
    const e = b.expenses.filter(x=>x.date.startsWith(String(thisYear))).reduce((s,x)=>s+x.amount,0);
    return s + Math.max(0, r-e);
  }}, 0);
  const grossIncome = incomeRubber + incomeRental + incomeSongkran + incomeGeneric;

  // หักค่าใช้จ่าย (เหมา 60% สำหรับการเกษตร, 30% ห้องเช่า — เป็นการประมาณ)
  // เพื่อความง่าย ใช้หักเหมารวม 50% (ตัวเลขประมาณ)
  // หักลดหย่อนส่วนตัว 60,000 (พื้นฐาน)
  const expenseDeduction = grossIncome * 0.5;
  const personalDeduction = 60000;
  const netIncome = Math.max(0, grossIncome - expenseDeduction - personalDeduction);

  // อัตราภาษีก้าวหน้าไทย 2568 (สำหรับเงินได้สุทธิ)
  const brackets = [
    {{max:150000,    rate:0,    label:'0 - 150,000'}},
    {{max:300000,    rate:0.05, label:'150,001 - 300,000'}},
    {{max:500000,    rate:0.10, label:'300,001 - 500,000'}},
    {{max:750000,    rate:0.15, label:'500,001 - 750,000'}},
    {{max:1000000,   rate:0.20, label:'750,001 - 1,000,000'}},
    {{max:2000000,   rate:0.25, label:'1,000,001 - 2,000,000'}},
    {{max:5000000,   rate:0.30, label:'2,000,001 - 5,000,000'}},
    {{max:Infinity,  rate:0.35, label:'> 5,000,000'}},
  ];
  let tax = 0, prevMax = 0, breakdown = [];
  for (const b of brackets) {{
    if (netIncome <= prevMax) break;
    const taxable = Math.min(netIncome, b.max) - prevMax;
    const t = taxable * b.rate;
    if (taxable > 0) breakdown.push({{label:b.label, taxable, rate:b.rate, tax:t}});
    tax += t;
    prevMax = b.max;
  }}
  const effectiveRate = grossIncome > 0 ? (tax/grossIncome*100) : 0;

  document.getElementById('ov-taxCard').innerHTML = `
    <div style="background:white;border-radius:12px;padding:18px 20px;border-left:5px solid #6366f1;box-shadow:0 1px 3px rgba(0,0,0,.04)">
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin-bottom:14px">
        <div><div style="color:#666;font-size:.78em">รายได้รวมประมาณการ</div><div style="font-weight:700;font-size:1.1em">${{fmt(grossIncome)}} ฿</div></div>
        <div><div style="color:#666;font-size:.78em">หักค่าใช้จ่าย (50% เหมา)</div><div style="font-weight:600;color:#dc2626">-${{fmt(expenseDeduction)}} ฿</div></div>
        <div><div style="color:#666;font-size:.78em">หักลดหย่อนส่วนตัว</div><div style="font-weight:600;color:#dc2626">-${{fmt(personalDeduction)}} ฿</div></div>
        <div><div style="color:#666;font-size:.78em">เงินได้สุทธิ</div><div style="font-weight:700;font-size:1.1em">${{fmt(netIncome)}} ฿</div></div>
      </div>
      ${{breakdown.length > 0 ? `
        <table style="width:100%;border-collapse:collapse;font-size:.85em;margin-bottom:10px">
          <thead><tr style="background:#f7f8fc"><th style="padding:6px 10px;text-align:left">ช่วงเงินได้สุทธิ (฿)</th><th style="padding:6px 10px;text-align:right">อัตรา</th><th style="padding:6px 10px;text-align:right">เงินได้ในช่วง</th><th style="padding:6px 10px;text-align:right">ภาษี (฿)</th></tr></thead>
          <tbody>
            ${{breakdown.map(b => `<tr><td style="padding:5px 10px;border-bottom:1px solid #f1f5f9">${{b.label}}</td><td style="padding:5px 10px;text-align:right;border-bottom:1px solid #f1f5f9">${{(b.rate*100)}}%</td><td style="padding:5px 10px;text-align:right;border-bottom:1px solid #f1f5f9">${{fmt(b.taxable)}}</td><td style="padding:5px 10px;text-align:right;border-bottom:1px solid #f1f5f9">${{fmt(b.tax)}}</td></tr>`).join('')}}
          </tbody>
        </table>` : ''}}
      <div style="display:flex;justify-content:space-between;align-items:center;background:#eef2ff;padding:12px 16px;border-radius:8px;margin-top:10px">
        <div>
          <div style="font-size:.78em;color:#4f46e5">💰 ภาษีประมาณการที่ต้องชำระ</div>
          <div style="font-size:.78em;color:#9ca3af;margin-top:2px">อัตราภาษีเฉลี่ย ${{effectiveRate.toFixed(2)}}% ของรายได้รวม</div>
        </div>
        <div style="font-size:1.6em;font-weight:800;color:#4f46e5">${{fmt(tax)}} ฿</div>
      </div>
      <p style="color:#999;font-size:.75em;margin:10px 0 0;line-height:1.5">
        ⚠️ <b>ประมาณการเท่านั้น</b> — ใช้สูตรหักเหมา 50% + ลดหย่อนส่วนตัว 60,000 ฿<br>
        การคำนวณจริงอาจหักได้มากกว่านี้ (เช่น ประกันชีวิต RMF/SSF บุพการี ฯลฯ) — ปรึกษาบัญชีเพื่อยื่นจริง
      </p>
    </div>
  `;

  // Render Quick Insights
  const insBox = document.getElementById('ov-insights');
  if (insights.length > 0) {{
    insBox.innerHTML = `
      <div style="display:flex;align-items:center;gap:10px;margin-bottom:10px">
        <span style="font-size:1.4em">🧠</span>
        <h3 style="margin:0;color:#92400e;font-size:1.05em">Quick Insights — สิ่งที่น่ารู้วันนี้</h3>
      </div>
      <div style="display:grid;gap:6px;font-size:.92em;line-height:1.7;color:#451a03">
        ${{insights.map(i => `<div>• ${{i}}</div>`).join('')}}
      </div>
    `;
  }} else {{
    insBox.style.display = 'none';
  }}

  // ══════════ 🆕 Generic Businesses → Overview KPIs ══════════
  const genCont = document.getElementById('ov-genericKpiContainer');
  if (GENERIC_BIZ.length > 0 && genCont) {{
    let genHtml = '';
    GENERIC_BIZ.forEach(b => {{
      const rTot = b.revenues.reduce((s,r)=>s+r.amount,0);
      const eTot = b.expenses.reduce((s,r)=>s+r.amount,0);
      const profit = rTot - eTot;
      const rThis = b.revenues.filter(r=>r.date.startsWith(String(thisYear))).reduce((s,r)=>s+r.amount,0);
      const rLast = b.revenues.filter(r=>r.date.startsWith(String(lastYear))).reduce((s,r)=>s+r.amount,0);
      const yoy = rLast>0 ? ((rThis-rLast)/rLast*100) : 0;
      genHtml += `
        <div class="biz-group" style="border-left:6px solid ${{b.color}};background:${{b.color}}0d">
          <h3>${{b.emoji}} ${{b.name}}</h3>
          <div class="biz-kpi-row">
            <div class="biz-kpi" style="background:${{b.color}}1a;border-left:4px solid ${{b.color}}"><div class="bk-num">${{fmt(rTot)}} ฿</div><div class="bk-label">รายรับสะสม</div></div>
            <div class="biz-kpi gray"><div class="bk-num">${{fmt(eTot)}} ฿</div><div class="bk-label">รายจ่ายสะสม</div></div>
            <div class="biz-kpi ${{profit>=0?'green':'red'}}"><div class="bk-num">${{fmt(profit)}} ฿</div><div class="bk-label">กำไรสุทธิ</div></div>
            <div class="biz-kpi" style="background:${{b.color}}1a;border-left:4px solid ${{b.color}}"><div class="bk-num">${{fmt(rThis)}} ฿</div><div class="bk-label">ปีนี้ (${{thisYear+543}})<br>${{fmtDelta(yoy)}} YoY</div></div>
            <div class="biz-kpi gray"><div class="bk-num">${{fmt(rLast)}} ฿</div><div class="bk-label">ปีที่แล้ว (${{lastYear+543}})</div></div>
          </div>
        </div>`;
    }});
    genCont.innerHTML = genHtml;
  }}
}}

// ═══════════════════════════════════════════════════════
// TAB SWITCHING
// ═══════════════════════════════════════════════════════
const tabInited = {{}};
function switchTab(name) {{
  const allTabs = ['overview','rubber','rental','songkran'].concat(GENERIC_KEYS);
  allTabs.forEach(t => {{
    const el = document.getElementById('tab-'+t);
    const bt = document.getElementById('btn-'+t);
    if (el) el.style.display = t===name ? '' : 'none';
    if (bt) bt.classList.toggle('active', t===name);
  }});
  if (!tabInited[name]) {{
    tabInited[name] = true;
    if (name==='overview')  initOverview();
    else if (name==='rubber')    renderRubber();
    else if (name==='rental')    initRental();
    else if (name==='songkran')  initSongkran();
    else {{
      const cfg = GENERIC_BIZ.find(b => b.key===name);
      if (cfg) initGenericBiz(cfg);
    }}
  }}
}}

// ═══════════════════════════════════════════════════════
// GENERIC BUSINESS RENDERER (รองรับธุรกิจใหม่ไม่จำกัด)
// ═══════════════════════════════════════════════════════
function initGenericBiz(cfg) {{
  const k = cfg.key;
  const revs = cfg.revenues || [];
  const exps = cfg.expenses || [];
  const thisYear = new Date().getFullYear();
  const lastYear = thisYear - 1;

  const sumBy = (arr, yr) => arr.filter(r => r.date && r.date.startsWith(String(yr))).reduce((s,r)=>s+r.amount,0);
  const totalRev  = revs.reduce((s,r)=>s+r.amount,0);
  const totalExp  = exps.reduce((s,r)=>s+r.amount,0);
  const profit    = totalRev - totalExp;
  const revThis   = sumBy(revs, thisYear);
  const revLast   = sumBy(revs, lastYear);
  const expThis   = sumBy(exps, thisYear);
  const expLast   = sumBy(exps, lastYear);
  const profitThis= revThis - expThis;
  const profitLast= revLast - expLast;
  const yoyRev    = revLast>0 ? ((revThis-revLast)/revLast*100) : 0;
  const yoyProfit = profitLast!==0 ? ((profitThis-profitLast)/Math.abs(profitLast)*100) : 0;

  // KPIs
  document.getElementById(`gb-${{k}}-kpi`).innerHTML = `
    <div class="biz-kpi" style="background:${{cfg.color}}1a;border-left:4px solid ${{cfg.color}}">
      <div class="bk-num">${{fmt(totalRev)}} ฿</div><div class="bk-label">รายรับสะสม</div></div>
    <div class="biz-kpi gray">
      <div class="bk-num">${{fmt(totalExp)}} ฿</div><div class="bk-label">รายจ่ายสะสม</div></div>
    <div class="biz-kpi ${{profit>=0?'green':'red'}}">
      <div class="bk-num">${{fmt(profit)}} ฿</div><div class="bk-label">กำไรสุทธิสะสม</div></div>
    <div class="biz-kpi" style="background:${{cfg.color}}1a;border-left:4px solid ${{cfg.color}}">
      <div class="bk-num">${{fmt(revThis)}} ฿</div><div class="bk-label">รายรับปีนี้ (${{thisYear+543}})<br>${{fmtDelta(yoyRev)}} YoY</div></div>
    <div class="biz-kpi ${{profitThis>=0?'green':'red'}}">
      <div class="bk-num">${{fmt(profitThis)}} ฿</div><div class="bk-label">กำไรปีนี้<br>${{fmtDelta(yoyProfit)}} YoY</div></div>
  `;

  // Monthly revenue vs expense
  const mmap = {{}};
  revs.forEach(r => {{ const m=r.date.substring(0,7); if(!mmap[m]) mmap[m]={{r:0,e:0}}; mmap[m].r+=r.amount; }});
  exps.forEach(r => {{ const m=r.date.substring(0,7); if(!mmap[m]) mmap[m]={{r:0,e:0}}; mmap[m].e+=r.amount; }});
  const months = Object.keys(mmap).sort();
  new Chart(document.getElementById(`gb-${{k}}-monthChart`), {{
    type:'bar',
    data:{{labels:months,datasets:[
      {{label:'รายรับ',data:months.map(m=>mmap[m].r),backgroundColor:cfg.color+'cc'}},
      {{label:'รายจ่าย',data:months.map(m=>mmap[m].e),backgroundColor:'rgba(220,38,38,.7)'}}
    ]}},
    options:{{responsive:true,plugins:{{legend:{{position:'top'}}}},scales:{{y:{{beginAtZero:true,ticks:{{callback:v=>fmt(v)}}}}}}}}
  }});

  // Year compare
  const yset = new Set([...revs.map(r=>r.date.substring(0,4)), ...exps.map(r=>r.date.substring(0,4))].filter(Boolean));
  const years = [...yset].sort();
  new Chart(document.getElementById(`gb-${{k}}-yearChart`), {{
    type:'bar',
    data:{{labels:years.map(y=>+y+543),datasets:[
      {{label:'รายรับ',data:years.map(y=>sumBy(revs,+y)),backgroundColor:cfg.color+'cc'}},
      {{label:'รายจ่าย',data:years.map(y=>sumBy(exps,+y)),backgroundColor:'rgba(220,38,38,.7)'}},
      {{label:'กำไร',data:years.map(y=>sumBy(revs,+y)-sumBy(exps,+y)),backgroundColor:'rgba(76,175,80,.7)'}}
    ]}},
    options:{{responsive:true,plugins:{{legend:{{position:'top'}}}},scales:{{y:{{ticks:{{callback:v=>fmt(v)}}}}}}}}
  }});

  // Expense pie by item
  const expByItem = {{}};
  exps.forEach(e => {{ const k2=e.item||'อื่น ๆ'; expByItem[k2]=(expByItem[k2]||0)+e.amount; }});
  const eLabels = Object.keys(expByItem).sort((a,b)=>expByItem[b]-expByItem[a]).slice(0,10);
  const palette = ['#ef4444','#f97316','#f59e0b','#eab308','#84cc16','#22c55e','#14b8a6','#06b6d4','#3b82f6','#8b5cf6'];
  new Chart(document.getElementById(`gb-${{k}}-expPie`), {{
    type:'doughnut',
    data:{{labels:eLabels,datasets:[{{data:eLabels.map(l=>expByItem[l]),backgroundColor:palette}}]}},
    options:{{responsive:true,plugins:{{legend:{{position:'bottom'}},tooltip:{{callbacks:{{label:c=>` ${{c.label}}: ${{fmt(c.parsed)}} ฿`}}}}}}}}
  }});

  // Transaction table — รายการล่าสุด 50 ตัว (รวม รายรับ+รายจ่าย)
  const allTxn = revs.map(r=>({{...r,type:'รายรับ'}})).concat(exps.map(e=>({{...e,type:'รายจ่าย'}})));
  allTxn.sort((a,b)=>b.date.localeCompare(a.date));
  const recent = allTxn.slice(0,50);
  let trows = '';
  recent.forEach(t => {{
    const sign = t.type==='รายรับ' ? '+' : '-';
    const color = t.type==='รายรับ' ? '#059669' : '#dc2626';
    trows += `<tr>
      <td>${{t.date}}</td>
      <td><span style="color:${{color}};font-weight:600">${{t.type}}</span></td>
      <td>${{t.item}}</td>
      <td style="text-align:right;color:${{color}};font-weight:600">${{sign}} ${{fmt(t.amount)}}</td>
      <td style="color:#666;font-size:.85em">${{t.note||''}}</td>
    </tr>`;
  }});
  document.getElementById(`gb-${{k}}-tbl`).innerHTML = `
    <thead><tr><th>วันที่</th><th>ประเภท</th><th>รายการ</th><th style="text-align:right">จำนวน (฿)</th><th>หมายเหตุ</th></tr></thead>
    <tbody>${{trows}}</tbody>
  `;
}}

// ═══════════════════════════════════════════════════════
// RUBBER FARM
// ═══════════════════════════════════════════════════════
let rCharts = {{}};
let rCurView = 'round';
let rCurYear = 'all';

const rSel = document.getElementById('r-yearFilter');
rAllYears.forEach(y => rSel.innerHTML += `<option value="${{y}}">${{y}}</option>`);

function rApplyFilter() {{ rCurYear = document.getElementById('r-yearFilter').value; renderRubber(); }}
function rSetView(v) {{
  rCurView = v;
  ['r-vRound','r-vMonth','r-vYear'].forEach(id => document.getElementById(id).classList.remove('active'));
  document.getElementById(v==='round'?'r-vRound':v==='month'?'r-vMonth':'r-vYear').classList.add('active');
  renderRubber();
}}

function renderRubber() {{
  let filtered = rAllData.filter(d => rCurYear==='all' || d.year==rCurYear);
  if (rCurView==='round') rRenderRound(filtered);
  else if (rCurView==='month') rRenderAgg(rMonthData, rCurYear, 'month');
  else rRenderAgg(rYearData, rCurYear, 'year');
}}

function rBuildChart(id,type,labels,datasets,extraOpts={{}}) {{
  if(rCharts[id]) rCharts[id].destroy();
  const ds=datasets.map(d=>Object.assign({{borderWidth:type==='bar'?1:2}},d));
  const isWide = (document.getElementById(id)?.closest('.chart-card.wide')) != null;
  rCharts[id]=new Chart(document.getElementById(id),{{
    type, data:{{labels,datasets:ds}},
    options:Object.assign({{responsive:true,plugins:{{legend:{{position:'top'}}}}}},{{scales:Object.assign({{x:{{}}}},extraOpts)}})
  }});
}}

function rUpdateKPI(owner,sale,nw,rounds,repay,adv,moist) {{
  document.getElementById('r-kpiGrid').innerHTML=[
    {{label:'เจ้าของสวน (ဝင်ငွေ)',val:fmt(owner)+' บาท',cls:''}},
    {{label:'ยอดขายรวม',val:fmt(sale)+' บาท',cls:'blue'}},
    {{label:'น้ำหนักสุทธิรวม',val:fmt(nw)+' กก.',cls:'orange'}},
    {{label:'จำนวนรอบ',val:rounds+' รอบ',cls:'purple'}},
    {{label:'ชำระคืนรวม',val:fmt(repay)+' บาท',cls:'blue'}},
    {{label:'เบิกใหม่รวม',val:adv>0?fmt(adv)+' บาท':'ไม่มี',cls:adv>0?'red':''}},
    {{label:'ความชื้นเฉลี่ย',val:fmtP(moist)+'%',cls:'orange'}},
  ].map(k=>'<div class="kpi '+k.cls+'"><div class="num">'+k.val+'</div><div class="label">'+k.label+'</div></div>').join('');
}}

function rUpdateInsight(data) {{
  if(!data.length) return;
  const maxR=data.reduce((a,b)=>a.owner>b.owner?a:b);
  const minR=data.reduce((a,b)=>a.owner<b.owner?a:b);
  const maxP=data.reduce((a,b)=>a.price>b.price?a:b);
  const avgO=data.reduce((s,d)=>s+d.owner,0)/data.length;
  document.getElementById('r-insightBox').innerHTML=
    '<h3>🔍 วิเคราะห์อัตโนมัติ</h3><ul>'+
    '<li>รอบที่ดีที่สุด: <b>'+maxR.date_th+'</b> — <b>'+fmt(maxR.owner)+' บาท</b></li>'+
    '<li>รอบที่น้อยที่สุด: <b>'+minR.date_th+'</b> — <b>'+fmt(minR.owner)+' บาท</b></li>'+
    '<li>ราคายางสูงสุด: <b>'+maxP.date_th+'</b> — <b>'+maxP.price+' บาท/กก.</b></li>'+
    '<li>รายได้เฉลี่ยต่อรอบ: <b>'+fmt(avgO)+' บาท</b></li>'+
    '</ul>';
}}

function rShowEmpty(){{
  ['r-kpiGrid','r-insightBox','r-tableBody'].forEach(id=>document.getElementById(id).innerHTML='');
  document.getElementById('r-tableTitle').textContent='ไม่มีข้อมูลในช่วงที่เลือก';
}}

function rRenderRound(data) {{
  document.getElementById('r-mainTable').className='view-round';
  if(!data.length){{rShowEmpty();return;}}
  const labels=data.map(d=>d.date_th);
  rUpdateKPI(data.reduce((s,d)=>s+d.owner,0),data.reduce((s,d)=>s+d.sale,0),
    data.reduce((s,d)=>s+d.nw,0),data.length,
    data.reduce((s,d)=>s+d.repay,0),data.reduce((s,d)=>s+d.adv,0),
    data.reduce((s,d)=>s+d.moisture,0)/data.length);
  rUpdateInsight(data);
  rBuildChart('r-moneyChart','bar',labels,[
    {{label:'เจ้าของสวน (ဥယျာဉ်ပိုင်ရှင်)',data:data.map(d=>d.owner),backgroundColor:'rgba(76,175,80,.75)',borderColor:'rgba(76,175,80,1)'}},
    {{label:'คนตัด (ရာဘာဖြတ်သူ)',data:data.map(d=>d.tapper),backgroundColor:'rgba(156,39,176,.65)',borderColor:'rgba(156,39,176,1)'}}
  ],{{y:{{ticks:{{callback:v=>fmt(v)}}}}}});
  rBuildChart('r-priceChart','line',labels,[{{label:'ราคา',data:data.map(d=>d.price),backgroundColor:'rgba(255,152,0,.2)',borderColor:'rgba(255,152,0,1)',fill:true,tension:.3,pointRadius:4}}]);
  rBuildChart('r-weightChart','bar',labels,[{{label:'น้ำหนักสุทธิ',data:data.map(d=>d.nw),backgroundColor:'rgba(33,150,243,.7)',borderColor:'rgba(33,150,243,1)'}}]);
  rBuildChart('r-moistureChart','line',labels,[{{label:'ความชื้น%',data:data.map(d=>d.moisture),backgroundColor:'rgba(244,67,54,.15)',borderColor:'rgba(244,67,54,1)',fill:true,tension:.3,pointRadius:4}}],{{y:{{min:15,max:22}}}});
  let cum=0;
  rBuildChart('r-cumulChart','line',labels,[{{label:'สะสม',data:data.map(d=>{{cum+=d.owner;return cum}}),backgroundColor:'rgba(76,175,80,.1)',borderColor:'rgba(76,175,80,1)',fill:true,tension:.3,pointRadius:4}}],{{y:{{ticks:{{callback:v=>fmt(v)}}}}}});
  document.getElementById('r-tableTitle').textContent='📋 ข้อมูลรายรอบ ('+data.length+' รอบ)';
  const rhdRound = [
    ['วันที่','ရက်စွဲ'],['น้ำหนักรวม','အလေးချိန်'],['น้ำหนักสุทธิ','အသားတင်'],
    ['ราคา','ဈေးနှုန်း'],['ยอดขาย','ရောင်းဘိုး'],['เจ้าของสวน','ဥယျာဉ်ပိုင်ရှင်'],
    ['คนตัด','ရာဘာဖြတ်'],['ชำระคืน','ပြန်ဆပ်'],['เบิกใหม่','ကြိုတင်'],['ความชื้น','စိုထိုင်းဆ']
  ];
  document.getElementById('r-tableHead').innerHTML='<tr>'+rhdRound.map(([th,mm])=>'<th>'+th+'<br><span style="font-size:.75em;opacity:.65;font-weight:normal">'+mm+'</span></th>').join('')+'</tr>';
  document.getElementById('r-tableBody').innerHTML=data.map(d=>{{
    const hi=d.owner>=6000;
    return '<tr><td>'+d.date_th+'</td><td>'+d.tw+'</td><td>'+d.nw+'</td>'+
      '<td>'+fmtP(d.price)+'</td><td>'+fmt(d.sale)+'</td>'+
      '<td><b>'+fmt(d.owner)+'</b> <span class="badge '+(hi?'high':'low')+'">'+(hi?'สูง':'ปกติ')+'</span></td>'+
      '<td>'+fmt(d.tapper)+'</td>'+
      '<td>'+(d.repay>0?'<span style="color:#1565C0">'+fmt(d.repay)+'</span>':'—')+'</td>'+
      '<td>'+(d.adv>0?'<span style="color:#e65100">'+fmt(d.adv)+'</span>':'—')+'</td>'+
      '<td>'+fmtP(d.moisture)+'%</td></tr>';
  }}).join('');
  const tot=f=>data.reduce((s,d)=>s+d[f],0);
  document.getElementById('r-tableFoot').innerHTML='<tr><td>รวม</td><td>'+fmt(tot('tw'))+'</td><td>'+fmt(tot('nw'))+'</td>'+
    '<td>'+fmtP(tot('price')/data.length)+'</td><td>'+fmt(tot('sale'))+'</td>'+
    '<td>'+fmt(tot('owner'))+'</td><td>'+fmt(tot('tapper'))+'</td>'+
    '<td>'+fmt(tot('repay'))+'</td><td>'+(tot('adv')>0?fmt(tot('adv')):'—')+'</td>'+
    '<td>'+fmtP(tot('moisture')/data.length)+'%</td></tr>';
}}

function rRenderAgg(srcData,yearFilter,mode) {{
  document.getElementById('r-mainTable').className='view-agg';
  let entries=Object.entries(srcData);
  if(yearFilter!=='all'&&mode==='month') entries=entries.filter(([k])=>k.startsWith(yearFilter));
  if(!entries.length){{rShowEmpty();return;}}
  const owners=entries.map(([,v])=>v.owner);
  const tappers=entries.map(([,v])=>v.tapper);
  const prices=entries.map(([,v])=>v.price);
  const nws=entries.map(([,v])=>v.nw);
  const moists=entries.map(([,v])=>v.moisture);
  const labels=entries.map(([k])=>k);
  const totOwner=owners.reduce((a,b)=>a+b,0);
  const totSale=entries.reduce((s,[,v])=>s+v.sale,0);
  const totNW=nws.reduce((a,b)=>a+b,0);
  const totRepay=entries.reduce((s,[,v])=>s+v.repay,0);
  const totAdv=entries.reduce((s,[,v])=>s+v.adv,0);
  const avgM=moists.reduce((a,b)=>a+b,0)/moists.length;
  rUpdateKPI(totOwner,totSale,totNW,entries.reduce((s,[,v])=>s+v.count,0),totRepay,totAdv,avgM);
  rBuildChart('r-moneyChart','bar',labels,[
    {{label:'เจ้าของสวน (ဥယျာဉ်ပိုင်ရှင်)',data:owners,backgroundColor:'rgba(76,175,80,.75)',borderColor:'rgba(76,175,80,1)'}},
    {{label:'คนตัดสุทธิ',data:tappers,backgroundColor:'rgba(156,39,176,.65)',borderColor:'rgba(156,39,176,1)'}}
  ],{{y:{{ticks:{{callback:v=>fmt(v)}}}}}});
  rBuildChart('r-priceChart','line',labels,[{{label:'ราคาเฉลี่ย',data:prices,backgroundColor:'rgba(255,152,0,.2)',borderColor:'rgba(255,152,0,1)',fill:true,tension:.3,pointRadius:5}}]);
  rBuildChart('r-weightChart','bar',labels,[{{label:'น้ำหนักสุทธิ',data:nws,backgroundColor:'rgba(33,150,243,.7)',borderColor:'rgba(33,150,243,1)'}}]);
  rBuildChart('r-moistureChart','line',labels,[{{label:'ความชื้น%',data:moists,backgroundColor:'rgba(244,67,54,.15)',borderColor:'rgba(244,67,54,1)',fill:true,tension:.3,pointRadius:5}}],{{y:{{min:15,max:22}}}});
  let cum=0;
  rBuildChart('r-cumulChart','line',labels,[{{label:'สะสม',data:owners.map(v=>{{cum+=v;return cum}}),backgroundColor:'rgba(76,175,80,.1)',borderColor:'rgba(76,175,80,1)',fill:true,tension:.3,pointRadius:5}}],{{y:{{ticks:{{callback:v=>fmt(v)}}}}}});
  const title=mode==='month'?'📋 สรุปรายเดือน':'📋 สรุปรายปี';
  document.getElementById('r-tableTitle').textContent=title;
  const rhdAgg = [
    [mode==='month'?'เดือน':'ปี', mode==='month'?'လ':'နှစ်'],
    ['จำนวนรอบ','အကြိမ်ရေ'],['ยอดขาย','ရောင်းဘိုး'],['เจ้าของสวน','ဥယျာဉ်ပိုင်ရှင်'],
    ['คนตัด','ရာဘာဖြတ်'],['น้ำหนักสุทธิ','အသားတင်'],['ชำระคืน','ပြန်ဆပ်'],
    ['เบิกใหม่','ကြိုတင်'],['ราคาเฉลี่ย','ပျမ်းမျှဈေး'],['ความชื้น','စိုထိုင်းဆ']
  ];
  document.getElementById('r-tableHead').innerHTML='<tr>'+rhdAgg.map(([th,mm])=>'<th>'+th+'<br><span style="font-size:.75em;opacity:.65;font-weight:normal">'+mm+'</span></th>').join('')+'</tr>';
  document.getElementById('r-tableBody').innerHTML=entries.map(([k,v])=>
    '<tr><td>'+k+'</td><td>'+v.count+'</td><td>'+fmt(v.sale)+'</td>'+
    '<td><b>'+fmt(v.owner)+'</b></td><td>'+fmt(v.tapper)+'</td>'+
    '<td>'+fmt(v.nw)+'</td><td>'+fmt(v.repay)+'</td>'+
    '<td>'+(v.adv>0?'<span style="color:#e65100">'+fmt(v.adv)+'</span>':'—')+'</td>'+
    '<td>'+fmtP(v.price)+'</td><td>'+fmtP(v.moisture)+'%</td></tr>').join('');
  document.getElementById('r-tableFoot').innerHTML='<tr><td>รวม/เฉลี่ย</td><td>'+entries.reduce((s,[,v])=>s+v.count,0)+'</td>'+
    '<td>'+fmt(totSale)+'</td><td>'+fmt(totOwner)+'</td>'+
    '<td>'+fmt(entries.reduce((s,[,v])=>s+v.tapper,0))+'</td>'+
    '<td>'+fmt(totNW)+'</td><td>'+fmt(totRepay)+'</td>'+
    '<td>'+(totAdv>0?fmt(totAdv):'—')+'</td>'+
    '<td>'+fmtP(prices.reduce((a,b)=>a+b,0)/prices.length)+'</td>'+
    '<td>'+fmtP(avgM)+'%</td></tr>';
}}

function exportPDF(){{ window.print(); }}
function exportExcel() {{
  const wb=XLSX.utils.book_new();
  const r1=[['วันที่','น้ำหนักรวม','น้ำหนักสุทธิ','ราคา','ยอดขาย','โอนให้เจ้าของ','คนตัดสุทธิ','ชำระคืน','เบิกใหม่','ความชื้น'],
    ...rAllData.map(d=>[d.date_raw,d.tw,d.nw,d.price,d.sale,d.owner,d.tapper,d.repay,d.adv,d.moisture])];
  XLSX.utils.book_append_sheet(wb,XLSX.utils.aoa_to_sheet(r1),'รายรอบ');
  const r2=[['ปี','จำนวนรอบ','ยอดขาย','โอนให้เจ้าของ','คนตัด','น้ำหนัก','ชำระคืน','เบิกใหม่'],
    ...Object.entries(rYearData).map(([y,v])=>[y,v.count,v.sale,v.owner,v.tapper,v.nw,v.repay,v.adv||0])];
  XLSX.utils.book_append_sheet(wb,XLSX.utils.aoa_to_sheet(r2),'รายปี');
  XLSX.writeFile(wb,'rubber_'+new Date().toISOString().slice(0,10)+'.xlsx');
}}

// ═══════════════════════════════════════════════════════
// RENTAL
// ═══════════════════════════════════════════════════════
let reIncomeChart = null;

function initRental() {{
  // Populate year filter
  const years = [...new Set(reIncomes.map(i=>i.date.substring(0,4)).filter(Boolean))].sort();
  const ySel = document.getElementById('re-yearFilter');
  years.forEach(y => {{
    const be = (+y + 543);
    ySel.innerHTML += `<option value="${{y}}">${{be}} (${{y}})</option>`;
  }});

  // Populate room filter
  const rooms = [...new Set(reIncomes.map(i=>i.room).filter(Boolean))].sort();
  const rSel = document.getElementById('re-roomFilter');
  rooms.forEach(r => rSel.innerHTML += `<option value="${{r}}">${{r}}</option>`);

  // Alerts
  const alertSec=document.getElementById('re-alertSection');
  if(reExpiring.length||reAlerts.length) {{
    let h='<div class="section"><h3>🔔 แจ้งเตือน</h3>';
    reExpiring.forEach(e=>h+=`<div class="alert-box ${{e.days<=30?'danger':''}}">⚠️ <b>${{e.room}}</b> — สัญญาหมด ${{e.date}} (อีก ${{e.days}} วัน)</div>`);
    reAlerts.forEach(a=>h+=`<div class="alert-box">📅 <b>${{a.room}}</b> — เก็บเงิน ${{a.date}} (อีก ${{a.days}} วัน) — <b>${{fmt(a.amount)}} ฿</b></div>`);
    alertSec.innerHTML=h+'</div>';
  }}

  // Rooms grid (static)
  const grid=document.getElementById('re-roomsGrid');
  reRooms.forEach(r=>{{
    const isOcc=r.status==='เช่าอยู่';
    grid.innerHTML+=`<div class="room-card ${{isOcc?'occupied':'vacant'}}">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
        <h4>${{r.name}}</h4><span class="sbadge ${{isOcc?'ok':'warn'}}">${{r.status||'ว่าง'}}</span>
      </div>
      <div class="rent">${{fmt(r.rent)}} ฿<span style="font-size:.55em;font-weight:normal;color:#888">/เดือน</span></div>
      <div class="detail">👤 ${{r.tenant||'-'}}<br>📅 เก็บเงิน: ${{r.collect_day}}<br>🔒 มัดจำ: ${{fmt(r.deposit)}} ฿<br>📄 ${{r.contract}}<br>${{r.end_date&&r.end_date!=='-'?'🗓️ สิ้นสุด: '+r.end_date+'<br>':''}}${{r.note?'📝 '+r.note:''}}</div>
    </div>`;
  }});

  // Pie chart (static — สัดส่วนค่าเช่า)
  new Chart(document.getElementById('re-pieChart'),{{
    type:'doughnut',
    data:{{labels:reRooms.map(r=>r.name),datasets:[{{data:reRooms.map(r=>r.rent),
      backgroundColor:['rgba(21,101,192,.8)','rgba(76,175,80,.8)','rgba(255,152,0,.8)','rgba(156,39,176,.8)'],borderWidth:2}}]}},
    options:{{responsive:true,plugins:{{legend:{{position:'bottom'}}}}}}
  }});

  // Water table (static)
  const wtb=document.getElementById('re-waterBody');
  if(reWater.length) {{
    reWater.forEach(w=>wtb.innerHTML+=`<tr><td>${{w.month}}</td><td>${{fmtD(w.water_unit)}}</td><td>${{fmtD(w.water_cost)}}</td><td>${{fmtD(w.elec_unit)}}</td><td>${{fmtD(w.elec_cost)}}</td><td><b>${{fmtD(w.total)}}</b></td></tr>`);
  }} else {{
    wtb.innerHTML='<tr><td colspan="6" class="no-data">ยังไม่มีข้อมูล</td></tr>';
  }}

  // Render filtered view (default = ทั้งหมด)
  reRenderFiltered();
}}

function reFilterYear() {{
  reRenderFiltered();
}}

function reRenderFiltered() {{
  const yearVal = document.getElementById('re-yearFilter').value;
  const roomVal = document.getElementById('re-roomFilter').value;

  // Filter
  let filtered = reIncomes.filter(i => {{
    const yOk = yearVal === 'all' || i.date.startsWith(yearVal);
    const rOk = roomVal === 'all' || i.room === roomVal;
    return yOk && rOk;
  }});

  const total = filtered.reduce((s,i)=>s+i.amount,0);
  const count = filtered.length;

  // ── KPI ──
  const yearLabel = yearVal==='all' ? 'ทั้งหมด' : `ปี ${{+yearVal+543}} (${{yearVal}})`;
  const filteredRooms = roomVal==='all' ? reRooms : reRooms.filter(r=>r.name===roomVal);
  const displayRent    = filteredRooms.reduce((s,r)=>s+r.rent, 0);
  const displayDeposit = filteredRooms.reduce((s,r)=>s+r.deposit, 0);
  const displayOccupied = filteredRooms.filter(r=>r.status==='เช่าอยู่').length;
  const rentLabel    = roomVal==='all' ? 'รายรับ/เดือน (เต็ม)' : `ค่าเช่า ${{roomVal}}`;
  const depositLabel = roomVal==='all' ? 'มัดจำรวมทุกห้อง' : `มัดจำ ${{roomVal}}`;

  document.getElementById('re-kpiGrid').innerHTML=`
    <div class="kpi" style="border-color:#4CAF50"><div class="num" style="color:#2e7d32">${{fmt(displayRent)}} ฿</div><div class="label">${{rentLabel}}</div></div>
    <div class="kpi blue"><div class="num">${{displayOccupied}}/${{filteredRooms.length}}</div><div class="label">ห้องที่มีผู้เช่า</div></div>
    <div class="kpi purple"><div class="num">${{fmt(displayDeposit)}} ฿</div><div class="label">${{depositLabel}}</div></div>
    <div class="kpi orange"><div class="num">${{fmt(total)}} ฿</div><div class="label">รายรับ ${{yearLabel}}</div></div>
    <div class="kpi blue"><div class="num">${{count}}</div><div class="label">จำนวนรายการ ${{yearLabel}}</div></div>
    <div class="kpi ${{reExpiring.length?'red':''}}"><div class="num">{len(expiring)}</div><div class="label">สัญญาใกล้หมด (60 วัน)</div></div>
  `;

  // ── กราฟรายเดือน ──
  const mMap = {{}};
  filtered.forEach(i=>{{ const m=i.date.substring(0,7); if(m) mMap[m]=(mMap[m]||0)+i.amount; }});
  const mLabels = Object.keys(mMap).sort();
  const mVals   = mLabels.map(m=>mMap[m]);
  const chartTitle = yearVal==='all' ? '💰 รายรับรายเดือน (฿)' : `💰 รายรับรายเดือน ปี ${{+yearVal+543}} (฿)`;
  document.getElementById('re-chartTitle').textContent = chartTitle;
  if(reIncomeChart) reIncomeChart.destroy();
  if(mLabels.length) {{
    reIncomeChart = new Chart(document.getElementById('re-incomeChart'),{{
      type:'bar',
      data:{{labels:mLabels,datasets:[{{
        label:'รายรับ',data:mVals,
        backgroundColor:'rgba(21,101,192,.75)',borderColor:'rgba(21,101,192,1)',borderWidth:1
      }}]}},
      options:{{responsive:true,plugins:{{legend:{{display:false}}}},
        scales:{{y:{{ticks:{{callback:v=>v.toLocaleString('th-TH')}}}}}}}}
    }});
  }}

  // ── ตารางรายรับ ──
  const tbody=document.getElementById('re-incomeBody');
  const tfoot=document.getElementById('re-incomeFoot');
  const roomLabel = roomVal==='all' ? '' : ` — ${{roomVal}}`;
  document.getElementById('re-tableTitle').textContent = `📋 ประวัติรายรับ ${{yearLabel}}${{roomLabel}} (${{count}} รายการ)`;
  if(filtered.length) {{
    tbody.innerHTML = filtered.slice().reverse().map(i=>
      `<tr><td>${{i.date}}</td><td>${{i.room}}</td><td>${{i.type}}</td>
       <td><b>${{fmt(i.amount)}}</b></td>
       <td><span class="sbadge ${{i.status==='รับแล้ว'?'ok':'warn'}}">${{i.status||'-'}}</span></td>
       <td>${{i.note||'-'}}</td></tr>`
    ).join('');
    tfoot.innerHTML=`<tr><td colspan="3">รวม</td><td><b>${{fmt(total)}}</b></td><td colspan="2"></td></tr>`;
  }} else {{
    tbody.innerHTML='<tr><td colspan="6" class="no-data">ไม่มีข้อมูลในช่วงที่เลือก</td></tr>';
    tfoot.innerHTML='';
  }}
}}

// ═══════════════════════════════════════════════════════
// SONGKRAN
// ═══════════════════════════════════════════════════════
function initSongkran() {{
  const tbody=document.getElementById('sk-summaryBody');
  skSummaries.forEach(s=>{{
    const isPos=s.profit>=0;
    tbody.innerHTML+=`<tr><td><b>${{s.product}}</b></td>
      <td>${{s.revenue>0?fmt(s.revenue):'-'}}</td><td>${{fmt(s.cost)}}</td>
      <td class="${{isPos?'profit-pos':'profit-neg'}}">${{s.profit!==0?((s.profit>0?'+':'')+fmt(s.profit)):'-'}}</td>
      <td>${{s.pct||'-'}}</td>
      <td>${{s.stock>0?'<span class="stock-badge">'+fmt(s.stock)+' ฿</span>':'-'}}</td>
      <td style="font-size:.82em;color:#666">${{s.note||''}}</td></tr>`;
  }});
  const stbody=document.getElementById('sk-salesBody');
  skSales.forEach(s=>stbody.innerHTML+=`<tr><td>${{s.date}}</td><td>${{s.product}}</td><td>${{s.qty}} ${{s.unit}}</td><td><b>${{fmt(s.revenue)}}</b></td><td style="font-size:.82em;color:#666">${{s.leftover||'-'}}</td></tr>`);
  // Profit chart
  const pLabels=skSummaries.filter(s=>s.profit!==0).map(s=>s.product);
  const pVals=skSummaries.filter(s=>s.profit!==0).map(s=>s.profit);
  new Chart(document.getElementById('sk-profitChart'),{{
    type:'bar',
    data:{{labels:pLabels,datasets:[{{label:'กำไร',data:pVals,backgroundColor:pVals.map(v=>v>=0?'rgba(76,175,80,.8)':'rgba(244,67,54,.8)'),borderWidth:1}}]}},
    options:{{responsive:true,plugins:{{legend:{{display:false}}}},scales:{{y:{{ticks:{{callback:v=>(v>=0?'+':'')+v.toLocaleString('th-TH')}}}}}}}}
  }});
  // Cost vs Revenue chart
  const crLabels=skSummaries.filter(s=>s.cost>0||s.revenue>0).map(s=>s.product);
  new Chart(document.getElementById('sk-costRevenueChart'),{{
    type:'bar',
    data:{{labels:crLabels,datasets:[
      {{label:'ยอดขาย',data:skSummaries.filter(s=>s.cost>0||s.revenue>0).map(s=>s.revenue),backgroundColor:'rgba(76,175,80,.75)'}},
      {{label:'ต้นทุน',data:skSummaries.filter(s=>s.cost>0||s.revenue>0).map(s=>s.cost),backgroundColor:'rgba(244,67,54,.75)'}}
    ]}},
    options:{{responsive:true,plugins:{{legend:{{position:'top'}}}},scales:{{y:{{ticks:{{callback:v=>v.toLocaleString('th-TH')}}}}}}}}
  }});
  // ── สินค้าคงเหลือ (ข้อมูลจริง) ──
  const stockBody = document.getElementById('sk-stockBody');
  const stockFoot = document.getElementById('sk-stockFoot');
  let totStock = 0;
  skStockItems.forEach(s => {{
    totStock += s.value;
    stockBody.innerHTML += `<tr>
      <td><b>${{s.item}}</b></td>
      <td>${{s.qty}} ${{s.unit}}</td>
      <td style="color:#e65100;font-weight:bold">${{fmt(s.value)}}</td>
    </tr>`;
  }});
  stockFoot.innerHTML = `<tr><td><b>รวม</b></td><td></td><td><b style="color:#e65100">${{fmt(totStock)}} ฿</b></td></tr>`;

  // ── กราฟต้นทุน ──
  // 1) Doughnut — สัดส่วนต้นทุนแต่ละสินค้า
  const costByProd = {{}};
  skCosts.forEach(c => {{ if(c.cost>0) costByProd[c.product]=(costByProd[c.product]||0)+c.cost; }});
  const dpColors = ['#e91e63','#9c27b0','#3f51b5','#2196f3','#00bcd4','#009688','#ff9800','#795548'];
  new Chart(document.getElementById('sk-costDoughnut'), {{
    type:'doughnut',
    data:{{labels:Object.keys(costByProd),datasets:[{{
      data:Object.values(costByProd),
      backgroundColor:dpColors.slice(0,Object.keys(costByProd).length),
      borderWidth:2
    }}]}},
    options:{{responsive:true,plugins:{{
      legend:{{position:'right',labels:{{font:{{size:11}}}}}},
      tooltip:{{callbacks:{{label:ctx=>' '+ctx.label+': '+ctx.parsed.toLocaleString('th-TH')+' ฿'}}}}
    }}}}
  }});

  // 2) Grouped bar — ยอดขาย vs ต้นทุน (เข้าใจง่าย ไม่มี dual axis)
  const rcFilter = skSummaries.filter(s=>s.cost>0||s.revenue>0);
  new Chart(document.getElementById('sk-revCostChart'), {{
    type:'bar',
    data:{{labels:rcFilter.map(s=>s.product),datasets:[
      {{label:'ยอดขาย (฿)', data:rcFilter.map(s=>s.revenue), backgroundColor:'rgba(76,175,80,.75)', borderRadius:4}},
      {{label:'ต้นทุน (฿)', data:rcFilter.map(s=>s.cost),    backgroundColor:'rgba(244,67,54,.75)', borderRadius:4}}
    ]}},
    options:{{responsive:true,interaction:{{mode:'index'}},
      plugins:{{legend:{{position:'top'}},
        tooltip:{{callbacks:{{label:ctx=>ctx.dataset.label+' '+ctx.parsed.y.toLocaleString('th-TH')+' ฿'}}}}
      }},
      scales:{{y:{{ticks:{{callback:v=>v.toLocaleString('th-TH')}}}}}}
    }}
  }});

  // 3) Horizontal bar — %กำไรแต่ละสินค้า (อ่านง่าย เขียว=กำไร แดง=ขาดทุน)
  const mgFilter = [...skSummaries].filter(s=>s.cost>0||s.revenue>0)
    .sort((a,b)=>((b.profit/Math.max(b.revenue,1))-(a.profit/Math.max(a.revenue,1))));
  const mgPcts = mgFilter.map(s=> s.revenue>0 ? +((s.profit/s.revenue)*100).toFixed(1) : (s.profit<0?-100:0));
  new Chart(document.getElementById('sk-marginChart'), {{
    type:'bar',
    data:{{labels:mgFilter.map(s=>s.product),datasets:[{{
      label:'%กำไร',
      data:mgPcts,
      backgroundColor:mgPcts.map(v=>v>=0?'rgba(76,175,80,.8)':'rgba(244,67,54,.8)'),
      borderRadius:4
    }}]}},
    options:{{indexAxis:'y',responsive:true,
      plugins:{{legend:{{display:false}},
        tooltip:{{callbacks:{{
          label:ctx=>{{
            const s=mgFilter[ctx.dataIndex];
            return ` ${{ctx.parsed.x}}% | กำไร ${{s.profit.toLocaleString('th-TH')}} ฿`;
          }}
        }}}}
      }},
      scales:{{
        x:{{ticks:{{callback:v=>v+'%'}},
          grid:{{color:ctx=>ctx.tick.value===0?'#333':'rgba(0,0,0,.08)'}},
          border:{{dash:[4,4]}}
        }}
      }}
    }}
  }});

  // 3) Horizontal bar — รายการที่แพงที่สุด (top items)
  const sortedItems = [...skCosts].filter(c=>c.cost>0)
    .sort((a,b)=>b.cost-a.cost).slice(0,15);
  const ciLabels = sortedItems.map(c=>(c.item||c.product)+(c.product!==c.item?` (${{c.product}})`:''));
  const ciVals   = sortedItems.map(c=>c.cost);
  const ciColors = sortedItems.map(c=>
    c.cost>=3000?'rgba(244,67,54,.8)':c.cost>=1000?'rgba(255,152,0,.8)':'rgba(76,175,80,.8)'
  );
  new Chart(document.getElementById('sk-costItemBar'), {{
    type:'bar',
    data:{{labels:ciLabels,datasets:[{{
      label:'ต้นทุน (฿)',data:ciVals,backgroundColor:ciColors,borderRadius:4
    }}]}},
    options:{{indexAxis:'y',responsive:true,
      plugins:{{legend:{{display:false}},
        tooltip:{{callbacks:{{label:ctx=>ctx.parsed.x.toLocaleString('th-TH')+' ฿'}}}}
      }},
      scales:{{x:{{ticks:{{callback:v=>v.toLocaleString('th-TH')}}}}}}
    }}
  }});

  // ── รายละเอียดต้นทุนทั้งหมด (ตาราง) ──
  const costBody = document.getElementById('sk-costBody');
  const costFoot = document.getElementById('sk-costFoot');
  const costByProduct = {{}};
  skCosts.forEach(c => {{
    if(!costByProduct[c.product]) costByProduct[c.product]=[];
    costByProduct[c.product].push(c);
  }});
  let grandCost = 0;
  Object.entries(costByProduct).forEach(([product, items]) => {{
    const productTotal = items.reduce((s,c)=>s+c.cost,0);
    grandCost += productTotal;
    items.forEach((c,idx) => {{
      costBody.innerHTML += `<tr style="${{idx===0?'border-top:2px solid #fce4ec':''}}">
        <td style="font-weight:${{idx===0?'bold':'normal'}};color:${{idx===0?'#880E4F':'#666'}}">${{idx===0?c.product:''}}</td>
        <td style="text-align:left">${{c.item||'-'}}</td>
        <td>${{c.qty||'-'}}</td>
        <td>${{c.unit||'-'}}</td>
        <td>${{c.cost>0?fmt(c.cost):'-'}}</td>
      </tr>`;
    }});
    costBody.innerHTML += `<tr style="background:#fce4ec">
      <td colspan="4" style="text-align:right;font-size:.85em;color:#880E4F">รวม ${{product}}</td>
      <td><b style="color:#880E4F">${{fmt(productTotal)}}</b></td>
    </tr>`;
  }});
  costFoot.innerHTML = `<tr><td colspan="4">รวมต้นทุนทั้งหมด</td><td><b>${{fmt(grandCost)}}</b></td></tr>`;

  // Tips
  const tips=['🍳 <b>ข้าวไข่เจียว</b> กำไรดีที่สุด 33% ปีหน้าควรขยายจำนวนวันขาย',
    '💧 <b>น้ำเปล่า</b> กำไร% สูงสุดในกลุ่มน้ำ ควรเพิ่มจำนวน',
    '🎒 <b>แป้ง/กระเป๋า</b> มีสต็อกปีหน้าแล้ว 4,449 ฿ ซื้อน้อยลงได้',
    '⛺ <b>ค่าเต้น</b> ซื้อแทนเช่าได้ 700-800 ฿ ประหยัดปีละ 1,000 ฿',
    '📝 <b>ปีหน้า</b> ควรจดยอดขายน้ำแยกรายวัน เพื่อวิเคราะห์ได้แม่นยำขึ้น'];
  document.getElementById('sk-tipsBox').innerHTML=tips.map(t=>`<div class="tip-box">${{t}}</div>`).join('');
}}

// ═══════════════════════════════════════════════════════
// INIT
// ═══════════════════════════════════════════════════════
tabInited['overview'] = true;
initOverview();

// ═══════════════════════════════════════════════════════
// 🎯 GOALS SETUP — ตั้งเป้ารายได้รายธุรกิจ
// ═══════════════════════════════════════════════════════
function goalsSetup() {{
  const biz = window._goalsBiz || [];
  const key = window._goalsKey;
  if (!biz.length || !key) {{ alert('ยังโหลดข้อมูลไม่เสร็จ ลองใหม่อีกครั้ง'); return; }}
  const cur = JSON.parse(localStorage.getItem(key) || '{{}}');
  const defGoal = (last) => last > 0 ? Math.round(last * 1.1 / 1000) * 1000 : 0;

  const overlay = document.createElement('div');
  overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.6);z-index:9999;display:flex;align-items:center;justify-content:center;padding:20px';
  const rows = biz.map(b => {{
    const v = cur[b.key] != null ? cur[b.key] : defGoal(b.last);
    const hint = b.last > 0 ? `ปีที่แล้ว ${{b.last.toLocaleString()}} ฿ — แนะนำ ${{defGoal(b.last).toLocaleString()}} ฿ (+10%)` : 'ยังไม่มีข้อมูลปีที่แล้ว';
    return `
      <div style="margin-bottom:14px">
        <label style="display:block;font-weight:600;margin-bottom:4px">${{b.name}}</label>
        <input type="number" data-key="${{b.key}}" value="${{v}}" min="0" step="1000"
               style="width:100%;padding:10px 12px;border:1px solid #ddd;border-radius:8px;font-size:1em">
        <div style="font-size:.78em;color:#888;margin-top:3px">${{hint}}</div>
      </div>`;
  }}).join('');
  overlay.innerHTML = `
    <div style="background:white;border-radius:14px;padding:22px;max-width:480px;width:100%;max-height:90vh;overflow:auto;box-shadow:0 20px 60px rgba(0,0,0,.3)">
      <h3 style="margin:0 0 14px;color:#1a1a2e">🎯 ตั้งเป้ารายได้รายปี</h3>
      <p style="font-size:.85em;color:#666;margin:0 0 16px">บันทึกในเครื่องคุณเท่านั้น (localStorage) — เปลี่ยนเครื่องต้องตั้งใหม่</p>
      <form id="gf">${{rows}}
        <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:16px">
          <button type="button" id="gc" style="padding:9px 18px;background:#f3f4f6;border:none;border-radius:8px;cursor:pointer;font-weight:600">ยกเลิก</button>
          <button type="button" id="gr" style="padding:9px 18px;background:#fef3c7;color:#92400e;border:none;border-radius:8px;cursor:pointer;font-weight:600">รีเซ็ต</button>
          <button type="submit" style="padding:9px 18px;background:#6366f1;color:white;border:none;border-radius:8px;cursor:pointer;font-weight:600">💾 บันทึก</button>
        </div>
      </form>
    </div>`;
  document.body.appendChild(overlay);
  overlay.querySelector('#gc').onclick = () => overlay.remove();
  overlay.querySelector('#gr').onclick = () => {{
    if (confirm('ลบเป้าทั้งหมดของปีนี้?')) {{
      localStorage.removeItem(key);
      overlay.remove();
      initOverview();
    }}
  }};
  overlay.querySelector('#gf').onsubmit = (e) => {{
    e.preventDefault();
    const newGoals = {{}};
    overlay.querySelectorAll('input[data-key]').forEach(inp => {{
      const v = parseInt(inp.value) || 0;
      if (v > 0) newGoals[inp.dataset.key] = v;
    }});
    localStorage.setItem(key, JSON.stringify(newGoals));
    overlay.remove();
    initOverview();
  }};
}}

// ═══════════════════════════════════════════════════════
// 📄 ANNUAL REPORT — เปิดหน้าใหม่พร้อม print-friendly layout
// ═══════════════════════════════════════════════════════
function openAnnualReport() {{
  const thisYear = new Date().getFullYear();
  const lastYear = thisYear - 1;
  const beYear = thisYear + 543;
  const today = new Date().toLocaleDateString('th-TH', {{year:'numeric',month:'long',day:'numeric'}});

  // คำนวณตัวเลขทุกธุรกิจ
  const rubberThis = rAllData.filter(d=>d.year===thisYear).reduce((s,d)=>s+d.owner,0);
  const rubberLast = rAllData.filter(d=>d.year===lastYear).reduce((s,d)=>s+d.owner,0);
  const rubberAll  = rAllData.reduce((s,d)=>s+d.owner,0);
  const rubberCnt  = rAllData.filter(d=>d.year===thisYear).length;
  const rubberAvgPrice = rAllData.length ? rAllData.reduce((s,d)=>s+d.price,0)/rAllData.length : 0;

  const rentalThis = reIncomes.filter(i=>i.date.startsWith(String(thisYear))).reduce((s,i)=>s+i.amount,0);
  const rentalLast = reIncomes.filter(i=>i.date.startsWith(String(lastYear))).reduce((s,i)=>s+i.amount,0);
  const rentalAll  = reIncomes.reduce((s,i)=>s+i.amount,0);
  const occupied   = reRooms.filter(r=>r.status==='เช่าอยู่').length;
  const monthlyRent = reRooms.reduce((s,r)=>s+r.rent,0);

  const fmtR = n => (+n||0).toLocaleString('th-TH',{{minimumFractionDigits:0,maximumFractionDigits:0}});
  const yoyPct = (cur,prev) => prev>0 ? ((cur-prev)/prev*100).toFixed(1)+'%' : '—';

  // Generic biz rows
  const genRows = GENERIC_BIZ.map(b => {{
    const rTot = b.revenues.reduce((s,r)=>s+r.amount,0);
    const eTot = b.expenses.reduce((s,r)=>s+r.amount,0);
    const rThis = b.revenues.filter(r=>r.date.startsWith(String(thisYear))).reduce((s,r)=>s+r.amount,0);
    const rLast = b.revenues.filter(r=>r.date.startsWith(String(lastYear))).reduce((s,r)=>s+r.amount,0);
    return `<tr><td>${{b.emoji}} ${{b.name}}</td><td>${{fmtR(rTot)}}</td><td>${{fmtR(eTot)}}</td><td>${{fmtR(rTot-eTot)}}</td><td>${{fmtR(rThis)}}</td><td>${{fmtR(rLast)}}</td><td>${{yoyPct(rThis,rLast)}}</td></tr>`;
  }}).join('');

  // Songkran items table
  const skItems = skSummaries.filter(s => s.product !== 'รวมทั้งหมด').map(s =>
    `<tr><td>${{s.product}}</td><td>${{fmtR(s.revenue)}}</td><td>${{fmtR(s.cost)}}</td><td>${{fmtR(s.profit)}}</td><td>${{s.pct}}</td></tr>`
  ).join('');

  // Stock items
  const stockRows = skStockItems.map(s =>
    `<tr><td>${{s.item}}</td><td>${{s.qty}} ${{s.unit}}</td><td>${{fmtR(s.value)}}</td></tr>`
  ).join('');
  const stockTotal = skStockItems.reduce((s,i)=>s+i.value,0);

  // Rooms table
  const roomsRows = reRooms.map(r =>
    `<tr><td>${{r.name}}</td><td>${{r.tenant}}</td><td>${{fmtR(r.rent)}}</td><td>${{r.status}}</td><td>${{r.end_date}}</td></tr>`
  ).join('');

  // Build HTML
  const html = `<!DOCTYPE html>
<html lang="th"><head><meta charset="UTF-8">
<title>Annual Report ${{beYear}} — Boss Business Hub</title>
<style>
@page {{ size: A4; margin: 1.2cm; }}
* {{ box-sizing: border-box; }}
body {{ font-family: 'Sarabun','Leelawadee UI','Tahoma',sans-serif; color:#1a1a2e; line-height:1.55; max-width:21cm; margin:0 auto; padding:18px; background:#f0f0f0; }}
.page {{ background:white; padding:36px 44px; margin-bottom:14px; box-shadow:0 2px 10px rgba(0,0,0,.08); page-break-after:always; min-height:27.5cm; }}
.page:last-child {{ page-break-after:auto; }}
h1 {{ font-size:1.8em; margin:0 0 6px; color:#1a1a2e; }}
h2 {{ font-size:1.25em; margin:24px 0 10px; padding-bottom:6px; border-bottom:2px solid #1a1a2e; }}
h3 {{ font-size:1.05em; margin:16px 0 8px; color:#37474f; }}
.cover {{ text-align:center; padding:80px 30px; }}
.cover .big {{ font-size:5em; margin:20px 0; }}
.cover h1 {{ font-size:2.4em; margin:14px 0; }}
.cover .sub {{ color:#666; font-size:1.1em; margin:8px 0; }}
.kpi-grid {{ display:grid; grid-template-columns:repeat(3,1fr); gap:10px; margin:14px 0; }}
.kpi {{ background:#f7f8fc; border-radius:8px; padding:14px 16px; border-left:4px solid #1a1a2e; }}
.kpi .num {{ font-size:1.4em; font-weight:700; color:#1a1a2e; }}
.kpi .lbl {{ font-size:.78em; color:#666; margin-top:2px; }}
table {{ width:100%; border-collapse:collapse; margin:10px 0; font-size:.85em; }}
th, td {{ padding:7px 10px; border:1px solid #ddd; text-align:left; }}
th {{ background:#1a1a2e; color:white; font-weight:600; }}
tr:nth-child(even) td {{ background:#f9fafb; }}
.print-btn {{ position:fixed; top:14px; right:14px; background:#1a1a2e; color:white; border:none; padding:10px 22px; border-radius:8px; cursor:pointer; font-weight:600; font-size:.95em; box-shadow:0 4px 12px rgba(0,0,0,.2); }}
.tag {{ display:inline-block; background:#dbeafe; color:#1e40af; padding:2px 10px; border-radius:12px; font-size:.78em; margin-left:6px; }}
.green {{ color:#059669; font-weight:600; }} .red {{ color:#dc2626; font-weight:600; }}
@media print {{ body{{background:white;padding:0;}} .page{{box-shadow:none;margin:0;}} .print-btn{{display:none;}} }}
</style>
</head><body>

<button class="print-btn" onclick="window.print()">🖨️ พิมพ์ / Save PDF</button>

<!-- COVER -->
<div class="page cover">
  <div class="big">📊</div>
  <h1>รายงานประจำปี ${{beYear}}</h1>
  <div class="sub">Boss Business Hub — บอสอู๊ด</div>
  <div class="sub" style="margin-top:36px">🌿 สวนยาง · 🏠 ห้องเช่า · 🎊 สงกราน${{GENERIC_BIZ.map(b=>` · ${{b.emoji}} ${{b.name}}`).join('')}}</div>
  <div style="margin-top:80px;color:#999;font-size:.95em">จัดทำโดย ปอง · ${{today}}</div>
</div>

<!-- SUMMARY -->
<div class="page">
  <h1>📋 สรุปภาพรวม</h1>
  <h2>💰 ภาพรวมรายได้ ปี ${{beYear}}</h2>
  <div class="kpi-grid">
    <div class="kpi"><div class="num">${{fmtR(rubberThis)}} ฿</div><div class="lbl">🌿 สวนยาง — รายได้ปีนี้</div></div>
    <div class="kpi"><div class="num">${{fmtR(rentalThis)}} ฿</div><div class="lbl">🏠 ห้องเช่า — รายรับปีนี้</div></div>
    <div class="kpi"><div class="num">${{fmtR(skTotalProfit)}} ฿</div><div class="lbl">🎊 สงกราน — กำไรสุทธิ</div></div>
  </div>

  <h2>📊 ตารางสรุปทุกธุรกิจ</h2>
  <table>
    <thead><tr><th>ธุรกิจ</th><th>รายได้สะสม</th><th>รายจ่ายสะสม</th><th>กำไร</th><th>ปีนี้ (${{beYear}})</th><th>ปีก่อน (${{lastYear+543}})</th><th>YoY</th></tr></thead>
    <tbody>
      <tr><td>🌿 สวนยาง (เจ้าของสวน)</td><td>${{fmtR(rubberAll)}}</td><td>—</td><td>${{fmtR(rubberAll)}}</td><td>${{fmtR(rubberThis)}}</td><td>${{fmtR(rubberLast)}}</td><td>${{yoyPct(rubberThis,rubberLast)}}</td></tr>
      <tr><td>🏠 ห้องเช่า</td><td>${{fmtR(rentalAll)}}</td><td>—</td><td>${{fmtR(rentalAll)}}</td><td>${{fmtR(rentalThis)}}</td><td>${{fmtR(rentalLast)}}</td><td>${{yoyPct(rentalThis,rentalLast)}}</td></tr>
      <tr><td>🎊 สงกราน</td><td>${{fmtR(skTotalRevenue)}}</td><td>${{fmtR(skTotalCost)}}</td><td class="${{skTotalProfit>=0?'green':'red'}}">${{fmtR(skTotalProfit)}}</td><td>${{fmtR(skTotalProfit)}}</td><td>—</td><td>—</td></tr>
      ${{genRows}}
    </tbody>
  </table>
</div>

<!-- RUBBER -->
<div class="page">
  <h1>🌿 รายงาน — สวนยางพารา</h1>
  <div class="kpi-grid">
    <div class="kpi"><div class="num">${{fmtR(rubberThis)}} ฿</div><div class="lbl">รายได้ปีนี้</div></div>
    <div class="kpi"><div class="num">${{rubberCnt}} รอบ</div><div class="lbl">จำนวนรอบกรีดปีนี้</div></div>
    <div class="kpi"><div class="num">${{rubberAvgPrice.toFixed(2)}} ฿/กก.</div><div class="lbl">ราคาเฉลี่ยตลอดกาล</div></div>
  </div>
  <h3>📊 รายได้ย้อนหลัง 12 เดือน</h3>
  <table>
    <thead><tr><th>เดือน</th><th>เจ้าของสวน (฿)</th></tr></thead>
    <tbody>${{(()=>{{ const map={{}}; rAllData.forEach(d=>{{const m=d.date_raw.substring(0,7); map[m]=(map[m]||0)+d.owner;}}); return Object.keys(map).sort().slice(-12).map(m=>`<tr><td>${{m}}</td><td>${{fmtR(map[m])}}</td></tr>`).join(''); }})()}}</tbody>
  </table>
</div>

<!-- RENTAL -->
<div class="page">
  <h1>🏠 รายงาน — ห้องเช่า</h1>
  <div class="kpi-grid">
    <div class="kpi"><div class="num">${{fmtR(rentalThis)}} ฿</div><div class="lbl">รายรับปีนี้</div></div>
    <div class="kpi"><div class="num">${{occupied}}/${{reRooms.length}}</div><div class="lbl">ห้องที่เช่าอยู่</div></div>
    <div class="kpi"><div class="num">${{fmtR(monthlyRent)}} ฿</div><div class="lbl">รายรับเต็มที่/เดือน</div></div>
  </div>
  <h3>🚪 รายละเอียดห้อง</h3>
  <table>
    <thead><tr><th>ห้อง</th><th>ผู้เช่า</th><th>ค่าเช่า (฿)</th><th>สถานะ</th><th>หมดสัญญา</th></tr></thead>
    <tbody>${{roomsRows}}</tbody>
  </table>
</div>

<!-- SONGKRAN -->
<div class="page">
  <h1>🎊 รายงาน — สงกราน ${{beYear}}</h1>
  <div class="kpi-grid">
    <div class="kpi"><div class="num">${{fmtR(skTotalRevenue)}} ฿</div><div class="lbl">ยอดขายรวม</div></div>
    <div class="kpi"><div class="num">${{fmtR(skTotalCost)}} ฿</div><div class="lbl">ต้นทุนรวม</div></div>
    <div class="kpi"><div class="num ${{skTotalProfit>=0?'green':'red'}}">${{fmtR(skTotalProfit)}} ฿</div><div class="lbl">กำไรสุทธิ</div></div>
  </div>
  <h3>📦 สรุปรายสินค้า</h3>
  <table>
    <thead><tr><th>สินค้า</th><th>ยอดขาย</th><th>ต้นทุน</th><th>กำไร</th><th>%</th></tr></thead>
    <tbody>${{skItems}}</tbody>
  </table>
  <h3>🎒 สต็อกคงเหลือ (ยกปีหน้า)</h3>
  <table>
    <thead><tr><th>สินค้า</th><th>จำนวน</th><th>มูลค่า (฿)</th></tr></thead>
    <tbody>${{stockRows}}<tr><td colspan="2"><b>รวม</b></td><td><b>${{fmtR(stockTotal)}}</b></td></tr></tbody>
  </table>
</div>

<script>
// auto open print dialog หลัง 1 วินาที (ให้ render เสร็จก่อน)
setTimeout(() => window.print(), 800);
<\/script>
</body></html>`;

  const w = window.open('', '_blank');
  w.document.write(html);
  w.document.close();
}}

// ═══════════════════════════════════════════════════════
// 🤖 AI Q&A ASSISTANT (Gemini 2.5 Flash)
// ═══════════════════════════════════════════════════════
const AI_KEY_STORE = 'bosshub_gemini_key';
const AI_HISTORY_STORE = 'bosshub_ai_history';
let aiHistory = JSON.parse(localStorage.getItem(AI_HISTORY_STORE) || '[]');

function aiToggle() {{
  const p = document.getElementById('ai-panel');
  const open = p.style.display === 'none';
  p.style.display = open ? 'flex' : 'none';
  if (open) {{
    if (aiHistory.length === 0) aiWelcome();
    else aiRenderHistory();
    aiRenderQuick();
    setTimeout(() => document.getElementById('ai-input').focus(), 100);
  }}
}}

function aiWelcome() {{
  const key = localStorage.getItem(AI_KEY_STORE);
  if (!key) {{
    aiAddBubble('bot', `👋 สวัสดีครับ! ผมเป็น AI ช่วยวิเคราะห์ธุรกิจของปอง<br><br>
      <b>ตั้งค่าครั้งแรก:</b> ใส่ Gemini API key (ฟรี 1,500 req/วัน):<br>
      <ol style="margin:8px 0;padding-left:22px;font-size:.88em">
        <li>เปิด <a href="https://aistudio.google.com/apikey" target="_blank" style="color:#6366f1">aistudio.google.com/apikey</a></li>
        <li>กด "Create API key"</li>
        <li>คัดลอก key (ขึ้นต้นด้วย <code>AIza...</code>)</li>
        <li>กดปุ่มข้างล่าง วาง key</li>
      </ol>
      <button onclick="aiSetupKey()" style="background:#6366f1;color:white;border:none;padding:8px 16px;border-radius:6px;cursor:pointer;font-weight:600;margin-top:6px">🔑 ใส่ API Key</button>`);
  }} else {{
    aiAddBubble('bot', `👋 สวัสดีครับ! ผมพร้อมตอบคำถามเรื่องธุรกิจของปองแล้ว<br><br>
      <b>ลองถามเช่น:</b><br>
      • "เดือนไหนยอดสูงสุด?"<br>
      • "ปีนี้ธุรกิจไหนกำไรดีสุด?"<br>
      • "ห้องเช่ามีปัญหาอะไรไหม?"<br>
      • "แนะนำว่าควรปรับอะไรบ้าง?"`);
  }}
}}

function aiSetupKey() {{
  const key = prompt('วาง Gemini API key (ขึ้นต้นด้วย AIza...):');
  if (!key) return;
  if (!key.startsWith('AIza')) {{ alert('API key ไม่ถูกต้อง — ต้องขึ้นต้น AIza'); return; }}
  localStorage.setItem(AI_KEY_STORE, key.trim());
  aiHistory = [];
  localStorage.setItem(AI_HISTORY_STORE, '[]');
  document.getElementById('ai-messages').innerHTML = '';
  aiAddBubble('bot', '✅ บันทึก key เรียบร้อย! ถามได้เลยครับ');
}}

function aiClearKey() {{
  if (!confirm('ลบ API key และประวัติทั้งหมด?')) return;
  localStorage.removeItem(AI_KEY_STORE);
  localStorage.removeItem(AI_HISTORY_STORE);
  aiHistory = [];
  document.getElementById('ai-messages').innerHTML = '';
  aiWelcome();
}}

function aiAddBubble(role, html) {{
  const box = document.getElementById('ai-messages');
  const isUser = role === 'user';
  box.insertAdjacentHTML('beforeend', `
    <div style="display:flex;justify-content:${{isUser?'flex-end':'flex-start'}};margin-bottom:10px">
      <div style="background:${{isUser?'#6366f1':'white'}};color:${{isUser?'white':'#1a1a2e'}};padding:10px 14px;border-radius:14px;max-width:85%;box-shadow:0 1px 3px rgba(0,0,0,.06);font-size:.88em;line-height:1.55">
        ${{html}}
      </div>
    </div>
  `);
  box.scrollTop = box.scrollHeight;
}}

function aiRenderHistory() {{
  document.getElementById('ai-messages').innerHTML = '';
  aiHistory.forEach(m => aiAddBubble(m.role, m.html));
}}

function aiRenderQuick() {{
  const quicks = [
    '📈 ปีนี้ธุรกิจไหนกำไรสูงสุด?',
    '🌿 ราคายางเฉลี่ย?',
    '🏠 ห้องไหนมีปัญหา?',
    '💡 แนะนำการปรับปรุง',
  ];
  document.getElementById('ai-quick').innerHTML = quicks.map(q =>
    `<button onclick="aiAsk('${{q.replace(/'/g, "\\\\'")}}')" style="background:#eef2ff;color:#4f46e5;border:none;padding:5px 10px;border-radius:14px;cursor:pointer;font-size:.78em">${{q}}</button>`
  ).join('') + ` <button onclick="aiClearKey()" title="ลบ API key" style="background:transparent;color:#9ca3af;border:none;padding:5px;cursor:pointer;font-size:.85em">⚙️</button>`;
}}

// สร้าง context สรุปข้อมูลธุรกิจ (compact)
function aiBuildContext() {{
  const thisYear = new Date().getFullYear();
  const lastYear = thisYear - 1;
  const rubberThis = rAllData.filter(d=>d.year===thisYear).reduce((s,d)=>s+d.owner,0);
  const rubberLast = rAllData.filter(d=>d.year===lastYear).reduce((s,d)=>s+d.owner,0);
  const rubberAll  = rAllData.reduce((s,d)=>s+d.owner,0);
  const rubberAvg  = rAllData.length ? rAllData.reduce((s,d)=>s+d.price,0)/rAllData.length : 0;
  const rentalThis = reIncomes.filter(i=>i.date.startsWith(String(thisYear))).reduce((s,i)=>s+i.amount,0);
  const rentalLast = reIncomes.filter(i=>i.date.startsWith(String(lastYear))).reduce((s,i)=>s+i.amount,0);
  const occupied   = reRooms.filter(r=>r.status==='เช่าอยู่').length;
  const monthlyRent= reRooms.reduce((s,r)=>s+r.rent,0);
  const monthMap = {{}};
  rAllData.forEach(d=>{{const m=d.date_raw.substring(0,7); monthMap[m]=(monthMap[m]||0)+d.owner;}});
  reIncomes.forEach(i=>{{const m=i.date.substring(0,7); monthMap[m]=(monthMap[m]||0)+i.amount;}});
  const monthSummary = Object.keys(monthMap).sort().slice(-12).map(m=>`${{m}}:${{Math.round(monthMap[m])}}`).join(', ');

  const ctx = {{
    today: new Date().toISOString().slice(0,10),
    thisYear, lastYear, beYear: thisYear+543,
    rubber: {{
      total_revenue: rubberAll, this_year: rubberThis, last_year: rubberLast,
      rounds_total: rAllData.length, avg_price_per_kg: +rubberAvg.toFixed(2),
      latest_round: rAllData[rAllData.length-1] || null
    }},
    rental: {{
      total_revenue: reIncomes.reduce((s,i)=>s+i.amount,0),
      this_year: rentalThis, last_year: rentalLast,
      rooms_total: reRooms.length, occupied,
      max_monthly_rent: monthlyRent,
      rooms: reRooms.map(r => ({{
        name:r.name, tenant:r.tenant, rent:r.rent, status:r.status, end:r.end_date
      }})),
      expiring_60d: reExpiring
    }},
    songkran: {{
      revenue: skTotalRevenue, cost: skTotalCost, profit: skTotalProfit,
      stock_value: skTotalStock, products: skSummaries.filter(s=>s.product!=='รวมทั้งหมด').map(s=>({{
        name:s.product, revenue:s.revenue, cost:s.cost, profit:s.profit, pct:s.pct
      }}))
    }},
    generic_businesses: GENERIC_BIZ.map(b => ({{
      name: b.name,
      revenue_total: b.revenues.reduce((s,r)=>s+r.amount,0),
      expense_total: b.expenses.reduce((s,r)=>s+r.amount,0)
    }})),
    monthly_combined_last_12: monthSummary
  }};
  return JSON.stringify(ctx, null, 0);
}}

async function aiAsk(forceQ) {{
  const input = document.getElementById('ai-input');
  const q = (forceQ || input.value).trim();
  if (!q) return;
  input.value = '';
  const key = localStorage.getItem(AI_KEY_STORE);
  if (!key) {{ aiSetupKey(); return; }}

  aiAddBubble('user', q);
  aiHistory.push({{role:'user', html:q}});
  aiAddBubble('bot', '<span style="opacity:.6">🤔 กำลังคิด...</span>');

  const ctx = aiBuildContext();
  const sysPrompt = `คุณเป็น AI ผู้ช่วยวิเคราะห์ธุรกิจของปอง (เจ้าของธุรกิจชื่อบอสอู๊ด)
ตอบเป็นภาษาไทยเสมอ กระชับ ตรงประเด็น มีตัวเลขประกอบ
ใช้ emoji ประกอบเล็กน้อย ใช้ <b>ตัวหนา</b> สำหรับตัวเลขสำคัญ
ถ้าข้อมูลไม่พอตอบ ให้บอกตรง ๆ อย่าเดา
หน่วยเงินคือบาท (฿) ปีไทย พ.ศ. = ปี ค.ศ. + 543

ข้อมูลธุรกิจล่าสุด (JSON):
${{ctx}}`;

  try {{
    const url = `https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key=${{key}}`;
    const body = {{
      systemInstruction: {{ parts: [{{ text: sysPrompt }}] }},
      contents: [{{ role:'user', parts: [{{ text: q }}] }}],
      generationConfig: {{ temperature: 0.4, maxOutputTokens: 800 }}
    }};
    const res = await fetch(url, {{
      method: 'POST',
      headers: {{ 'Content-Type': 'application/json' }},
      body: JSON.stringify(body)
    }});
    const json = await res.json();
    const msgs = document.getElementById('ai-messages');
    msgs.lastElementChild.remove();  // ลบ "กำลังคิด..."

    if (json.error) {{
      aiAddBubble('bot', `❌ ${{json.error.message || 'API error'}}`);
      return;
    }}
    const text = json.candidates?.[0]?.content?.parts?.[0]?.text || 'ไม่ได้รับคำตอบ';
    const html = text.replace(/\\n/g, '<br>');
    aiAddBubble('bot', html);
    aiHistory.push({{role:'bot', html}});
    if (aiHistory.length > 20) aiHistory = aiHistory.slice(-20);
    localStorage.setItem(AI_HISTORY_STORE, JSON.stringify(aiHistory));
  }} catch (e) {{
    document.getElementById('ai-messages').lastElementChild.remove();
    aiAddBubble('bot', `❌ Error: ${{e.message}}`);
  }}
}}

// 📱 PWA — register service worker
if ('serviceWorker' in navigator) {{
  window.addEventListener('load', () => {{
    navigator.serviceWorker.register('sw.js').catch(e => console.warn('SW reg failed:', e));
  }});
}}
</script>
</body>
</html>"""

print(f"\n✍️  สร้าง HTML...")
with open(OUT_PATH, "w", encoding="utf-8") as f:
    f.write(html)
size = os.path.getsize(OUT_PATH)
print(f"✅ unified_index.html สร้างเสร็จ! {size//1024} KB")

# ─── Ensure repo & Push ────────────────────────────────────────────────────
print("\n🔧 ตรวจสอบ repo...")
ensure_repo()

import time; time.sleep(2)  # รอ repo พร้อม

def push_file(remote_path, local_bytes, msg=None):
    """Push bytes content to GitHub repo at remote_path."""
    api_url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{remote_path}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json", "Content-Type": "application/json"}
    req = urllib.request.Request(api_url, headers=headers)
    try:
        with urllib.request.urlopen(req) as r:
            sha = json.loads(r.read()).get("sha", "")
    except:
        sha = ""
    content_b64 = base64.b64encode(local_bytes).decode()
    payload = {"message": msg or f"update {remote_path} {datetime.now().strftime('%Y-%m-%d %H:%M')}", "content": content_b64, "branch": GITHUB_BRANCH}
    if sha: payload["sha"] = sha
    req2 = urllib.request.Request(api_url, data=json.dumps(payload).encode(), headers=headers, method="PUT")
    with urllib.request.urlopen(req2) as r:
        json.loads(r.read())

# ─── 📱 PWA assets ────────────────────────────────────────────────────────
PWA_MANIFEST = {
    "name": "Boss Business Hub",
    "short_name": "BossHub",
    "description": "Dashboard บอสอู๊ด — สวนยาง · ห้องเช่า · สงกราน",
    "start_url": "./",
    "display": "standalone",
    "orientation": "portrait",
    "background_color": "#1a1a2e",
    "theme_color": "#1a1a2e",
    "lang": "th",
    "icons": [
        {"src": "icon.svg", "sizes": "any",     "type": "image/svg+xml", "purpose": "any maskable"},
        {"src": "icon.svg", "sizes": "192x192", "type": "image/svg+xml"},
        {"src": "icon.svg", "sizes": "512x512", "type": "image/svg+xml"},
    ]
}
PWA_ICON_SVG = '''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#1a1a2e"/>
      <stop offset="100%" stop-color="#37474f"/>
    </linearGradient>
  </defs>
  <rect width="512" height="512" rx="96" fill="url(#bg)"/>
  <text x="256" y="200" font-size="120" text-anchor="middle" font-family="Apple Color Emoji,Segoe UI Emoji,sans-serif">📊</text>
  <text x="160" y="370" font-size="100" text-anchor="middle" font-family="Apple Color Emoji,Segoe UI Emoji,sans-serif">🌿</text>
  <text x="256" y="370" font-size="100" text-anchor="middle" font-family="Apple Color Emoji,Segoe UI Emoji,sans-serif">🏠</text>
  <text x="352" y="370" font-size="100" text-anchor="middle" font-family="Apple Color Emoji,Segoe UI Emoji,sans-serif">🎊</text>
  <text x="256" y="455" font-size="42" text-anchor="middle" fill="white" font-weight="bold" font-family="sans-serif">BossHub</text>
</svg>
'''
_SW_VER = datetime.now().strftime("%Y%m%d%H%M")
PWA_SW = '''// Service Worker — Boss Business Hub
const CACHE = 'bosshub-__VER__';
const ASSETS = ['./', './index.html', './manifest.json', './icon.svg'];
self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(ASSETS)).then(() => self.skipWaiting()));
});
self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(keys => Promise.all(
    keys.filter(k => k !== CACHE).map(k => caches.delete(k))
  )).then(() => self.clients.claim()));
});
// Network-first, fallback to cache (ข้อมูลล่าสุดได้ก่อน, offline ก็ใช้ได้)
self.addEventListener('fetch', e => {
  if (e.request.method !== 'GET') return;
  e.respondWith(
    fetch(e.request).then(r => {
      const copy = r.clone();
      caches.open(CACHE).then(c => c.put(e.request, copy)).catch(()=>{});
      return r;
    }).catch(() => caches.match(e.request).then(r => r || caches.match('./index.html')))
  );
});
'''.replace('__VER__', _SW_VER)

print("🚀 Push ขึ้น GitHub...")
try:
    with open(OUT_PATH, "rb") as f:
        html_bytes = f.read()
    push_file(GITHUB_FILE, html_bytes, f"update unified dashboard {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    push_file("manifest.json", json.dumps(PWA_MANIFEST, ensure_ascii=False, indent=2).encode("utf-8"))
    push_file("sw.js",         PWA_SW.encode("utf-8"))
    push_file("icon.svg",      PWA_ICON_SVG.encode("utf-8"))
    print(f"✅ Push สำเร็จ! (index.html + manifest.json + sw.js + icon.svg)")
    print(f"   🌐 https://pong-openclaw.github.io/farm-dashboard/")
    print(f"   📱 เปิดบนมือถือ → กด 'Add to Home Screen' เพื่อติดตั้งเป็นแอป")
except Exception as e:
    print(f"⚠️  Push ไม่สำเร็จ: {e}")
    print(f"   ไฟล์อยู่ที่: {OUT_PATH}")
