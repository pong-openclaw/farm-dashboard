# 🚀 คู่มือตั้งค่า Auto-Rebuild สำหรับปอง
## ทำครั้งเดียว — Dashboard อัปเดตอัตโนมัติตลอด

หลังทำเสร็จ ปองทำได้:
- ✅ แก้ข้อมูลใน Google Sheet → รอเช้าวันถัดไป → Dashboard อัปเดตเอง
- ✅ อยากอัปเดตด่วน → เปิด GitHub → คลิกปุ่ม "Run workflow" → รอ 2 นาที
- ✅ ไม่ต้องเปิดเครื่อง ไม่ต้องใช้ Claude Code

---

## ขั้นตอนที่ 1 — อัปเดต GitHub Token (5 นาที)

Token เดิมของปองต้องเพิ่มสิทธิ์ `workflow` เพื่อสร้าง Auto-Rebuild

1. เปิด https://github.com/settings/tokens
2. คลิก token ที่ใช้กับ Boss Business Hub (ชื่อ "BossHub" หรืออะไรก็ตาม)
3. เลื่อนลงหา **`workflow`** → ติ๊กถูก ✅
4. กด **Update token** ล่างสุด
5. **Copy token ใหม่** → บันทึกไว้ใน `C:\Users\USER\RubberFarm\.github_token`

---

## ขั้นตอนที่ 2 — สร้าง Google Service Account (10 นาที)

Service Account = "บัญชีหุ่นยนต์" ที่อ่าน Sheet ให้ GitHub Actions — Sheet ยัง **private** ตลอด ✅

### 2a. เปิด Google Cloud Console
1. เปิด https://console.cloud.google.com/
2. เลือก project ที่ต้องการ (หรือสร้างใหม่ชื่อ "BossBusinessHub")

### 2b. เปิดใช้ Google Sheets API
1. เมนู ☰ → **APIs & Services** → **Library**
2. ค้นหา `Google Sheets API` → คลิก → **Enable**

### 2c. สร้าง Service Account
1. เมนู ☰ → **APIs & Services** → **Credentials**
2. กด **+ CREATE CREDENTIALS** → **Service account**
3. ใส่ชื่อ: `bosshub-reader`
4. กด **Done** (ข้าม role ได้)

### 2d. ดาวน์โหลด JSON Key
1. คลิก service account ที่เพิ่งสร้าง (`bosshub-reader@...`)
2. แท็บ **Keys** → **Add Key** → **Create new key**
3. เลือก **JSON** → **Create**
4. ไฟล์ JSON จะดาวน์โหลดอัตโนมัติ — **เก็บไว้ อย่าลบ**

### 2e. Share Google Sheets ให้ Service Account
1. เปิดไฟล์ JSON ที่ดาวน์โหลด → หาค่า **`client_email`**
   - ตัวอย่าง: `bosshub-reader@your-project.iam.gserviceaccount.com`
2. เปิด Google Sheet **สวนยาง** → กด Share → วาง email นั้น → **Viewer** → Send
3. ทำซ้ำกับ Sheet **ห้องเช่า** และ **สงกราน**

---

## ขั้นตอนที่ 3 — ใส่ Secrets ใน GitHub (5 นาที)

1. เปิด https://github.com/pong-openclaw/farm-dashboard/settings/secrets/actions
2. กด **New repository secret** — เพิ่ม 2 อัน:

| Name | Value |
|------|-------|
| `PAT_TOKEN` | GitHub Token ใหม่จาก Step 1 |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | **เนื้อหาทั้งหมด** ของไฟล์ JSON จาก Step 2d (copy ทั้งไฟล์) |

---

## ขั้นตอนที่ 4 — ทดสอบ Manual Trigger (2 นาที)

1. เปิด https://github.com/pong-openclaw/farm-dashboard/actions
2. เลือก workflow **"Rebuild Dashboard"**
3. กด **Run workflow** → **Run workflow** อีกครั้ง
4. รอ 2-3 นาที → เห็น ✅ เขียว = สำเร็จ!
5. เปิด https://pong-openclaw.github.io/farm-dashboard/ → Ctrl+Shift+R → เห็นข้อมูลใหม่

---

## สรุป — ปองทำได้แล้ว

| งาน | วิธี |
|-----|------|
| 📝 อัปเดตข้อมูล | แก้ Google Sheet → รอเช้าวันถัดไป (07:00 น.) |
| ⚡ อัปเดตด่วน | GitHub → Actions → Run workflow → รอ 2 นาที |
| 👀 ดู Dashboard | https://pong-openclaw.github.io/farm-dashboard/ |
| 🤖 ถาม AI | กดปุ่ม 💬 ในหน้าเว็บ |
| 📧 รับ Alert | อีเมล pongnarin.jar@gmail.com ทุกวัน 08:00 |

**ไม่ต้องเปิดเครื่อง ไม่ต้องใช้ Claude Code นอกจากอยาก feature ใหม่** 🎉
