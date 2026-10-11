# 💈 Barbershop Telegram Queue Bot

O'zbekistondagi sartaroshxonalar (barbershop) uchun navbat boshqaruv Telegram boti.  
Telegram queue management bot for barbershops in Uzbekistan (`Asia/Tashkent`, UTC+5, currency UZS).

---

## 🇺🇿 O'zbekcha Qo'llanma

### 1. Imkoniyatlar
- **Ketma-ket navbat**: Kelish tartibida qat'iy ketma-ketlik. Har bir barberning o'z alohida navbati bor.
- **Avtomatik chaqirish va kechikishlar**: Navbati kelgan mijozga darhol xabar yuboriladi. 10 daqiqa vaqt beriladi. Agar kelmasa, navbati 1 o'ringa orqaga suriladi (ko'pi bilan 2 marta). 3-marta kelmasa, navbat bekor qilinadi.
- **Ogohlantirish (Heads-up)**: Oldinda 1 kishi qolganda mijozga "Yo'lga chiqing" xabari boradi.
- **To'lovlar**: Click, Payme, Paynet va Naqd. Yagona merchant hisobi, barberlar bo'yicha bot ichida hisob-kitob.
- **3 ta til**: O'zbek lotin (`uz`), O'zbek kirill (`uz_cyrl`), Rus (`ru`).
- **Rollar**:
  - **Owner (Katta Barber)**: O'z navbatiga ega, barberlarni taklif havolasi orqali qo'shadi, barcha navbatlarni ko'radi, hisobotlar (kun/hafta/oy) va reytingni ko'radi, qaytarishlarni boshqaradi, mijozni bloklaydi.
  - **Barber**: Faqat o'z navbatini va o'ziga kelgan to'lovlarni ko'radi (mijoz niki bilan). "Keldi", "Kelmadi", "Xizmat ko'rsatildi", "Naqd to'landi" tugmalarini boshqaradi. Jonli mijoz (Telegram'siz) qo'shishi mumkin.
  - **Client (Mijoz)**: Barber va xizmatni tanlaydi, navbat holati va kutilish vaqtini ko'radi, navbatga yoziladi yoki bekor qiladi.

---

### 2. Tezkor Ishga Tushirish (Quick Start)

#### 1-qadam: Bot yaratish va Token olish
1. Telegram'da [@BotFather](https://t.me/BotFather) botiga kiring.
2. `/newbot` buyrug'ini yuboring va bot nomi hamda username'ini belgilang.
3. BotFather bergan `API Token`ni nusxalab oling.
4. O'zingizning Telegram ID raqamingizni aniqlang (masalan, [@userinfobot](https://t.me/userinfobot) orqali).

#### 2-qadam: Konfiguratsiya
Katalogdagi `.env.example` faylidan `.env` nusxasini oling:
```bash
cp .env.example .env
```
`.env` faylini tahrirlang (xavfsiz 48+ belgili kalitlarni generatsiya qilish: `python -c "import secrets; print(secrets.token_urlsafe(48))"`):
```env
BOT_TOKEN=123456789:SIZNING_BOT_TOKENINGIZ
OWNER_TELEGRAM_IDS=SIZNING_TELEGRAM_ID
ENV=production
RUN_MODE=polling  # yoki webhook
PAYMENTS_MODE=test # yoki live
```

#### 3-qadam: Docker bilan ishga tushirish
```bash
docker compose up -d --build
```
Bot avtomatik tarzda ma'lumotlar bazasi migratsiyalarini qo'llaydi va ishga tushadi!

---

### 3. Barberlarni Qo'shish Jarayoni
1. Owner botga `/start` bosadi va asosiy menyudan `👥 Barberlar` bo'limiga kiradi.
2. `➕ Yangi barber taklif qilish` tugmasini bosadi.
3. Bot 24 soat amal qiluvchi bir martalik havola yaratadi (`https://t.me/bot?start=barber_<token>`).
4. Barber havolani ochadi -> Ismini kiritadi -> Telefon raqamini yuboradi (tugma orqali) -> Rasm yuboradi -> Barber sifatida avtomatik faollashadi!

---

### 4. VPS Serverga Domen bilan O'rnatish (Caddy + SSL)
1. VPS serveringizda DNS A-yozuvini domeningizga yo'naltiring (masalan, `barber.example.com` -> VPS IP).
2. `.env` faylida:
   ```env
   RUN_MODE=webhook
   DOMAIN=barber.example.com
   WEBHOOK_BASE_URL=https://barber.example.com
   WEBHOOK_SECRET=tasodifiy_32_belgili_kalit
   WEBHOOK_PATH_SECRET=tasodifiy_route_kalit
   INTERNAL_SCHEDULER=true
   ```
3. Konteynerlarni ishga tushiring:
   ```bash
   docker compose up -d --build
   ```
4. Webhookni ro'yxatdan o'tkazing:
   ```bash
   python scripts/set_webhook.py --url https://barber.example.com --drop-pending
   ```
Caddy avtomatik tarzda Let's Encrypt SSL sertifikatini oladi va HTTPS orqali botga yo'naltiradi.

---

## 🇬🇧 English Documentation

### 1. Overview & Architecture
- **Strict Sequential Queue**: Arrival order, no time slots. Each barber has an independent queue.
- **Automated Calling & Lateness**: Called client has 10 minutes to arrive (`LATE_MINUTES=10`). If late, position shifts back by 1 place (max 2 times). 3rd no-show triggers automatic cancellation (`CANCELLED_NO_SHOW`).
- **Heads-Up Alerts**: Sent when exactly 1 person is ahead.
- **Payments**: Click, Payme, Paynet, Cash. Single merchant bank account, per-barber bookkeeping.
- **Roles**:
  - **Owner**: Operates own queue, invites barbers via one-time deep links, views live queues, revenue reports (day/week/month with CSV export), ranking, handles manual refunds, blocks users.
  - **Barber**: Views only own queue and own incoming payments (with client nicknames). Marks "Arrived", "No-show", "Service Done", "Cash Paid". Adds walk-in clients.
  - **Client**: Books barber or any available barber, views live wait times, pays, tracks queue live.

---

### 2. Local & Serverless Execution

#### Run with Docker Compose
```bash
docker compose up -d --build
```

#### Run Tests
```bash
pytest tests/ -v
```

#### Run Day Simulation
```bash
python scripts/simulate_day.py
```

#### Code Quality (Ruff)
```bash
ruff check .
```

---

## 📁 Project Structure

```
├── app/
│   ├── main.py              # Application entrypoint (polling & webhook)
│   ├── config.py            # Pydantic Settings
│   ├── db/                  # Engine & Session handling
│   ├── models/              # SQLAlchemy 2.0 Async Models
│   ├── repositories/        # Database query repositories
│   ├── services/            # Queue engine, payments, due work, reports
│   ├── payments/            # Payme, Click, Paynet, Cash, Fake adapters
│   ├── keyboards/           # Reply & Inline keyboards
│   ├── handlers/            # Aiogram routers (client, barber, owner, payments)
│   ├── middlewares/         # Session, user context, throttling, error handler
│   ├── i18n/                # uz.yaml, uz_cyrl.yaml, ru.yaml catalogs
│   ├── scheduler/           # APScheduler 15s runner
│   ├── utils/               # Timezone (Asia/Tashkent) & formatting
│   └── web/                 # aiohttp webhook & /internal/tick server
├── migrations/              # Alembic migration scripts
├── tests/                   # Automated test suite (80+ tests)
├── scripts/
│   ├── simulate_day.py      # End-to-end simulated day script
│   └── set_webhook.py       # Telegram webhook registration CLI
├── docs/
│   ├── DECISIONS.md         # Architectural decisions & defaults
│   ├── KNOWN_LIMITATIONS.md # Real limits, dependencies & operational facts
│   ├── PAYMENTS.md          # Payment integration & live transition
│   └── SERVERLESS.md        # Google Cloud Run deployment guide
├── Dockerfile
├── docker-compose.yml
├── Caddyfile
├── Makefile
└── requirements.txt
```
