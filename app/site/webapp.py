from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
from typing import Any

import aiohttp
from aiohttp import web

logger = logging.getLogger("barbershop_bot.webapp")

WEBAPP_SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(self), microphone=()",
    "Content-Security-Policy": (
        "default-src 'self' https: data: blob:; "
        "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://telegram.org https://cdn.jsdelivr.net; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com data:; "
        "img-src 'self' data: blob: https:; "
        "media-src 'self' data: blob: mediastream:; "
        "connect-src 'self' https:; "
        "frame-ancestors *"
    ),
}

# Detailed catalog of men's hairstyles and beard styles
HAIRSTYLES_CATALOG: list[dict[str, Any]] = [
    {
        "id": "low_fade_crop",
        "name_uz": "Low Fade + Textured Crop",
        "name_ru": "Low Fade + Текстурный Кроп",
        "badge_uz": "🔥 Eng mashhur",
        "desc_uz": "Yon tomonlari pastdan silliq o'tish (Low Fade) va tepasi teksturali zamonaviy turmak.",
        "best_shapes": ["oval", "square", "diamond", "round"],
        "prompt": "modern men low fade textured french crop haircut, sharp hairline, barbershop studio quality",
    },
    {
        "id": "high_skin_fade_quiff",
        "name_uz": "High Skin Fade + Quiff",
        "name_ru": "High Skin Fade + Квифф",
        "badge_uz": "⚡ Hajmli & Kuchli",
        "desc_uz": "Yonlari nolga yaqin baland fade, old qismi ko'tarilgan hajmli Quiff uslubi.",
        "best_shapes": ["round", "oval", "square"],
        "prompt": "men high skin fade textured quiff hairstyle, volumetric top, clean fade sides",
    },
    {
        "id": "classic_side_part",
        "name_uz": "Classic Side Part (Klassika)",
        "name_ru": "Классический Боковой Пробор",
        "badge_uz": "👔 Biznes & Rasmiy",
        "desc_uz": "Yonga taralgan an'anaviy, tartibli va har qanday kiyimga mos tushuvchi klassik stil.",
        "best_shapes": ["oval", "square", "oblong", "diamond"],
        "prompt": "men classic gentleman side part taper fade haircut, neat combed hair, executive look",
    },
    {
        "id": "modern_pompadour",
        "name_uz": "Modern Pompadour",
        "name_ru": "Современный Помпадур",
        "badge_uz": "👑 Premium",
        "desc_uz": "Tepa qismi orqaga va yuqoriga silliq taralgan, yuzni uzunroq va chiroyli ko'rsatuvchi turmak.",
        "best_shapes": ["round", "oval", "square"],
        "prompt": "men modern pompadour mid fade haircut, slick volumetric top",
    },
    {
        "id": "buzz_cut_fade",
        "name_uz": "Buzz Cut + Mid Drop Fade",
        "name_ru": "Бокс / Buzz Cut + Фейд",
        "badge_uz": "💪 Sport & Minimal",
        "desc_uz": "Kalta, parvarishi oson, jag' chiziqlarini keskin va erkakcha ko'rsatuvchi harbiy-sport uslubi.",
        "best_shapes": ["square", "oval", "diamond"],
        "prompt": "men buzz cut with mid drop skin fade and sharp line up",
    },
    {
        "id": "undercut_slick",
        "name_uz": "Disconnected Undercut",
        "name_ru": "Андеркат (Undercut)",
        "badge_uz": "✨ Kontrast",
        "desc_uz": "Yonlari kalta va tepasi uzun kontrastli zamonaviy yoshlar uslubi.",
        "best_shapes": ["oval", "round", "diamond"],
        "prompt": "men disconnected undercut slick back textured hair",
    },
    {
        "id": "french_crop",
        "name_uz": "French Crop (Fransuzcha)",
        "name_ru": "Френч Кроп (French Crop)",
        "badge_uz": "🎯 Trend 2026",
        "desc_uz": "Peshona qismi tekis chiziqli va tepasi qalin teksturali zamonaviy Yevropa uslubi.",
        "best_shapes": ["oblong", "oval", "diamond", "square"],
        "prompt": "men sharp french crop haircut with mid taper fade",
    },
    {
        "id": "curly_taper",
        "name_uz": "Curly / Wavy Drop Fade",
        "name_ru": "Кудрявый / Волнистый Фейд",
        "badge_uz": "🌊 To'lqinli soch",
        "desc_uz": "Jingalak yoki to'lqinli sochlar uchun tabiiy hajm va toza yon fade uyg'unligi.",
        "best_shapes": ["oval", "oblong", "diamond", "round"],
        "prompt": "men curly wavy top haircut with clean drop fade",
    },
    {
        "id": "modern_mullet",
        "name_uz": "Modern Burst Fade Mullet",
        "name_ru": "Современный Маллет (Burst Fade)",
        "badge_uz": "🔥 Yoshlarbop",
        "desc_uz": "Quloq atrofi yarim oy (Burst fade) va orqa qismi teksturali zamonaviy trend.",
        "best_shapes": ["oval", "diamond", "square"],
        "prompt": "men modern burst fade textured mullet haircut",
    },
    {
        "id": "textured_fringe",
        "name_uz": "Textured Messy Fringe",
        "name_ru": "Текстурная Чёлка (Fringe)",
        "badge_uz": "🌟 Tabiiy ko'rinish",
        "desc_uz": "Oldinga tushib turuvchi erkin, yengil va peshonani yopuvchi teksturali uslub.",
        "best_shapes": ["oblong", "diamond", "oval"],
        "prompt": "men textured messy fringe haircut with low taper",
    },
]

BEARD_CATALOG: list[dict[str, Any]] = [
    {"id": "none", "name_uz": "Soqolsiz (Toza)", "name_ru": "Без бороды"},
    {"id": "stubble", "name_uz": "Yengil soqol (Stubble)", "name_ru": "Лёгкая щетина"},
    {"id": "fade_beard", "name_uz": "Fade Soqol (Konturli)", "name_ru": "Фейд борода с контуром"},
    {"id": "full_beard", "name_uz": "Qalin To'liq Soqol", "name_ru": "Полная густая борода"},
    {"id": "goatee", "name_uz": "Goatee (Espanyolka)", "name_ru": "Эспаньолка (Goatee)"},
]


async def _call_optional_cloud_ai(
    image_b64: str,
    style_obj: dict[str, Any],
    beard_obj: dict[str, Any],
    hair_color: str,
    face_shape: str,
) -> dict[str, Any] | None:
    """
    Optional cloud AI enhancement if GEMINI_API_KEY or OPENAI_API_KEY is configured in environment.
    Returns extra AI stylist commentary or generated image URL/base64 when available.
    """
    gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()
    openai_key = os.environ.get("OPENAI_API_KEY", "").strip()

    if gemini_key:
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={gemini_key}"
            raw_b64 = image_b64.split(",", 1)[-1] if "," in image_b64 else image_b64
            payload = {
                "contents": [
                    {
                        "parts": [
                            {
                                "text": (
                                    f"Sen professional sartarosh-stilistsan. Mijozning yuz shakli: {face_shape}. "
                                    f"Tanlangan soch turmagi: {style_obj['name_uz']}, soqol: {beard_obj['name_uz']}, "
                                    f"rang: {hair_color}. Shu mijozning yuz tuzilishiga mos 2-3 jumlalik aniq, "
                                    "qisqa va foydali o'zbek tilidagi tavsiya yozib ber."
                                )
                            },
                            {
                                "inline_data": {
                                    "mime_type": "image/jpeg",
                                    "data": raw_b64[:400000],
                                }
                            },
                        ]
                    }
                ]
            }
            timeout = aiohttp.ClientTimeout(total=8)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, json=payload) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        candidates = data.get("candidates") or []
                        if candidates:
                            parts = candidates[0].get("content", {}).get("parts", [])
                            if parts and "text" in parts[0]:
                                return {"ai_advice": parts[0]["text"].strip(), "engine": "gemini"}
        except Exception as exc:
            logger.debug("Optional Gemini API call skipped: %s", exc)

    if openai_key:
        try:
            url = "https://api.openai.com/v1/chat/completions"
            headers = {"Authorization": f"Bearer {openai_key}", "Content-Type": "application/json"}
            payload = {
                "model": "gpt-4o-mini",
                "messages": [
                    {
                        "role": "system",
                        "content": "Sen professional barbershop AI stilistisan. O'zbek tilida qisqa (2-3 gap) tavsiya ber.",
                    },
                    {
                        "role": "user",
                        "content": (
                            f"Yuz shakli: {face_shape}. Soch: {style_obj['name_uz']}. "
                            f"Soqol: {beard_obj['name_uz']}. Rang: {hair_color}."
                        ),
                    },
                ],
                "max_tokens": 160,
            }
            timeout = aiohttp.ClientTimeout(total=8)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, headers=headers, json=payload) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        choices = data.get("choices") or []
                        if choices:
                            txt = choices[0].get("message", {}).get("content", "").strip()
                            if txt:
                                return {"ai_advice": txt, "engine": "openai"}
        except Exception as exc:
            logger.debug("Optional OpenAI API call skipped: %s", exc)

    return None


def _build_smart_stylist_advice(
    style_obj: dict[str, Any],
    beard_obj: dict[str, Any],
    face_shape: str,
    hair_color: str,
) -> dict[str, Any]:
    shape_labels = {
        "oval": ("Oval (Ideal muvozanat)", 98),
        "square": ("Kvadrat (Kuchli jag' chizig'i)", 96),
        "round": ("Dumaloq (Yumshoq burchaklar)", 94),
        "diamond": ("Olmos (Yanoq suyaklari aniqligi)", 95),
        "oblong": ("Uzunchoq (Cho'zinchoq proporsiya)", 93),
    }
    shape_title, base_score = shape_labels.get(face_shape, ("Oval (Universal)", 96))
    is_best = face_shape in style_obj.get("best_shapes", [])
    match_score = min(99, base_score + (2 if is_best else -3))

    color_names = {
        "natural_black": "Tabiiy Qora",
        "dark_brown": "To'q Jigarrang (Espresso)",
        "ash_graphite": "Kulrang Grafit (Silver Ash)",
        "warm_chestnut": "Kashtan / Oltin Jigarrang",
    }
    color_label = color_names.get(hair_color, "Tabiiy Qora")

    recommended_styles = [
        s["id"] for s in HAIRSTYLES_CATALOG if face_shape in s.get("best_shapes", [])
    ][:4]

    advice = (
        f"✨ Sizning yuz tuzilishingiz — {shape_title}. "
        f"«{style_obj['name_uz']}» turmagi va «{beard_obj['name_uz']}» uyg'unligi yuz proporsiyasini "
        f"{match_score}% aniqlikda ochib beradi. {style_obj['desc_uz']} "
        f"Tanlangan tus: {color_label} — sartaroshga ushbu tayyor variantni ko'rsatib xuddi shunday qirqishni so'rashingiz mumkin!"
    )

    return {
        "ok": True,
        "face_shape": face_shape,
        "face_shape_title": shape_title,
        "match_score": match_score,
        "style_id": style_obj["id"],
        "style_name": style_obj["name_uz"],
        "beard_id": beard_obj["id"],
        "beard_name": beard_obj["name_uz"],
        "hair_color": color_label,
        "recommended_styles": recommended_styles,
        "ai_advice": advice,
        "engine": "smart_hybrid_ai",
    }


async def handle_webapp_generate(request: web.Request) -> web.Response:
    try:
        payload = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "Invalid JSON"}, status=400)

    style_id = str(payload.get("style_id") or "low_fade_crop")
    beard_id = str(payload.get("beard_id") or "fade_beard")
    face_shape = str(payload.get("face_shape") or "oval")
    hair_color = str(payload.get("hair_color") or "natural_black")
    image_b64 = str(payload.get("image") or "")

    style_obj = next((s for s in HAIRSTYLES_CATALOG if s["id"] == style_id), HAIRSTYLES_CATALOG[0])
    beard_obj = next((b for b in BEARD_CATALOG if b["id"] == beard_id), BEARD_CATALOG[0])

    result = _build_smart_stylist_advice(style_obj, beard_obj, face_shape, hair_color)

    if image_b64:
        cloud_res = await _call_optional_cloud_ai(image_b64, style_obj, beard_obj, hair_color, face_shape)
        if cloud_res:
            result.update(cloud_res)

    return web.json_response(result)


_WEBAPP_HTML = r"""<!DOCTYPE html>
<html lang="uz">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">
  <title>AI Soch &amp; Soqol Stilisti — Jasur Barber</title>
  <script src="https://telegram.org/js/telegram-web-app.js"></script>
  <style>
    :root {
      --bg: #080a0f;
      --card: rgba(18, 22, 32, 0.92);
      --card-2: rgba(26, 32, 46, 0.95);
      --gold: #d4af37;
      --gold-light: #f5e6b3;
      --gold-dark: #9e7b12;
      --text: #f8fafc;
      --muted: #94a3b8;
      --success: #22c55e;
      --border: rgba(212, 175, 55, 0.28);
    }
    * { box-sizing: border-box; -webkit-tap-highlight-color: transparent; }
    body {
      margin: 0;
      padding: 0 0 96px 0;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      background: radial-gradient(circle at 20% 0%, rgba(212,175,55,0.16), transparent 45%),
                  radial-gradient(circle at 80% 90%, rgba(185,28,28,0.10), transparent 45%),
                  var(--bg);
      color: var(--text);
      min-height: 100vh;
      overflow-x: hidden;
    }
    .pole-bar {
      height: 4px;
      background: repeating-linear-gradient(-45deg, #b91c1c 0 12px, #f8fafc 12px 24px, #1d4ed8 24px 36px, #f8fafc 36px 48px);
    }
    .wrap {
      max-width: 520px;
      margin: 0 auto;
      padding: 14px 14px 28px;
    }
    .top-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 16px;
      padding: 12px 15px;
      margin-bottom: 14px;
      box-shadow: 0 10px 28px rgba(0,0,0,0.45);
    }
    .brand-left {
      display: flex;
      align-items: center;
      gap: 10px;
    }
    .logo-circle {
      width: 40px;
      height: 40px;
      border-radius: 12px;
      background: linear-gradient(135deg, rgba(212,175,55,0.28), rgba(212,175,55,0.06));
      border: 1px solid var(--gold);
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 20px;
    }
    .brand-title {
      font-weight: 800;
      font-size: 16px;
      color: var(--gold-light);
      letter-spacing: 0.3px;
    }
    .brand-sub {
      font-size: 11.5px;
      color: var(--muted);
    }
    .ai-badge {
      background: linear-gradient(135deg, #e5c158, #b5891c);
      color: #080a0f;
      font-weight: 800;
      font-size: 11px;
      padding: 5px 10px;
      border-radius: 999px;
      letter-spacing: 0.4px;
      box-shadow: 0 0 16px rgba(212,175,55,0.35);
    }

    /* Stage / Preview Card */
    .stage-card {
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 18px;
      padding: 14px;
      margin-bottom: 14px;
      box-shadow: 0 14px 34px rgba(0,0,0,0.55);
      position: relative;
    }
    .viewport-box {
      position: relative;
      width: 100%;
      aspect-ratio: 3 / 3.7;
      max-height: 430px;
      background: #0d111a;
      border-radius: 14px;
      overflow: hidden;
      border: 1px solid rgba(255,255,255,0.1);
      display: flex;
      align-items: center;
      justify-content: center;
    }
    video#cameraVideo, canvas#mainCanvas {
      width: 100%;
      height: 100%;
      object-fit: cover;
      display: none;
    }
    video#cameraVideo {
      transform: scaleX(-1);
    }
    .face-guide-overlay {
      position: absolute;
      inset: 0;
      pointer-events: none;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
    }
    .face-oval {
      width: 58%;
      height: 68%;
      border: 2px dashed rgba(212, 175, 55, 0.78);
      border-radius: 50% 50% 46% 46% / 44% 44% 56% 56%;
      box-shadow: 0 0 0 9999px rgba(6, 8, 14, 0.42), inset 0 0 24px rgba(212, 175, 55, 0.22);
      transition: all 0.25s ease;
    }
    .guide-hint {
      margin-top: 10px;
      background: rgba(8, 10, 15, 0.82);
      border: 1px solid var(--border);
      color: var(--gold-light);
      font-size: 12px;
      font-weight: 600;
      padding: 5px 12px;
      border-radius: 999px;
      z-index: 2;
    }
    .empty-state {
      text-align: center;
      padding: 24px 18px;
      z-index: 2;
    }
    .empty-icon {
      width: 68px;
      height: 68px;
      border-radius: 50%;
      margin: 0 auto 12px;
      background: radial-gradient(circle, rgba(212,175,55,0.24), rgba(212,175,55,0.04));
      border: 1.5px solid var(--gold);
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 30px;
      box-shadow: 0 0 24px rgba(212,175,55,0.25);
    }
    .empty-title {
      font-size: 17px;
      font-weight: 700;
      color: #fff;
      margin-bottom: 6px;
    }
    .empty-desc {
      font-size: 13px;
      color: var(--muted);
      line-height: 1.45;
      margin-bottom: 18px;
    }
    .btn-row {
      display: flex;
      gap: 9px;
      justify-content: center;
      flex-wrap: wrap;
    }
    .btn {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 7px;
      padding: 11px 16px;
      border-radius: 12px;
      font-weight: 700;
      font-size: 13.5px;
      border: none;
      cursor: pointer;
      transition: transform 0.15s ease, filter 0.15s ease;
      text-decoration: none;
    }
    .btn:active { transform: scale(0.97); }
    .btn-gold {
      background: linear-gradient(135deg, #edd071 0%, #d4af37 55%, #aa820a 100%);
      color: #090b10;
      box-shadow: 0 5px 18px rgba(212,175,55,0.32);
    }
    .btn-dark {
      background: rgba(255,255,255,0.08);
      color: var(--text);
      border: 1px solid rgba(255,255,255,0.16);
    }
    .btn-sm {
      padding: 8px 12px;
      font-size: 12.5px;
      border-radius: 10px;
    }

    /* Floating overlays on canvas */
    .canvas-top-badges {
      position: absolute;
      top: 10px;
      left: 10px;
      right: 10px;
      display: none;
      justify-content: space-between;
      align-items: center;
      z-index: 4;
      pointer-events: none;
    }
    .pill-badge {
      background: rgba(9, 11, 16, 0.84);
      backdrop-filter: blur(8px);
      border: 1px solid var(--border);
      color: var(--gold-light);
      padding: 5px 10px;
      border-radius: 999px;
      font-size: 11.5px;
      font-weight: 700;
    }
    .pill-match {
      background: rgba(22, 163, 74, 0.88);
      color: #fff;
      padding: 5px 10px;
      border-radius: 999px;
      font-size: 11.5px;
      font-weight: 800;
    }
    .compare-btn {
      position: absolute;
      bottom: 10px;
      right: 10px;
      z-index: 5;
      display: none;
      background: rgba(9, 11, 16, 0.86);
      border: 1px solid var(--gold);
      color: var(--gold-light);
      padding: 7px 12px;
      border-radius: 10px;
      font-size: 12px;
      font-weight: 700;
      cursor: pointer;
      user-select: none;
    }

    /* Fine-tune hair adjustment bar */
    .adjust-bar {
      display: none;
      margin-top: 11px;
      padding-top: 10px;
      border-top: 1px solid rgba(255,255,255,0.08);
      gap: 8px;
      align-items: center;
      justify-content: space-between;
      flex-wrap: wrap;
    }
    .adjust-group {
      display: flex;
      align-items: center;
      gap: 6px;
      font-size: 11.5px;
      color: var(--muted);
    }
    .mini-ctrl {
      width: 28px;
      height: 28px;
      border-radius: 8px;
      background: rgba(255,255,255,0.08);
      border: 1px solid rgba(255,255,255,0.14);
      color: #fff;
      font-weight: 700;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      justify-content: center;
    }

    /* 4 Variants Mini Grid */
    .variants-section {
      display: none;
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 16px;
      padding: 13px;
      margin-bottom: 14px;
    }
    .sec-title {
      font-size: 13.5px;
      font-weight: 800;
      color: var(--gold-light);
      margin: 0 0 10px 0;
      display: flex;
      align-items: center;
      justify-content: space-between;
    }
    .variants-grid {
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 8px;
    }
    .variant-item {
      background: #0d111a;
      border: 1.5px solid rgba(255,255,255,0.12);
      border-radius: 11px;
      overflow: hidden;
      cursor: pointer;
      text-align: center;
      transition: all 0.2s ease;
    }
    .variant-item.active {
      border-color: var(--gold);
      box-shadow: 0 0 12px rgba(212,175,55,0.38);
      transform: translateY(-2px);
    }
    .variant-item canvas {
      width: 100%;
      aspect-ratio: 1 / 1.15;
      display: block;
      object-fit: cover;
    }
    .variant-label {
      font-size: 10px;
      font-weight: 700;
      color: var(--text);
      padding: 4px 3px;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      background: rgba(9, 11, 16, 0.9);
    }

    /* Controls Card */
    .panel-card {
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 16px;
      padding: 14px;
      margin-bottom: 14px;
    }
    .chips-scroll {
      display: flex;
      gap: 8px;
      overflow-x: auto;
      padding-bottom: 4px;
      scrollbar-width: none;
    }
    .chips-scroll::-webkit-scrollbar { display: none; }
    .chip {
      flex: 0 0 auto;
      padding: 8px 13px;
      border-radius: 11px;
      background: rgba(255,255,255,0.05);
      border: 1px solid rgba(255,255,255,0.12);
      color: var(--text);
      font-size: 12.5px;
      font-weight: 600;
      cursor: pointer;
      transition: all 0.18s ease;
    }
    .chip.active {
      background: linear-gradient(135deg, rgba(212,175,55,0.28), rgba(212,175,55,0.10));
      border-color: var(--gold);
      color: var(--gold-light);
      box-shadow: 0 3px 12px rgba(212,175,55,0.2);
    }

    /* Hairstyles Cards Grid */
    .styles-grid {
      display: grid;
      grid-template-columns: repeat(2, 1fr);
      gap: 9px;
      margin-top: 8px;
    }
    .style-card {
      background: var(--card-2);
      border: 1.5px solid rgba(255,255,255,0.09);
      border-radius: 13px;
      padding: 10px 11px;
      cursor: pointer;
      transition: all 0.18s ease;
      position: relative;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
    }
    .style-card.active {
      border-color: var(--gold);
      background: linear-gradient(145deg, rgba(212,175,55,0.19), rgba(18,22,32,0.95));
      box-shadow: 0 4px 16px rgba(212,175,55,0.25);
    }
    .style-badge {
      display: inline-block;
      font-size: 10px;
      font-weight: 700;
      color: var(--gold-light);
      background: rgba(212,175,55,0.14);
      border: 1px solid rgba(212,175,55,0.3);
      padding: 2px 7px;
      border-radius: 999px;
      margin-bottom: 5px;
      align-self: flex-start;
    }
    .style-name {
      font-size: 13px;
      font-weight: 700;
      color: #fff;
      margin-bottom: 3px;
    }
    .style-desc {
      font-size: 11px;
      color: var(--muted);
      line-height: 1.3;
    }

    /* Color Swatches */
    .color-row {
      display: flex;
      gap: 10px;
      align-items: center;
      flex-wrap: wrap;
    }
    .color-swatch {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 6px 11px;
      border-radius: 999px;
      background: rgba(255,255,255,0.05);
      border: 1.5px solid rgba(255,255,255,0.14);
      font-size: 12px;
      font-weight: 600;
      color: var(--text);
      cursor: pointer;
    }
    .color-swatch.active {
      border-color: var(--gold);
      color: var(--gold-light);
      background: rgba(212,175,55,0.15);
    }
    .dot {
      width: 14px;
      height: 14px;
      border-radius: 50%;
      border: 1px solid rgba(255,255,255,0.4);
    }

    /* AI Advice Box */
    .ai-advice-card {
      background: linear-gradient(135deg, rgba(212,175,55,0.16), rgba(18,22,32,0.95));
      border: 1px solid var(--gold);
      border-radius: 15px;
      padding: 13px 14px;
      margin-bottom: 14px;
      font-size: 13px;
      line-height: 1.48;
      color: #f1f5f9;
    }

    /* Sticky Bottom Action Bar */
    .bottom-bar {
      position: fixed;
      left: 0;
      right: 0;
      bottom: 0;
      background: rgba(9, 11, 16, 0.94);
      backdrop-filter: blur(14px);
      border-top: 1px solid var(--border);
      padding: 10px 14px 14px;
      z-index: 50;
    }
    .bottom-inner {
      max-width: 520px;
      margin: 0 auto;
      display: flex;
      gap: 8px;
    }
    .btn-book {
      flex: 1;
      padding: 13px 16px;
      font-size: 14.5px;
      border-radius: 13px;
    }
  </style>
</head>
<body>
  <div class="pole-bar"></div>
  <div class="wrap">
    <div class="top-header">
      <div class="brand-left">
        <div class="logo-circle">💈</div>
        <div>
          <div class="brand-title">JASUR BARBER AI</div>
          <div class="brand-sub">Yuz shakliga mos 3D/AI soch va soqol tanlash</div>
        </div>
      </div>
      <span class="ai-badge">✨ AI PRO</span>
    </div>

    <!-- Main Camera / Photo Viewport -->
    <div class="stage-card">
      <div class="viewport-box" id="viewportBox">
        <video id="cameraVideo" autoplay playsinline muted></video>
        <canvas id="mainCanvas" width="720" height="888"></canvas>

        <div class="canvas-top-badges" id="canvasBadges">
          <span class="pill-badge" id="faceShapeBadge">🧠 Yuz: Oval</span>
          <span class="pill-match" id="matchBadge">🔥 98% Mos</span>
        </div>

        <button type="button" class="compare-btn" id="compareBtn">👁 Oldin / Keyin</button>

        <div class="face-guide-overlay" id="faceGuideOverlay" style="display:none;">
          <div class="face-oval"></div>
          <div class="guide-hint">Yuzingizni oval markaziga joylashtiring</div>
        </div>

        <div class="empty-state" id="emptyState">
          <div class="empty-icon">🤳</div>
          <div class="empty-title">Yuzingizga mos soch turmagini ko'ring!</div>
          <div class="empty-desc">
            Kamerani yoqib selfi tushing yoki galereyadan rasm yuklang.
            AI yuzingiz shaklini tahlil qilib, <b>10 xil soch</b> va <b>5 xil soqol</b> turini yuzingizga chizib ko'rsatadi.
          </div>
          <div class="btn-row">
            <button type="button" class="btn btn-gold" id="startCameraBtn">📷 Kamerani yoqish</button>
            <label for="fileInput" class="btn btn-dark" style="cursor:pointer;">🖼 Rasm yuklash</label>
            <button type="button" class="btn btn-dark btn-sm" id="demoFaceBtn">🧑 Demo modelda sinash</button>
          </div>
        </div>
      </div>

      <!-- Camera Active Shutter Controls -->
      <div class="btn-row" id="cameraControls" style="display:none; margin-top:12px;">
        <button type="button" class="btn btn-gold" id="capturePhotoBtn" style="flex:1;">📸 Suratga olish va AI tahlil</button>
        <button type="button" class="btn btn-dark" id="cancelCameraBtn">✖ Bekor</button>
      </div>

      <!-- Loaded Photo Action Controls -->
      <div class="adjust-bar" id="adjustBar">
        <div class="adjust-group">
          <span>Joylashuv:</span>
          <button type="button" class="mini-ctrl" data-adj="up" title="Yuqoriga">↑</button>
          <button type="button" class="mini-ctrl" data-adj="down" title="Pastga">↓</button>
          <button type="button" class="mini-ctrl" data-adj="smaller" title="Kichraytirish">−</button>
          <button type="button" class="mini-ctrl" data-adj="larger" title="Kattalashtirish">+</button>
        </div>
        <div class="adjust-group">
          <button type="button" class="btn btn-dark btn-sm" id="retakeBtn">🔄 Yangi rasm</button>
          <button type="button" class="btn btn-dark btn-sm" id="downloadBtn">📥 Saqlash</button>
        </div>
      </div>

      <input type="file" id="fileInput" accept="image/*" style="display:none;">
    </div>

    <!-- 4 AI Multi-Variant Previews -->
    <div class="variants-section" id="variantsSection">
      <div class="sec-title">
        <span>🎨 Yuzingiz uchun 4 ta Top AI Variant</span>
        <span style="font-size:11px; color:var(--muted); font-weight:500;">Bosib tanlang</span>
      </div>
      <div class="variants-grid" id="variantsGrid"></div>
    </div>

    <!-- AI Stylist Recommendation Box -->
    <div class="ai-advice-card" id="aiAdviceBox">
      ✨ <b>AI Stilist:</b> Suratga tushing yoki rasm yuklang — biz yuzingiz proporsiyasini o'lchab, sizga eng yarashadigan soch va soqol variantlarini chizib beramiz!
    </div>

    <!-- Face Shape Selector (Auto-detected + Manual Override) -->
    <div class="panel-card">
      <div class="sec-title">
        <span>📐 Yuzingiz shakli (AI Avto-aniqlash)</span>
      </div>
      <div class="chips-scroll" id="faceShapeChips">
        <button type="button" class="chip active" data-shape="oval">🥚 Oval</button>
        <button type="button" class="chip" data-shape="square">🟦 Kvadrat</button>
        <button type="button" class="chip" data-shape="round">⚪ Dumaloq</button>
        <button type="button" class="chip" data-shape="diamond">💎 Olmos</button>
        <button type="button" class="chip" data-shape="oblong">📏 Uzunchoq</button>
      </div>
    </div>

    <!-- Hair Color Picker -->
    <div class="panel-card">
      <div class="sec-title">
        <span>🎨 Soch va Soqol rangi</span>
      </div>
      <div class="color-row" id="colorSwatches">
        <div class="color-swatch active" data-color="natural_black">
          <span class="dot" style="background:#141418;"></span> Qora
        </div>
        <div class="color-swatch" data-color="dark_brown">
          <span class="dot" style="background:#382417;"></span> To'q jigarrang
        </div>
        <div class="color-swatch" data-color="warm_chestnut">
          <span class="dot" style="background:#633d24;"></span> Kashtan
        </div>
        <div class="color-swatch" data-color="ash_graphite">
          <span class="dot" style="background:#707782;"></span> Kulrang / Silver
        </div>
      </div>
    </div>

    <!-- Beard Style Selector -->
    <div class="panel-card">
      <div class="sec-title">
        <span>🧔 Soqol uslubi</span>
      </div>
      <div class="chips-scroll" id="beardChips"></div>
    </div>

    <!-- 10 Hairstyles Catalog -->
    <div class="panel-card">
      <div class="sec-title">
        <span>💇‍♂️ Soch turmaklari (10 xil variant)</span>
      </div>
      <div class="styles-grid" id="stylesGrid"></div>
    </div>
  </div>

  <!-- Bottom Sticky CTA -->
  <div class="bottom-bar">
    <div class="bottom-inner">
      <button type="button" class="btn btn-gold btn-book" id="bookWithStyleBtn">
        💈 Shu turmak bilan navbatga yozilish
      </button>
    </div>
  </div>

  <script>
    (function() {
      const tg = window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null;
      if (tg) {
        try {
          tg.ready();
          tg.expand();
        } catch (e) {}
      }

      const HAIRSTYLES = [
        { id: "low_fade_crop", name: "Low Fade + Crop", badge: "🔥 Eng mashhur", desc: "Yonlari pastdan fade va tepasi teksturali", shapes: ["oval","square","diamond","round"] },
        { id: "high_skin_fade_quiff", name: "High Fade + Quiff", badge: "⚡ Hajmli", desc: "Yonlari nol fade va oldi ko'tarilgan Quiff", shapes: ["round","oval","square"] },
        { id: "classic_side_part", name: "Classic Side Part", badge: "👔 Klassika", desc: "Yonga taralgan rasmiy jentlmen uslubi", shapes: ["oval","square","oblong","diamond"] },
        { id: "modern_pompadour", name: "Modern Pompadour", badge: "👑 Premium", desc: "Yuqoriga va orqaga silliq hajmli taralgan", shapes: ["round","oval","square"] },
        { id: "buzz_cut_fade", name: "Buzz Cut + Fade", badge: "💪 Sport", desc: "Kalta, keskin konturli erkakcha uslub", shapes: ["square","oval","diamond"] },
        { id: "undercut_slick", name: "Undercut Slick", badge: "✨ Kontrast", desc: "Yonlari kalta, tepasi uzun kontrastli", shapes: ["oval","round","diamond"] },
        { id: "french_crop", name: "French Crop", badge: "🎯 Trend 2026", desc: "Peshona chizig'i aniq va qalin tekstura", shapes: ["oblong","oval","diamond","square"] },
        { id: "curly_taper", name: "Curly Drop Fade", badge: "🌊 Jingalak", desc: "To'lqinli/jingalak hajm va toza drop fade", shapes: ["oval","oblong","diamond","round"] },
        { id: "modern_mullet", name: "Burst Fade Mullet", badge: "🔥 Yoshlarbop", desc: "Quloq atrofi yarim oy fade va zamonaviy orqa", shapes: ["oval","diamond","square"] },
        { id: "textured_fringe", name: "Textured Fringe", badge: "🌟 Tabiiy", desc: "Oldinga tushgan erkin teksturali chiziqlar", shapes: ["oblong","diamond","oval"] }
      ];

      const BEARDS = [
        { id: "none", name: "Soqolsiz (Toza)" },
        { id: "stubble", name: "Yengil (3 kunlik)" },
        { id: "fade_beard", name: "Fade Soqol" },
        { id: "full_beard", name: "To'liq Qalin Soqol" },
        { id: "goatee", name: "Goatee (Espanyolka)" }
      ];

      const COLOR_PALETTES = {
        natural_black: { base: "#121318", mid: "#22252e", hi: "#3b404f", skinShadow: "rgba(18,19,24,0.28)" },
        dark_brown:    { base: "#271810", mid: "#3d261a", hi: "#5c3b28", skinShadow: "rgba(39,24,16,0.26)" },
        warm_chestnut: { base: "#472916", mid: "#693e23", hi: "#8c5735", skinShadow: "rgba(71,41,22,0.25)" },
        ash_graphite:  { base: "#3e434c", mid: "#636b78", hi: "#949eab", skinShadow: "rgba(62,67,76,0.24)" }
      };

      const state = {
        hasPhoto: false,
        sourceCanvas: document.createElement("canvas"),
        faceBox: { cx: 360, cy: 430, rx: 165, ry: 215 },
        offsetX: 0,
        offsetY: 0,
        scaleAdjust: 1.0,
        faceShape: "oval",
        styleId: "low_fade_crop",
        beardId: "fade_beard",
        hairColor: "natural_black",
        showOriginal: false,
        stream: null
      };
      state.sourceCanvas.width = 720;
      state.sourceCanvas.height = 888;

      const videoEl = document.getElementById("cameraVideo");
      const mainCanvas = document.getElementById("mainCanvas");
      const ctx = mainCanvas.getContext("2d");
      const emptyState = document.getElementById("emptyState");
      const faceGuideOverlay = document.getElementById("faceGuideOverlay");
      const cameraControls = document.getElementById("cameraControls");
      const adjustBar = document.getElementById("adjustBar");
      const canvasBadges = document.getElementById("canvasBadges");
      const compareBtn = document.getElementById("compareBtn");
      const variantsSection = document.getElementById("variantsSection");
      const variantsGrid = document.getElementById("variantsGrid");
      const aiAdviceBox = document.getElementById("aiAdviceBox");
      const faceShapeBadge = document.getElementById("faceShapeBadge");
      const matchBadge = document.getElementById("matchBadge");

      // Render Beard & Hairstyle selectors
      function renderSelectors() {
        const beardWrap = document.getElementById("beardChips");
        beardWrap.innerHTML = "";
        BEARDS.forEach(b => {
          const btn = document.createElement("button");
          btn.type = "button";
          btn.className = "chip" + (b.id === state.beardId ? " active" : "");
          btn.textContent = b.name;
          btn.onclick = () => {
            state.beardId = b.id;
            renderSelectors();
            updateAllPreviews();
            requestAiAdvice();
          };
          beardWrap.appendChild(btn);
        });

        const stylesWrap = document.getElementById("stylesGrid");
        stylesWrap.innerHTML = "";
        HAIRSTYLES.forEach(s => {
          const card = document.createElement("div");
          card.className = "style-card" + (s.id === state.styleId ? " active" : "");
          const isRec = s.shapes.includes(state.faceShape);
          card.innerHTML = `
            <div>
              <span class="style-badge">${isRec ? "✅ Yuzga mos • " : ""}${s.badge}</span>
              <div class="style-name">${s.name}</div>
              <div class="style-desc">${s.desc}</div>
            </div>
          `;
          card.onclick = () => {
            state.styleId = s.id;
            renderSelectors();
            updateAllPreviews();
            requestAiAdvice();
          };
          stylesWrap.appendChild(card);
        });
      }

      // Intelligent skin-tone face detector on sourceCanvas
      function analyzeFaceFromCanvas(srcCanvas) {
        const w = srcCanvas.width;
        const h = srcCanvas.height;
        const sctx = srcCanvas.getContext("2d");
        const imgData = sctx.getImageData(0, 0, w, h).data;

        let minX = w, maxX = 0, minY = h, maxY = 0, count = 0;
        let sumX = 0, sumY = 0;
        const startX = Math.floor(w * 0.16), endX = Math.floor(w * 0.84);
        const startY = Math.floor(h * 0.14), endY = Math.floor(h * 0.82);

        for (let y = startY; y < endY; y += 4) {
          for (let x = startX; x < endX; x += 4) {
            const idx = (y * w + x) * 4;
            const r = imgData[idx], g = imgData[idx + 1], b = imgData[idx + 2];
            // RGB + YCbCr skin detection heuristic
            const maxC = Math.max(r, g, b), minC = Math.min(r, g, b);
            const cb = 128 - 0.168736 * r - 0.331264 * g + 0.5 * b;
            const cr = 128 + 0.5 * r - 0.418688 * g - 0.081312 * b;
            if (r > 75 && g > 40 && b > 20 && r > g && r > b && (maxC - minC) > 15 && cr >= 133 && cr <= 178 && cb >= 77 && cb <= 132) {
              sumX += x;
              sumY += y;
              if (x < minX) minX = x;
              if (x > maxX) maxX = x;
              if (y < minY) minY = y;
              if (y > maxY) maxY = y;
              count++;
            }
          }
        }

        if (count > 220) {
          const cx = Math.max(w * 0.35, Math.min(w * 0.65, sumX / count));
          const cy = Math.max(h * 0.36, Math.min(h * 0.56, sumY / count));
          const spanX = Math.max(w * 0.34, Math.min(w * 0.58, (maxX - minX) * 0.92));
          const spanY = Math.max(h * 0.38, Math.min(h * 0.62, (maxY - minY) * 0.94));
          const ratio = spanY / Math.max(1, spanX);

          let detectedShape = "oval";
          if (ratio > 1.34) detectedShape = "oblong";
          else if (ratio < 1.12) detectedShape = "round";
          else if (Math.abs((cx - minX) - (maxX - cx)) < 14) detectedShape = "square";
          else detectedShape = "oval";

          state.faceBox = {
            cx: cx,
            cy: cy,
            rx: spanX * 0.50,
            ry: spanY * 0.52
          };
          setFaceShape(detectedShape, false);
        } else {
          state.faceBox = { cx: w * 0.5, cy: h * 0.47, rx: w * 0.235, ry: h * 0.245 };
        }
      }

      function setFaceShape(shape, triggerUpdate = true) {
        state.faceShape = shape;
        document.querySelectorAll("#faceShapeChips .chip").forEach(btn => {
          btn.classList.toggle("active", btn.dataset.shape === shape);
        });
        const names = { oval: "Oval", square: "Kvadrat", round: "Dumaloq", diamond: "Olmos", oblong: "Uzunchoq" };
        faceShapeBadge.textContent = "🧠 Yuz: " + (names[shape] || "Oval");
        renderSelectors();
        if (triggerUpdate) {
          updateAllPreviews();
          requestAiAdvice();
        }
      }

      // Procedural high-detail hair strand & beard renderer
      function renderHairAndBeardOnCanvas(targetCanvas, styleId, beardId, colorKey, showOrig) {
        const w = targetCanvas.width;
        const h = targetCanvas.height;
        const tctx = targetCanvas.getContext("2d");
        tctx.clearRect(0, 0, w, h);
        tctx.drawImage(state.sourceCanvas, 0, 0, w, h);

        if (showOrig) return;

        const scaleX = w / 720;
        const scaleY = h / 888;
        const adjS = state.scaleAdjust;
        const cx = (state.faceBox.cx + state.offsetX) * scaleX;
        const cy = (state.faceBox.cy + state.offsetY) * scaleY;
        const rx = state.faceBox.rx * scaleX * adjS;
        const ry = state.faceBox.ry * scaleY * adjS;

        const pal = COLOR_PALETTES[colorKey] || COLOR_PALETTES.natural_black;

        tctx.save();

        // 1. Subtle temple & forehead barbershop fade shadow
        const fadeGradL = tctx.createRadialGradient(cx - rx * 0.92, cy - ry * 0.25, rx * 0.05, cx - rx * 0.85, cy - ry * 0.25, rx * 0.52);
        fadeGradL.addColorStop(0, pal.skinShadow);
        fadeGradL.addColorStop(1, "rgba(0,0,0,0)");
        tctx.fillStyle = fadeGradL;
        tctx.beginPath();
        tctx.ellipse(cx - rx * 0.88, cy - ry * 0.22, rx * 0.32, ry * 0.52, -0.12, 0, Math.PI * 2);
        tctx.fill();

        const fadeGradR = tctx.createRadialGradient(cx + rx * 0.92, cy - ry * 0.25, rx * 0.05, cx + rx * 0.85, cy - ry * 0.25, rx * 0.52);
        fadeGradR.addColorStop(0, pal.skinShadow);
        fadeGradR.addColorStop(1, "rgba(0,0,0,0)");
        tctx.fillStyle = fadeGradR;
        tctx.beginPath();
        tctx.ellipse(cx + rx * 0.88, cy - ry * 0.22, rx * 0.32, ry * 0.52, 0.12, 0, Math.PI * 2);
        tctx.fill();

        // 2. Main Hair Silhouette + Volumetric Gradient + Realistic Hair Strands
        drawHairstyleLayer(tctx, cx, cy, rx, ry, styleId, pal);

        // 3. Beard Layer if selected
        if (beardId && beardId !== "none") {
          drawBeardLayer(tctx, cx, cy, rx, ry, beardId, pal);
        }

        tctx.restore();
      }

      function drawHairstyleLayer(g, cx, cy, rx, ry, styleId, pal) {
        const topY = cy - ry * 0.96;
        const crownY = cy - ry * 1.34;

        // Base gradient for realistic hair depth
        const hairGrad = g.createLinearGradient(cx, crownY - ry * 0.25, cx, cy - ry * 0.2);
        hairGrad.addColorStop(0, pal.hi);
        hairGrad.addColorStop(0.45, pal.mid);
        hairGrad.addColorStop(1, pal.base);

        g.save();
        g.shadowColor = "rgba(0,0,0,0.42)";
        g.shadowBlur = rx * 0.09;
        g.shadowOffsetY = ry * 0.03;

        // Back mullet extension if modern_mullet
        if (styleId === "modern_mullet") {
          g.fillStyle = pal.base;
          g.beginPath();
          g.ellipse(cx - rx * 0.96, cy + ry * 0.28, rx * 0.22, ry * 0.42, 0.2, 0, Math.PI * 2);
          g.ellipse(cx + rx * 0.96, cy + ry * 0.28, rx * 0.22, ry * 0.42, -0.2, 0, Math.PI * 2);
          g.fill();
        }

        g.fillStyle = hairGrad;
        g.beginPath();

        if (styleId === "buzz_cut_fade") {
          // Tight military buzz dome with sharp line-up forehead
          g.moveTo(cx - rx * 0.92, cy - ry * 0.42);
          g.quadraticCurveTo(cx - rx * 0.96, cy - ry * 1.15, cx, cy - ry * 1.20);
          g.quadraticCurveTo(cx + rx * 0.96, cy - ry * 1.15, cx + rx * 0.92, cy - ry * 0.42);
          g.lineTo(cx + rx * 0.80, cy - ry * 0.68);
          g.quadraticCurveTo(cx, cy - ry * 0.74, cx - rx * 0.80, cy - ry * 0.68);
          g.closePath();
          g.globalAlpha = 0.86;
          g.fill();
          g.globalAlpha = 1;
        } else if (styleId === "high_skin_fade_quiff" || styleId === "modern_pompadour") {
          const lift = styleId === "modern_pompadour" ? 1.52 : 1.44;
          g.moveTo(cx - rx * 0.86, cy - ry * 0.56);
          g.bezierCurveTo(cx - rx * 0.94, cy - ry * 1.25, cx - rx * 0.45, cy - ry * lift, cx + rx * 0.08, cy - ry * (lift + 0.04));
          g.bezierCurveTo(cx + rx * 0.65, cy - ry * lift, cx + rx * 0.92, cy - ry * 1.12, cx + rx * 0.86, cy - ry * 0.56);
          g.quadraticCurveTo(cx + rx * 0.72, cy - ry * 0.76, cx, cy - ry * 0.78);
          g.quadraticCurveTo(cx - rx * 0.72, cy - ry * 0.76, cx - rx * 0.86, cy - ry * 0.56);
          g.closePath();
          g.fill();
        } else if (styleId === "classic_side_part") {
          g.moveTo(cx - rx * 0.98, cy - ry * 0.34);
          g.bezierCurveTo(cx - rx * 1.04, cy - ry * 1.18, cx - rx * 0.55, cy - ry * 1.38, cx, cy - ry * 1.36);
          g.bezierCurveTo(cx + rx * 0.68, cy - ry * 1.38, cx + rx * 1.04, cy - ry * 1.12, cx + rx * 0.98, cy - ry * 0.34);
          g.lineTo(cx + rx * 0.84, cy - ry * 0.62);
          g.bezierCurveTo(cx + rx * 0.45, cy - ry * 0.82, cx - rx * 0.35, cy - ry * 0.68, cx - rx * 0.56, cy - ry * 0.82);
          g.lineTo(cx - rx * 0.84, cy - ry * 0.60);
          g.closePath();
          g.fill();
          // Hard razor side part line
          g.strokeStyle = "rgba(245,230,179,0.45)";
          g.lineWidth = Math.max(1.5, rx * 0.018);
          g.beginPath();
          g.moveTo(cx - rx * 0.54, cy - ry * 0.80);
          g.lineTo(cx - rx * 0.68, cy - ry * 1.16);
          g.stroke();
        } else if (styleId === "french_crop" || styleId === "low_fade_crop") {
          const fringeY = styleId === "french_crop" ? 0.58 : 0.65;
          g.moveTo(cx - rx * 0.95, cy - ry * 0.44);
          g.bezierCurveTo(cx - rx * 1.02, cy - ry * 1.18, cx - rx * 0.55, cy - ry * 1.34, cx, cy - ry * 1.34);
          g.bezierCurveTo(cx + rx * 0.55, cy - ry * 1.34, cx + rx * 1.02, cy - ry * 1.18, cx + rx * 0.95, cy - ry * 0.44);
          g.lineTo(cx + rx * 0.82, cy - ry * fringeY);
          g.quadraticCurveTo(cx, cy - ry * (fringeY - 0.05), cx - rx * 0.82, cy - ry * fringeY);
          g.closePath();
          g.fill();
        } else if (styleId === "textured_fringe") {
          g.moveTo(cx - rx * 0.96, cy - ry * 0.40);
          g.bezierCurveTo(cx - rx * 1.05, cy - ry * 1.22, cx - rx * 0.52, cy - ry * 1.38, cx, cy - ry * 1.38);
          g.bezierCurveTo(cx + rx * 0.52, cy - ry * 1.38, cx + rx * 1.05, cy - ry * 1.22, cx + rx * 0.96, cy - ry * 0.40);
          // Zig-zag messy fringe over forehead
          const steps = 9;
          for (let i = steps; i >= 0; i--) {
            const t = i / steps;
            const px = (cx - rx * 0.82) + t * (rx * 1.64);
            const py = cy - ry * (i % 2 === 0 ? 0.50 : 0.63);
            g.lineTo(px, py);
          }
          g.closePath();
          g.fill();
        } else if (styleId === "curly_taper") {
          g.moveTo(cx - rx * 0.94, cy - ry * 0.48);
          g.bezierCurveTo(cx - rx * 1.08, cy - ry * 1.25, cx - rx * 0.55, cy - ry * 1.44, cx, cy - ry * 1.44);
          g.bezierCurveTo(cx + rx * 0.55, cy - ry * 1.44, cx + rx * 1.08, cy - ry * 1.25, cx + rx * 0.94, cy - ry * 0.48);
          g.quadraticCurveTo(cx, cy - ry * 0.58, cx - rx * 0.94, cy - ry * 0.48);
          g.closePath();
          g.fill();
          // Curly puffs
          for (let i = 0; i < 26; i++) {
            const ang = Math.PI + (i / 25) * Math.PI;
            const radX = rx * (0.76 + (i % 3) * 0.08);
            const radY = ry * (0.88 + (i % 2) * 0.12);
            const px = cx + Math.cos(ang) * radX;
            const py = (cy - ry * 0.45) + Math.sin(ang) * radY * 0.95;
            g.fillStyle = i % 2 === 0 ? pal.mid : pal.base;
            g.beginPath();
            g.arc(px, py, rx * (0.14 + (i % 3) * 0.03), 0, Math.PI * 2);
            g.fill();
          }
        } else {
          // undercut_slick & modern_mullet top
          g.moveTo(cx - rx * 0.88, cy - ry * 0.52);
          g.bezierCurveTo(cx - rx * 0.96, cy - ry * 1.24, cx - rx * 0.50, cy - ry * 1.42, cx, cy - ry * 1.42);
          g.bezierCurveTo(cx + rx * 0.50, cy - ry * 1.42, cx + rx * 0.96, cy - ry * 1.24, cx + rx * 0.88, cy - ry * 0.52);
          g.quadraticCurveTo(cx, cy - ry * 0.72, cx - rx * 0.88, cy - ry * 0.52);
          g.closePath();
          g.fill();
        }

        // 3. Fine Hair Strand Highlights for Photorealistic Texture
        g.shadowBlur = 0;
        g.strokeStyle = pal.hi;
        g.lineWidth = Math.max(1.1, rx * 0.012);
        g.globalAlpha = 0.42;
        const strandCount = styleId === "buzz_cut_fade" ? 18 : 42;
        for (let i = 0; i < strandCount; i++) {
          const t = (i / (strandCount - 1)) * 2 - 1; // -1 to 1
          const sx = cx + t * rx * 0.78;
          const sy = cy - ry * 0.68;
          const ex = sx + (styleId === "classic_side_part" ? rx * 0.22 : t * rx * 0.12);
          const ey = cy - ry * (styleId === "buzz_cut_fade" ? 1.05 : 1.28);
          g.beginPath();
          g.moveTo(sx, sy);
          g.quadraticCurveTo((sx + ex) * 0.5, sy - ry * 0.35, ex, ey);
          g.stroke();
        }
        g.restore();
      }

      function drawBeardLayer(g, cx, cy, rx, ry, beardId, pal) {
        g.save();
        const jawY = cy + ry * 0.22;
        const chinY = cy + ry * 1.04;
        const mouthY = cy + ry * 0.42;

        if (beardId === "goatee") {
          g.fillStyle = pal.base;
          g.globalAlpha = 0.82;
          // Mustache
          g.beginPath();
          g.moveTo(cx - rx * 0.36, mouthY);
          g.quadraticCurveTo(cx, mouthY - ry * 0.12, cx + rx * 0.36, mouthY);
          g.quadraticCurveTo(cx, mouthY - ry * 0.02, cx - rx * 0.36, mouthY);
          g.fill();
          // Chin goatee
          g.beginPath();
          g.ellipse(cx, cy + ry * 0.85, rx * 0.34, ry * 0.20, 0, 0, Math.PI * 2);
          g.fill();
          g.restore();
          return;
        }

        const alpha = beardId === "stubble" ? 0.36 : (beardId === "fade_beard" ? 0.76 : 0.90);
        const chinDrop = beardId === "full_beard" ? 1.15 : 1.04;

        const beardGrad = g.createLinearGradient(cx, jawY, cx, cy + ry * chinDrop);
        beardGrad.addColorStop(0, beardId === "fade_beard" ? "rgba(18,19,24,0.12)" : pal.mid);
        beardGrad.addColorStop(0.35, pal.base);
        beardGrad.addColorStop(1, pal.base);

        g.fillStyle = beardGrad;
        g.globalAlpha = alpha;

        // Outer jawline path + inner mouth cutout
        g.beginPath();
        g.moveTo(cx - rx * 0.95, cy - ry * 0.04);
        g.quadraticCurveTo(cx - rx * 0.96, cy + ry * 0.75, cx, cy + ry * chinDrop);
        g.quadraticCurveTo(cx + rx * 0.96, cy + ry * 0.75, cx + rx * 0.95, cy - ry * 0.04);
        g.lineTo(cx + rx * 0.82, cy - ry * 0.04);
        g.quadraticCurveTo(cx + rx * 0.68, cy + ry * 0.38, cx + rx * 0.38, mouthY);
        g.quadraticCurveTo(cx, mouthY - ry * 0.10, cx - rx * 0.38, mouthY);
        g.quadraticCurveTo(cx - rx * 0.68, cy + ry * 0.38, cx - rx * 0.82, cy - ry * 0.04);
        g.closePath();
        g.fill();

        // Mouth opening cutout blend
        g.globalCompositeOperation = "source-atop";
        g.fillStyle = "rgba(220, 165, 145, 0.22)";
        g.beginPath();
        g.ellipse(cx, mouthY + ry * 0.12, rx * 0.26, ry * 0.09, 0, 0, Math.PI * 2);
        g.fill();

        g.restore();
      }

      // Draw a synthetic studio portrait for Demo Mode
      function generateDemoPortrait() {
        const sc = state.sourceCanvas;
        const g = sc.getContext("2d");
        const w = sc.width, h = sc.height;

        const bg = g.createRadialGradient(w * 0.5, h * 0.4, 40, w * 0.5, h * 0.5, w * 0.8);
        bg.addColorStop(0, "#1e2638");
        bg.addColorStop(1, "#0b0e16");
        g.fillStyle = bg;
        g.fillRect(0, 0, w, h);

        const cx = 360, cy = 440, rx = 162, ry = 212;
        state.faceBox = { cx, cy, rx, ry };

        // Shoulders & Suit
        g.fillStyle = "#141824";
        g.beginPath();
        g.ellipse(cx, h * 0.96, rx * 2.1, ry * 0.95, 0, Math.PI, Math.PI * 2);
        g.fill();

        // Neck
        g.fillStyle = "#c99778";
        g.fillRect(cx - rx * 0.45, cy + ry * 0.65, rx * 0.9, ry * 0.75);

        // Ears
        g.fillStyle = "#d4a281";
        g.beginPath();
        g.ellipse(cx - rx * 0.98, cy, rx * 0.14, ry * 0.24, -0.1, 0, Math.PI * 2);
        g.ellipse(cx + rx * 0.98, cy, rx * 0.14, ry * 0.24, 0.1, 0, Math.PI * 2);
        g.fill();

        // Face oval with realistic skin shading
        const skin = g.createRadialGradient(cx - 20, cy - 30, 30, cx, cy, ry * 1.05);
        skin.addColorStop(0, "#ecc1a1");
        skin.addColorStop(0.7, "#dca986");
        skin.addColorStop(1, "#be8967");
        g.fillStyle = skin;
        g.beginPath();
        g.ellipse(cx, cy, rx, ry, 0, 0, Math.PI * 2);
        g.fill();

        // Eyebrows
        g.strokeStyle = "#2b1d14";
        g.lineWidth = 8;
        g.lineCap = "round";
        g.beginPath();
        g.moveTo(cx - rx * 0.58, cy - ry * 0.22);
        g.quadraticCurveTo(cx - rx * 0.36, cy - ry * 0.30, cx - rx * 0.16, cy - ry * 0.22);
        g.moveTo(cx + rx * 0.16, cy - ry * 0.22);
        g.quadraticCurveTo(cx + rx * 0.36, cy - ry * 0.30, cx + rx * 0.58, cy - ry * 0.22);
        g.stroke();

        // Eyes
        [-0.36, 0.36].forEach(dir => {
          const ex = cx + dir * rx;
          const ey = cy - ry * 0.10;
          g.fillStyle = "#ffffff";
          g.beginPath();
          g.ellipse(ex, ey, rx * 0.16, ry * 0.065, 0, 0, Math.PI * 2);
          g.fill();
          g.fillStyle = "#3b281c";
          g.beginPath();
          g.arc(ex, ey, rx * 0.065, 0, Math.PI * 2);
          g.fill();
          g.fillStyle = "#090b10";
          g.beginPath();
          g.arc(ex, ey, rx * 0.03, 0, Math.PI * 2);
          g.fill();
        });

        // Nose
        g.strokeStyle = "rgba(140, 92, 65, 0.55)";
        g.lineWidth = 4;
        g.beginPath();
        g.moveTo(cx, cy - ry * 0.10);
        g.lineTo(cx - 8, cy + ry * 0.22);
        g.quadraticCurveTo(cx, cy + ry * 0.27, cx + 14, cy + ry * 0.22);
        g.stroke();

        // Lips
        g.fillStyle = "#b56e5b";
        g.beginPath();
        g.ellipse(cx, cy + ry * 0.48, rx * 0.25, ry * 0.06, 0, 0, Math.PI * 2);
        g.fill();

        onPhotoReady();
      }

      function onPhotoReady() {
        state.hasPhoto = true;
        state.offsetX = 0;
        state.offsetY = 0;
        state.scaleAdjust = 1.0;

        emptyState.style.display = "none";
        videoEl.style.display = "none";
        faceGuideOverlay.style.display = "none";
        cameraControls.style.display = "none";
        mainCanvas.style.display = "block";
        canvasBadges.style.display = "flex";
        compareBtn.style.display = "block";
        adjustBar.style.display = "flex";
        variantsSection.style.display = "block";

        updateAllPreviews();
        requestAiAdvice();
      }

      function updateAllPreviews() {
        if (!state.hasPhoto) return;
        renderHairAndBeardOnCanvas(mainCanvas, state.styleId, state.beardId, state.hairColor, state.showOriginal);

        // Render 4 recommended variant thumbnails
        const recommended = HAIRSTYLES.filter(s => s.shapes.includes(state.faceShape)).slice(0, 4);
        if (!recommended.some(s => s.id === state.styleId)) {
          const cur = HAIRSTYLES.find(s => s.id === state.styleId);
          if (cur) recommended[3] = cur;
        }

        variantsGrid.innerHTML = "";
        recommended.forEach(s => {
          const item = document.createElement("div");
          item.className = "variant-item" + (s.id === state.styleId ? " active" : "");
          const vc = document.createElement("canvas");
          vc.width = 200;
          vc.height = 240;
          renderHairAndBeardOnCanvas(vc, s.id, state.beardId, state.hairColor, false);

          const lbl = document.createElement("div");
          lbl.className = "variant-label";
          lbl.textContent = s.name;

          item.appendChild(vc);
          item.appendChild(lbl);
          item.onclick = () => {
            state.styleId = s.id;
            renderSelectors();
            updateAllPreviews();
            requestAiAdvice();
          };
          variantsGrid.appendChild(item);
        });
      }

      async function requestAiAdvice() {
        try {
          const resp = await fetch("/webapp/api/generate", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              style_id: state.styleId,
              beard_id: state.beardId,
              face_shape: state.faceShape,
              hair_color: state.hairColor
            })
          });
          const data = await resp.json();
          if (data && data.ok) {
            matchBadge.textContent = "🔥 " + data.match_score + "% Mos";
            aiAdviceBox.innerHTML = "🤖 <b>AI Stilist tahlili:</b> " + data.ai_advice;
          }
        } catch (err) {}
      }

      // Camera handling
      async function startCamera() {
        try {
          const stream = await navigator.mediaDevices.getUserMedia({
            video: { facingMode: "user", width: { ideal: 720 }, height: { ideal: 888 } },
            audio: false
          });
          state.stream = stream;
          videoEl.srcObject = stream;
          emptyState.style.display = "none";
          mainCanvas.style.display = "none";
          videoEl.style.display = "block";
          faceGuideOverlay.style.display = "flex";
          cameraControls.style.display = "flex";
          adjustBar.style.display = "none";
        } catch (err) {
          alert("Kameraga ruxsat berilmadi yoki qurilmada kamera topilmadi. «Rasm yuklash» tugmasidan foydalaning.");
        }
      }

      function stopCamera() {
        if (state.stream) {
          state.stream.getTracks().forEach(t => t.stop());
          state.stream = null;
        }
      }

      document.getElementById("startCameraBtn").onclick = startCamera;

      document.getElementById("cancelCameraBtn").onclick = () => {
        stopCamera();
        videoEl.style.display = "none";
        faceGuideOverlay.style.display = "none";
        cameraControls.style.display = "none";
        if (state.hasPhoto) {
          mainCanvas.style.display = "block";
          adjustBar.style.display = "flex";
        } else {
          emptyState.style.display = "block";
        }
      };

      document.getElementById("capturePhotoBtn").onclick = () => {
        const sc = state.sourceCanvas;
        const sctx = sc.getContext("2d");
        const vw = videoEl.videoWidth || 720;
        const vh = videoEl.videoHeight || 888;
        const targetRatio = sc.width / sc.height;
        const videoRatio = vw / vh;
        let sx = 0, sy = 0, sw = vw, sh = vh;
        if (videoRatio > targetRatio) {
          sw = vh * targetRatio;
          sx = (vw - sw) / 2;
        } else {
          sh = vw / targetRatio;
          sy = (vh - sh) / 2;
        }
        sctx.save();
        sctx.translate(sc.width, 0);
        sctx.scale(-1, 1);
        sctx.drawImage(videoEl, sx, sy, sw, sh, 0, 0, sc.width, sc.height);
        sctx.restore();
        stopCamera();
        analyzeFaceFromCanvas(sc);
        onPhotoReady();
      };

      // Gallery image upload
      document.getElementById("fileInput").onchange = (ev) => {
        const file = ev.target.files && ev.target.files[0];
        if (!file) return;
        const reader = new FileReader();
        reader.onload = (e) => {
          const img = new Image();
          img.onload = () => {
            const sc = state.sourceCanvas;
            const sctx = sc.getContext("2d");
            const targetRatio = sc.width / sc.height;
            const imgRatio = img.width / img.height;
            let sx = 0, sy = 0, sw = img.width, sh = img.height;
            if (imgRatio > targetRatio) {
              sw = img.height * targetRatio;
              sx = (img.width - sw) / 2;
            } else {
              sh = img.width / targetRatio;
              sy = (img.height - sh) / 2;
            }
            sctx.drawImage(img, sx, sy, sw, sh, 0, 0, sc.width, sc.height);
            analyzeFaceFromCanvas(sc);
            onPhotoReady();
          };
          img.src = e.target.result;
        };
        reader.readAsDataURL(file);
      };

      document.getElementById("demoFaceBtn").onclick = generateDemoPortrait;

      document.getElementById("retakeBtn").onclick = () => {
        state.hasPhoto = false;
        mainCanvas.style.display = "none";
        canvasBadges.style.display = "none";
        compareBtn.style.display = "none";
        adjustBar.style.display = "none";
        variantsSection.style.display = "none";
        emptyState.style.display = "block";
      };

      document.getElementById("downloadBtn").onclick = () => {
        if (!state.hasPhoto) return;
        const link = document.createElement("a");
        link.download = "jasur_barber_ai_" + state.styleId + ".png";
        link.href = mainCanvas.toDataURL("image/png");
        link.click();
      };

      // Before / After comparison button
      compareBtn.onmousedown = compareBtn.ontouchstart = (e) => {
        e.preventDefault();
        state.showOriginal = true;
        updateAllPreviews();
      };
      window.addEventListener("mouseup", () => {
        if (state.showOriginal) {
          state.showOriginal = false;
          updateAllPreviews();
        }
      });
      window.addEventListener("touchend", () => {
        if (state.showOriginal) {
          state.showOriginal = false;
          updateAllPreviews();
        }
      });

      // Fine adjustment controls
      document.querySelectorAll(".mini-ctrl").forEach(btn => {
        btn.onclick = () => {
          const act = btn.dataset.adj;
          if (act === "up") state.offsetY -= 8;
          if (act === "down") state.offsetY += 8;
          if (act === "smaller") state.scaleAdjust = Math.max(0.75, state.scaleAdjust - 0.04);
          if (act === "larger") state.scaleAdjust = Math.min(1.30, state.scaleAdjust + 0.04);
          updateAllPreviews();
        };
      });

      // Face shape chip clicks
      document.querySelectorAll("#faceShapeChips .chip").forEach(btn => {
        btn.onclick = () => setFaceShape(btn.dataset.shape, true);
      });

      // Hair color clicks
      document.querySelectorAll("#colorSwatches .color-swatch").forEach(sw => {
        sw.onclick = () => {
          state.hairColor = sw.dataset.color;
          document.querySelectorAll("#colorSwatches .color-swatch").forEach(el => {
            el.classList.toggle("active", el.dataset.color === state.hairColor);
          });
          updateAllPreviews();
          requestAiAdvice();
        };
      });

      // Book with selected style CTA
      document.getElementById("bookWithStyleBtn").onclick = () => {
        const stObj = HAIRSTYLES.find(s => s.id === state.styleId) || HAIRSTYLES[0];
        const bdObj = BEARDS.find(b => b.id === state.beardId) || BEARDS[0];
        const payload = JSON.stringify({
          action: "book_ai_style",
          style_id: stObj.id,
          style_name: stObj.name,
          beard_name: bdObj.name,
          face_shape: state.faceShape
        });

        if (tg && tg.sendData) {
          try {
            tg.sendData(payload);
          } catch (e) {}
        }
        if (tg && tg.close) {
          setTimeout(() => { try { tg.close(); } catch (e) {} }, 180);
        } else {
          alert("Tanlangan uslub: " + stObj.name + " (" + bdObj.name + "). Botga qaytib «💈 Navbatga yozilish» tugmasini bosing!");
        }
      };

      renderSelectors();
    })();
  </script>
</body>
</html>
"""


async def handle_webapp_page(request: web.Request) -> web.Response:
    return web.Response(
        text=_WEBAPP_HTML,
        status=200,
        content_type="text/html",
        charset="utf-8",
        headers=WEBAPP_SECURITY_HEADERS,
    )
