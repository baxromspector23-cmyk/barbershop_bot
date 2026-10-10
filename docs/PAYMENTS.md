# To'lov Tizimlari Hujjatlari (docs/PAYMENTS.md)

Ushbu hujjatda Barbershop Telegram botiga Click, Payme, Paynet va Naqd to'lov tizimlarini ulash bo'yicha batafsil ko'rsatmalar, talablar va cheklovlar bayon etilgan.

---

## 1. Umumiy Qoidalar va Pul Oqimi

1. **Yagona Merchant Hisobi**: Barcha to'lovlar (Click, Payme, Paynet) to'g'ridan-to'g'ri barbershopning yagona yuridik bank hisob raqamiga kelib tushadi. Har bir barber bo'yicha tushumlar bot ichida buxgalteriya hisobi (bookkeeping) sifatida yuritiladi.
2. **Daromad Qoidasi (Revenue Rule)**: Buyurtma faqatgina xizmat ko'rsatilib (`COMPLETED`) VA to'lov qilinganida (`PAID`) daromad sifatida hisoblanadi. Oldindan to'langan (`prepaid`), lekin bekor qilingan buyurtmalar daromad hisoblanmaydi.
3. **Idempotentlik**: Har bir to'lov `(method, provider_payment_id)` bo'yicha unikal tarzda saqlanadi. Bir xil to'lov tasdig'i qayta kelsa, ikkinchi to'lov yoki ikkinchi bildirishnoma yaratilmaydi.
4. **Valyuta birligi**: Telegram Payments tizimida O'zbekiston so'mi (UZS) ISO 4217 standarti bo'yicha 2 xonali (tiyin) hisoblanadi. Bot serveri narxni tiyinga aylantirib (`amount * 100`) yuboradi, mijoz va barber ekranlarida esa butun so'mda (`50 000 so'm`) aks ettiriladi.

---

## 2. Click va Payme (Telegram Payments)

Telegram Payments Click va Payme uchun rasmiy qulay integratsiyani taqdim etadi.

### Kerakli Hujjatlar va Ma'lumotlar:
1. Click va Payme bilan yuridik shaxs (MChJ yoki YaTT) nomidan rasmiy merchant shartnomasi tuziladi.
2. Telegram @BotFather botida quyidagi ketma-ketlik bajariladi:
   - `/mybots` -> Botingizni tanlang -> `Bot Settings` -> `Payments`
   - `Payme` yoki `Click` provayderini tanlang.
   - Shartnoma ma'lumotlarini (Merchant ID, Secret Key) kiritib, **Provider Token** oling.
3. Olingan tokenlarni `.env` fayliga yozing:
   ```env
   CLICK_PROVIDER_TOKEN=398061295:TEST:99999
   PAYME_PROVIDER_TOKEN=371317599:TEST:11111
   ```

### Testdan Jonli (Live) Rejimga O'tish:
1. Test rejimida BotFather sinov tokenlarini beradi (`...:TEST:...`).
2. `.env` faylida:
   ```env
   ENV=production
   PAYMENTS_MODE=live
   CLICK_PROVIDER_TOKEN=<haqiqiy_jonli_token>
   PAYME_PROVIDER_TOKEN=<haqiqiy_jonli_token>
   ```
   > **XAVFSIZLIK TEKSHIRUVI**: Agar `ENV=production` bo'lsa va `PAYMENTS_MODE=test` qoldirilsa, bot ishga tushishdan bosh tortadi (startup exception).

---

## 3. Paynet Integratsiyasi

### Texnik Holat va Talablar:
- Telegram Bot API tizimida Paynet uchun to'g'ridan-to'g'ri BotFather orqali beriladigan Provider Token mavjud emas.
- Paynet jonli integratsiyasi quyidagi talablarni talab qiladi:
  1. **Rasmiy Merchant Shartnomasi**: Paynet (YaTT yoki MChJ bilan).
  2. **Service ID va Maxfiy Kalit (Secret Key)**: Paynet ma'lumotlar bazasida ro'yxatdan o'tkazilgan xizmat identifikatori.
  3. **Raqamli Imzo (Signature)**: Har bir tranzaksiya so'rovi va javobi uchun HMAC-SHA256 yoki RSA imzo tekshiruvi.
  4. **Statik IP Oq Ro'yxati (IP Whitelisting)**: Paynet faqat ruxsat etilgan statik IP manzillardan keluvchi HTTPS so'rovlarini qabul qiladi.
  5. **TAS-IX Tarmog'i**: Server O'zbekiston ichki milliy tarmog'ida (TAS-IX) joylashgan bo'lishi lozim.

### Xavfsizlik Qoidasi va Rejim:
- Botda `PaynetProvider` adapteri tayyorlangan bo'lsa-da, haqiqiy callback serveri ulanmaguncha `PAYNET_ENABLED=true` holatida productionda ishga tushirish taqiqlangan (`validate_runtime()` startup paytida xato chiqaradi).
- Faqatgina `PAYNET_ENABLED=true` bo'lgandagina Paynet tugmasi mijoz klaviaturasida ko'rinadi.

---

## 4. Naqd To'lov (CASH)

- Mijoz `Xizmatdan keyin to'layman` variantini tanlaganda, xizmat tugagach barber `Naqd to'landi` tugmasini bosadi.
- Bot darhol bu to'lovni `PAID` deb qayd etadi va barber hisobotiga qo'shadi.

---

## 5. Qaytarishlar (Refunds)

- Tizim pullarni avtomatik tarzda qaytarmaydi (kartaga avtomatik pul qaytarish bank tranzaksiyasi komissiyalarini keltirib chiqarishi sababli).
- Agar oldindan to'langan buyurtma bekor qilinsa yoki mijoz 3 marta kelmasa:
  - To'lov holati `REFUND_PENDING` ga o'tkaziladi.
  - Egasi (Owner) `Qaytarish kutilmoqda` bo'limida ko'radi.
  - Egasi Click/Payme kabinetidan yoki naqd tarzda pulni qaytargach, `Qaytarildi` tugmasini bosadi (`REFUNDED`).

---

## 6. Haqiqiy Hisob Ma'lumotlarisiz Tekshirib Bo'lmaydigan Narsalar (NOT VERIFIED)

Quyidagilar faqat haqiqiy shartnoma va jonli to'lov ma'lumotlari bilan tekshirilishi mumkin:
1. Haqiqiy bank kartasidan (Uzcard/Humo) real pul yechilishi.
2. BotFather jonli to'lov tokenlarining Telegram klasterlari bilan aloqasi.
3. Paynet serverining TAS-IX orqali yuboradigan haqiqiy JSON-RPC so'rovlari.
Botning barcha ichki to'lov holatlari, kvitansiya xabarlari, buxgalteriya hisobi, dublikat to'lovlarni bloklash va tushum hisob-kitoblari avtomatlashtirilgan testlar va simulyatsiya orqali tekshirilgan.
