from __future__ import annotations

import logging
import os
from typing import Any

import aiohttp
from aiohttp import web

from app.config import settings

logger = logging.getLogger("barbershop_bot.webapp")

WEBAPP_SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(self), microphone=()",
    "Content-Security-Policy": (
        "default-src 'self' https: data: blob:; "
        "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://telegram.org https://cdn.jsdelivr.net https://storage.googleapis.com; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com data:; "
        "img-src 'self' data: blob: https:; "
        "media-src 'self' data: blob: mediastream:; "
        "connect-src 'self' https: data: blob:; "
        "worker-src 'self' blob: https:; "
        "frame-ancestors *"
    ),
}

# Detailed catalog of men's hairstyles with real HD studio reference portraits and Nano Banana prompts
HAIRSTYLES_CATALOG: list[dict[str, Any]] = [
    {
        "id": "low_fade_crop",
        "name_uz": "Low Fade + Textured Crop",
        "name_ru": "Low Fade + Текстурный Кроп",
        "badge_uz": "🔥 Eng mashhur",
        "desc_uz": "Yon tomonlari pastdan silliq o'tish (Low Fade) va tepasi teksturali zamonaviy turmak.",
        "best_shapes": ["oval", "square", "diamond", "round"],
        "photo_url": "https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?w=720&auto=format&fit=crop&q=85",
        "prompt": "modern men's low skin fade with a textured French crop top and sharp natural hairline",
    },
    {
        "id": "high_skin_fade_quiff",
        "name_uz": "High Skin Fade + Quiff",
        "name_ru": "High Skin Fade + Квифф",
        "badge_uz": "⚡ Hajmli & Kuchli",
        "desc_uz": "Yonlari nolga yaqin baland fade, old qismi ko'tarilgan hajmli Quiff uslubi.",
        "best_shapes": ["round", "oval", "square"],
        "photo_url": "https://images.unsplash.com/photo-1500648767791-00dcc994a43e?w=720&auto=format&fit=crop&q=85",
        "prompt": "men's high skin fade with a volumetric textured quiff on top, clean barbershop fade",
    },
    {
        "id": "classic_side_part",
        "name_uz": "Classic Side Part (Klassika)",
        "name_ru": "Классический Боковой Пробор",
        "badge_uz": "👔 Biznes & Rasmiy",
        "desc_uz": "Yonga taralgan an'anaviy, tartibli va har qanday kiyimga mos tushuvchi klassik stil.",
        "best_shapes": ["oval", "square", "oblong", "diamond"],
        "photo_url": "https://images.unsplash.com/photo-1519085360753-af0119f7cbe7?w=720&auto=format&fit=crop&q=85",
        "prompt": "classic gentleman side part haircut with neat combed hair and clean taper fade sides",
    },
    {
        "id": "modern_pompadour",
        "name_uz": "Modern Pompadour",
        "name_ru": "Современный Помпадур",
        "badge_uz": "👑 Premium",
        "desc_uz": "Tepa qismi orqaga va yuqoriga silliq taralgan, yuzni uzunroq va chiroyli ko'rsatuvchi turmak.",
        "best_shapes": ["round", "oval", "square"],
        "photo_url": "https://images.unsplash.com/photo-1506794778202-cad84cf45f1d?w=720&auto=format&fit=crop&q=85",
        "prompt": "modern men's pompadour haircut with slick brushed-back volumetric top and mid fade",
    },
    {
        "id": "buzz_cut_fade",
        "name_uz": "Buzz Cut + Mid Drop Fade",
        "name_ru": "Бокс / Buzz Cut + Фейд",
        "badge_uz": "💪 Sport & Minimal",
        "desc_uz": "Kalta, parvarishi oson, jag' chiziqlarini keskin va erkakcha ko'rsatuvchi harbiy-sport uslubi.",
        "best_shapes": ["square", "oval", "diamond"],
        "photo_url": "https://images.unsplash.com/photo-1463453091185-61582044d556?w=720&auto=format&fit=crop&q=85",
        "prompt": "ultra-clean men's buzz cut with a mid drop skin fade and sharp forehead line-up",
    },
    {
        "id": "undercut_slick",
        "name_uz": "Disconnected Undercut",
        "name_ru": "Андеркат (Undercut)",
        "badge_uz": "✨ Kontrast",
        "desc_uz": "Yonlari kalta va tepasi uzun kontrastli zamonaviy yoshlar uslubi.",
        "best_shapes": ["oval", "round", "diamond"],
        "photo_url": "https://images.unsplash.com/photo-1492562080023-ab3db95bfbce?w=720&auto=format&fit=crop&q=85",
        "prompt": "men's disconnected undercut with short faded sides and slick textured longer top",
    },
    {
        "id": "french_crop",
        "name_uz": "French Crop (Fransuzcha)",
        "name_ru": "Френч Кроп (French Crop)",
        "badge_uz": "🎯 Trend 2026",
        "desc_uz": "Peshona qismi tekis chiziqli va tepasi qalin teksturali zamonaviy Yevropa uslubi.",
        "best_shapes": ["oblong", "oval", "diamond", "square"],
        "photo_url": "https://images.unsplash.com/photo-1539571696357-5a69c17a67c6?w=720&auto=format&fit=crop&q=85",
        "prompt": "men's sharp French crop haircut with forward textured fringe and mid taper fade",
    },
    {
        "id": "curly_taper",
        "name_uz": "Curly / Wavy Drop Fade",
        "name_ru": "Кудрявый / Волнистый Фейд",
        "badge_uz": "🌊 To'lqinli soch",
        "desc_uz": "Jingalak yoki to'lqinli sochlar uchun tabiiy hajm va toza yon fade uyg'unligi.",
        "best_shapes": ["oval", "oblong", "diamond", "round"],
        "photo_url": "https://images.unsplash.com/photo-1522075469751-3a6694fb2f61?w=720&auto=format&fit=crop&q=85",
        "prompt": "men's natural curly wavy top haircut with a clean barbershop drop fade on the sides",
    },
    {
        "id": "modern_mullet",
        "name_uz": "Modern Burst Fade Mullet",
        "name_ru": "Современный Маллет (Burst Fade)",
        "badge_uz": "🔥 Yoshlarbop",
        "desc_uz": "Quloq atrofi yarim oy (Burst fade) va orqa qismi teksturali zamonaviy trend.",
        "best_shapes": ["oval", "diamond", "square"],
        "photo_url": "https://images.unsplash.com/photo-1501196354995-cbb51c65aaea?w=720&auto=format&fit=crop&q=85",
        "prompt": "modern men's burst fade mullet haircut with textured top and clean faded temples",
    },
    {
        "id": "textured_fringe",
        "name_uz": "Textured Messy Fringe",
        "name_ru": "Текстурная Чёлка (Fringe)",
        "badge_uz": "🌟 Tabiiy ko'rinish",
        "desc_uz": "Oldinga tushib turuvchi erkin, yengil va peshonani yopuvchi teksturali uslub.",
        "best_shapes": ["oblong", "diamond", "oval"],
        "photo_url": "https://images.unsplash.com/photo-1472099645785-5658abf4ff4e?w=720&auto=format&fit=crop&q=85",
        "prompt": "men's messy textured fringe haircut with low taper fade",
    },
]

BEARD_CATALOG: list[dict[str, Any]] = [
    {"id": "fade_beard", "name_uz": "Fade Soqol (Konturli)", "name_ru": "Фейд борода с контуром", "prompt": "neatly lined-up faded beard"},
    {"id": "stubble", "name_uz": "Yengil soqol (Stubble)", "name_ru": "Лёгкая щетина", "prompt": "light 3-day designer stubble beard"},
    {"id": "full_beard", "name_uz": "Qalin To'liq Soqol", "name_ru": "Полная густая борода", "prompt": "well-groomed full thick masculine beard"},
    {"id": "goatee", "name_uz": "Goatee (Espanyolka)", "name_ru": "Эспаньолка (Goatee)", "prompt": "stylish goatee and mustache"},
    {"id": "none", "name_uz": "Soqolsiz (Toza)", "name_ru": "Без бороды", "prompt": "clean-shaven face"},
]

COLOR_PROMPTS: dict[str, str] = {
    "natural_black": "natural jet black hair color",
    "dark_brown": "rich dark espresso brown hair color",
    "warm_chestnut": "warm chestnut medium brown hair color",
    "ash_graphite": "modern silver ash grey platinum hair color",
}


async def _call_nano_banana_image_edit(
    image_b64: str,
    style_obj: dict[str, Any],
    beard_obj: dict[str, Any],
    hair_color: str,
    face_shape: str,
) -> dict[str, Any] | None:
    """
    Calls Google Gemini 'Nano Banana' (gemini-2.5-flash-image / gemini-2.0-flash-exp-image-generation)
    to photorealistically edit ONLY the hairstyle and beard on the client's real face photo
    while keeping their exact facial identity, skin tone, eyes, and background 100% intact.
    """
    gemini_key = (settings.GEMINI_API_KEY or os.environ.get("GEMINI_API_KEY") or "").strip()
    if not gemini_key or not image_b64:
        return None

    mime_type = "image/jpeg"
    if image_b64.startswith("data:") and ";base64," in image_b64:
        header, raw_b64 = image_b64.split(";base64,", 1)
        mime_type = header.replace("data:", "").strip() or "image/jpeg"
    else:
        raw_b64 = image_b64

    color_desc = COLOR_PROMPTS.get(hair_color, "natural black hair color")
    beard_desc = beard_obj.get("prompt", "neatly trimmed beard")
    edit_instruction = (
        f"Edit this person's photo in photorealistic 8k barbershop quality: "
        f"Change ONLY their hairstyle to a {style_obj['prompt']} with {color_desc}, "
        f"and set facial hair to {beard_desc}. "
        f"CRITICAL: Preserve the exact same person's face, eyes, nose, skin tone, facial expression, "
        f"head angle, clothing, and background 100% unchanged. Make the new hair blend naturally into the scalp and temples."
    )

    # 1. Try Nano Banana image generation models in priority order (returns edited photo + advice)
    candidate_models = [
        settings.GEMINI_IMAGE_MODEL or "gemini-2.5-flash-image",
        "gemini-3.1-flash-image",
        "gemini-3-pro-image",
        "gemini-2.5-flash-image-preview",
    ]
    seen = set()
    models_to_try = [m for m in candidate_models if not (m in seen or seen.add(m))]

    timeout = aiohttp.ClientTimeout(total=35)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        for model_name in models_to_try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={gemini_key}"
            payload = {
                "contents": [
                    {
                        "parts": [
                            {"text": edit_instruction},
                            {
                                "inlineData": {
                                    "mimeType": mime_type,
                                    "data": raw_b64,
                                }
                            },
                        ]
                    }
                ],
                "generationConfig": {
                    "responseModalities": ["TEXT", "IMAGE"],
                },
            }
            try:
                async with session.post(url, json=payload) as resp:
                    if resp.status != 200:
                        continue
                    data = await resp.json()
                    candidates = data.get("candidates") or []
                    if not candidates:
                        continue
                    parts = candidates[0].get("content", {}).get("parts") or []
                    generated_img_b64 = None
                    generated_mime = "image/png"
                    ai_text = None
                    for p in parts:
                        inline = p.get("inlineData") or p.get("inline_data")
                        if inline and inline.get("data"):
                            generated_img_b64 = inline["data"]
                            generated_mime = inline.get("mimeType") or inline.get("mime_type") or "image/png"
                        elif p.get("text"):
                            ai_text = p["text"].strip()

                    if generated_img_b64:
                        res: dict[str, Any] = {
                            "generated_image": f"data:{generated_mime};base64,{generated_img_b64}",
                            "engine": f"nano_banana ({model_name})",
                        }
                        if ai_text:
                            res["ai_advice"] = ai_text
                        return res
            except Exception as exc:
                logger.debug("NanoBanana call skipped on %s: %s", model_name, exc)

        # 2. If Nano Banana image output hits Free-Tier limit, use Gemini 3.6 Flash / 2.5 Flash Vision on the real face photo
        vision_prompt = (
            f"Sen Jasur Barber salonining oliy toifali AI sartarosh-stilistisan. "
            f"Rasmdagi mijozning haqiqiy yuz tuzilishini (peshona kengligi, yanoq suyaklari, jag' chizig'i va yuz shaklini) ko'rib tahlil qil. "
            f"Mijoz tanlagan soch turmagi: «{style_obj['name_uz']}», soqol uslubi: «{beard_obj['name_uz']}». "
            f"Shu mijozning o'z yuziga qarab 2-3 jumlada samimiy, professional va aniq o'zbek tilida tavsiya ber "
            f"(bu turmak uning qaysi yuz qismini chiroyli ochib berishini ayt)."
        )
        for vision_model in ("gemini-3.6-flash", "gemini-2.5-flash"):
            v_url = f"https://generativelanguage.googleapis.com/v1beta/models/{vision_model}:generateContent?key={gemini_key}"
            v_payload = {
                "contents": [
                    {
                        "parts": [
                            {"text": vision_prompt},
                            {
                                "inlineData": {
                                    "mimeType": mime_type,
                                    "data": raw_b64,
                                }
                            },
                        ]
                    }
                ]
            }
            try:
                async with session.post(v_url, json=v_payload) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        candidates = data.get("candidates") or []
                        if candidates:
                            parts = candidates[0].get("content", {}).get("parts") or []
                            for p in parts:
                                if p.get("text"):
                                    return {
                                        "ai_advice": p["text"].strip(),
                                        "engine": f"gemini_vision ({vision_model})",
                                    }
            except Exception as exc:
                logger.debug("Gemini vision fallback skipped on %s: %s", vision_model, exc)

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

    has_key = bool((settings.GEMINI_API_KEY or os.environ.get("GEMINI_API_KEY") or "").strip())

    advice = (
        f"✨ Sizning yuz tuzilishingiz — {shape_title}. "
        f"«{style_obj['name_uz']}» turmagi va «{beard_obj['name_uz']}» uyg'unligi yuz proporsiyasini "
        f"{match_score}% aniqlikda ochib beradi. {style_obj['desc_uz']} "
        f"Tanlangan tus: {color_label}."
    )

    return {
        "ok": True,
        "nano_banana_ready": has_key,
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
        "engine": "nano_banana_ready" if has_key else "mediapipe_hd",
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
        nano_res = await _call_nano_banana_image_edit(image_b64, style_obj, beard_obj, hair_color, face_shape)
        if nano_res:
            result.update(nano_res)

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
      --card: rgba(18, 22, 32, 0.94);
      --card-2: rgba(25, 31, 45, 0.96);
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
      padding: 0 0 98px 0;
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
      padding: 12px 13px 28px;
    }
    .top-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 16px;
      padding: 11px 14px;
      margin-bottom: 12px;
      box-shadow: 0 10px 28px rgba(0,0,0,0.45);
    }
    .brand-left {
      display: flex;
      align-items: center;
      gap: 10px;
    }
    .logo-circle {
      width: 38px;
      height: 38px;
      border-radius: 11px;
      background: linear-gradient(135deg, rgba(212,175,55,0.28), rgba(212,175,55,0.06));
      border: 1px solid var(--gold);
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 19px;
    }
    .brand-title {
      font-weight: 800;
      font-size: 15.5px;
      color: var(--gold-light);
      letter-spacing: 0.3px;
    }
    .brand-sub {
      font-size: 11px;
      color: var(--muted);
    }
    .ai-badge {
      background: linear-gradient(135deg, #e5c158, #b5891c);
      color: #080a0f;
      font-weight: 800;
      font-size: 10.5px;
      padding: 5px 9px;
      border-radius: 999px;
      letter-spacing: 0.3px;
      box-shadow: 0 0 14px rgba(212,175,55,0.35);
    }

    /* Mode Switcher */
    .mode-tabs {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 6px;
      background: rgba(12, 15, 22, 0.9);
      padding: 5px;
      border-radius: 13px;
      border: 1px solid var(--border);
      margin-bottom: 11px;
    }
    .mode-tab {
      border: none;
      background: transparent;
      color: var(--muted);
      font-size: 11.5px;
      font-weight: 700;
      padding: 8px 6px;
      border-radius: 9px;
      cursor: pointer;
      transition: all 0.18s ease;
    }
    .mode-tab.active {
      background: linear-gradient(135deg, #e5c158, #c49b27);
      color: #090b10;
      box-shadow: 0 3px 10px rgba(212,175,55,0.28);
    }

    /* Stage / Preview Card */
    .stage-card {
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 18px;
      padding: 12px;
      margin-bottom: 13px;
      box-shadow: 0 14px 34px rgba(0,0,0,0.55);
      position: relative;
    }
    .viewport-box {
      position: relative;
      width: 100%;
      aspect-ratio: 4 / 4.8;
      max-height: 440px;
      background: #0d111a;
      border-radius: 14px;
      overflow: hidden;
      border: 1px solid rgba(255,255,255,0.12);
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
    .ai-loading-overlay {
      position: absolute;
      inset: 0;
      background: rgba(8, 10, 15, 0.82);
      backdrop-filter: blur(8px);
      display: none;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      z-index: 10;
      text-align: center;
      padding: 20px;
    }
    @keyframes spin {
      to { transform: rotate(360deg); }
    }
    .spinner {
      width: 46px;
      height: 46px;
      border: 3.5px solid rgba(212,175,55,0.25);
      border-top-color: var(--gold);
      border-radius: 50%;
      animation: spin 0.9s linear infinite;
      margin-bottom: 12px;
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
      border: 2px dashed rgba(212, 175, 55, 0.82);
      border-radius: 50% 50% 46% 46% / 44% 44% 56% 56%;
      box-shadow: 0 0 0 9999px rgba(6, 8, 14, 0.45), inset 0 0 24px rgba(212, 175, 55, 0.22);
    }
    .guide-hint {
      margin-top: 10px;
      background: rgba(8, 10, 15, 0.86);
      border: 1px solid var(--border);
      color: var(--gold-light);
      font-size: 12px;
      font-weight: 600;
      padding: 5px 12px;
      border-radius: 999px;
      z-index: 2;
    }

    .action-strip {
      display: flex;
      gap: 8px;
      margin-top: 10px;
      flex-wrap: wrap;
      justify-content: space-between;
      align-items: center;
    }
    .btn {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 6px;
      padding: 10px 14px;
      border-radius: 11px;
      font-weight: 700;
      font-size: 13px;
      border: none;
      cursor: pointer;
      transition: transform 0.15s ease;
      text-decoration: none;
    }
    .btn:active { transform: scale(0.97); }
    .btn-gold {
      background: linear-gradient(135deg, #edd071 0%, #d4af37 55%, #aa820a 100%);
      color: #090b10;
      box-shadow: 0 4px 15px rgba(212,175,55,0.3);
    }
    .btn-dark {
      background: rgba(255,255,255,0.08);
      color: var(--text);
      border: 1px solid rgba(255,255,255,0.16);
    }
    .btn-sm {
      padding: 7px 11px;
      font-size: 12px;
      border-radius: 9px;
    }

    /* Floating overlays on canvas */
    .canvas-top-badges {
      position: absolute;
      top: 10px;
      left: 10px;
      right: 10px;
      display: flex;
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
      background: rgba(22, 163, 74, 0.90);
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
      background: rgba(9, 11, 16, 0.88);
      border: 1px solid var(--gold);
      color: var(--gold-light);
      padding: 7px 12px;
      border-radius: 10px;
      font-size: 11.5px;
      font-weight: 700;
      cursor: pointer;
      user-select: none;
    }

    /* 4 Variants Real Photo Grid */
    .variants-section {
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 16px;
      padding: 12px;
      margin-bottom: 13px;
    }
    .sec-title {
      font-size: 13.5px;
      font-weight: 800;
      color: var(--gold-light);
      margin: 0 0 9px 0;
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
      position: relative;
    }
    .variant-item.active {
      border-color: var(--gold);
      box-shadow: 0 0 14px rgba(212,175,55,0.42);
      transform: translateY(-2px);
    }
    .variant-item img {
      width: 100%;
      aspect-ratio: 1 / 1.18;
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
      background: rgba(9, 11, 16, 0.92);
    }

    /* Controls Card */
    .panel-card {
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 16px;
      padding: 13px;
      margin-bottom: 13px;
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

    /* Real Photo Hairstyles Catalog Cards Grid */
    .styles-grid {
      display: grid;
      grid-template-columns: repeat(2, 1fr);
      gap: 10px;
      margin-top: 8px;
    }
    .style-card {
      background: var(--card-2);
      border: 1.5px solid rgba(255,255,255,0.09);
      border-radius: 14px;
      overflow: hidden;
      cursor: pointer;
      transition: all 0.18s ease;
      display: flex;
      flex-direction: column;
    }
    .style-card.active {
      border-color: var(--gold);
      box-shadow: 0 6px 20px rgba(212,175,55,0.32);
      transform: translateY(-2px);
    }
    .style-thumb-wrap {
      position: relative;
      width: 100%;
      aspect-ratio: 4 / 4.2;
      overflow: hidden;
      background: #111520;
    }
    .style-thumb-wrap img {
      width: 100%;
      height: 100%;
      object-fit: cover;
      display: block;
      transition: transform 0.3s ease;
    }
    .style-card.active .style-thumb-wrap img {
      transform: scale(1.04);
    }
    .style-badge-float {
      position: absolute;
      top: 7px;
      left: 7px;
      font-size: 10px;
      font-weight: 700;
      color: #fff;
      background: rgba(9, 11, 16, 0.82);
      backdrop-filter: blur(6px);
      border: 1px solid rgba(212,175,55,0.45);
      padding: 3px 7px;
      border-radius: 999px;
    }
    .style-info {
      padding: 9px 10px 10px;
    }
    .style-name {
      font-size: 13px;
      font-weight: 800;
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
      gap: 9px;
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
      padding: 12px 14px;
      margin-bottom: 13px;
      font-size: 12.8px;
      line-height: 1.48;
      color: #f1f5f9;
    }

    /* Sticky Bottom Action Bar */
    .bottom-bar {
      position: fixed;
      left: 0;
      right: 0;
      bottom: 0;
      background: rgba(9, 11, 16, 0.95);
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
        <div class="logo-circle">🍌</div>
        <div>
          <div class="brand-title">JASUR BARBER • NANO BANANA AI</div>
          <div class="brand-sub">Gemini Pro / Nano Banana Jonli Soch Generatori</div>
        </div>
      </div>
      <span class="ai-badge" id="aiStatusBadge">✨ NANO BANANA</span>
    </div>

    <!-- 3 View Modes -->
    <div class="mode-tabs">
      <button type="button" class="mode-tab" data-mode="nanobanana">🍌 Nano Banana AI</button>
      <button type="button" class="mode-tab" data-mode="split">🔀 Yuzim + Jonli Stil</button>
      <button type="button" class="mode-tab active" data-mode="model">📸 4K Jonli Model</button>
    </div>

    <!-- Main Camera / Photo Viewport -->
    <div class="stage-card">
      <div class="viewport-box" id="viewportBox">
        <video id="cameraVideo" autoplay playsinline muted></video>
        <canvas id="mainCanvas" width="720" height="864" style="display:block;"></canvas>

        <div class="ai-loading-overlay" id="aiLoadingOverlay">
          <div class="spinner"></div>
          <div style="font-weight:800; color:var(--gold-light); font-size:15px;">🍌 Gemini Nano Banana AI ishlamoqda...</div>
          <div style="font-size:12px; color:var(--muted); margin-top:5px;">Yuzingizni o'zgartirmasdan tanlangan soch va soqolni fotorealistik chizmoqda (3–6 soniya)</div>
        </div>

        <div class="canvas-top-badges" id="canvasBadges">
          <span class="pill-badge" id="faceShapeBadge">🧠 Yuz: Oval</span>
          <span class="pill-match" id="matchBadge">🔥 98% Mos</span>
        </div>

        <button type="button" class="compare-btn" id="compareBtn">👁 Bosib turing: Asl rasm</button>

        <div class="face-guide-overlay" id="faceGuideOverlay" style="display:none;">
          <div class="face-oval"></div>
          <div class="guide-hint">Yuzingizni oval markaziga joylashtiring</div>
        </div>
      </div>

      <!-- Camera Active Shutter Controls -->
      <div class="action-strip" id="cameraControls" style="display:none;">
        <button type="button" class="btn btn-gold" id="capturePhotoBtn" style="flex:1;">📸 Suratga olish va Nano Banana AI</button>
        <button type="button" class="btn btn-dark" id="cancelCameraBtn">✖ Bekor</button>
      </div>

      <!-- Standard Camera / Upload Action Strip -->
      <div class="action-strip" id="photoControls">
        <div style="display:flex; gap:7px; flex-wrap:wrap;">
          <button type="button" class="btn btn-gold btn-sm" id="startCameraBtn">📷 Kamera (Selfi)</button>
          <label for="fileInput" class="btn btn-dark btn-sm" style="cursor:pointer;">🖼 Galereyadan rasm</label>
          <button type="button" class="btn btn-gold btn-sm" id="runNanoBananaBtn" style="display:none;">🍌 AI Sochni Kiygizish</button>
        </div>
        <button type="button" class="btn btn-dark btn-sm" id="downloadBtn">📥 Saqlash</button>
      </div>

      <input type="file" id="fileInput" accept="image/*" style="display:none;">
    </div>

    <!-- 4 Real Photo Top Variants -->
    <div class="variants-section" id="variantsSection">
      <div class="sec-title">
        <span>🔥 Yuz shaklingiz uchun Top 4 Jonli Variant</span>
        <span style="font-size:11px; color:var(--muted); font-weight:500;">Bosib ko'ring</span>
      </div>
      <div class="variants-grid" id="variantsGrid"></div>
    </div>

    <!-- AI Stylist Recommendation Box -->
    <div class="ai-advice-card" id="aiAdviceBox">
      🍌 <b>Gemini Nano Banana AI:</b> «📷 Kamera (Selfi)» yoki «🖼 Galereyadan rasm» tugmasini bosing — Gemini Nano Banana AI sizning o'z yuzingizga tanlangan soch va soqolni haqiqiy jonli fotosuratdek qilib kiygizib beradi!
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
        <span>🎨 Soch rangi tusi</span>
      </div>
      <div class="color-row" id="colorSwatches">
        <div class="color-swatch active" data-color="natural_black">
          <span class="dot" style="background:#141418;"></span> Tabiiy Qora
        </div>
        <div class="color-swatch" data-color="dark_brown">
          <span class="dot" style="background:#4a2c18;"></span> Issiq Kashtan
        </div>
        <div class="color-swatch" data-color="warm_chestnut">
          <span class="dot" style="background:#7a4b2a;"></span> Oltin Jigarrang
        </div>
        <div class="color-swatch" data-color="ash_graphite">
          <span class="dot" style="background:#7d8594;"></span> Kulrang / Silver
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

    <!-- 10 Real HD Hairstyles Catalog -->
    <div class="panel-card">
      <div class="sec-title">
        <span>💇‍♂️ 10 Xil Jonli Soch Turmaklari Katalogi</span>
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

  <script type="module">
    const tg = window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null;
    if (tg) {
      try {
        tg.ready();
        tg.expand();
      } catch (e) {}
    }

    const HAIRSTYLES = [
      {
        id: "low_fade_crop",
        name: "Low Fade + Crop",
        badge: "🔥 Eng mashhur",
        desc: "Yonlari pastdan silliq fade va tepasi teksturali zamonaviy turmak",
        shapes: ["oval", "square", "diamond", "round"],
        photo: "https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?w=720&auto=format&fit=crop&q=85"
      },
      {
        id: "high_skin_fade_quiff",
        name: "High Fade + Quiff",
        badge: "⚡ Hajmli",
        desc: "Yonlari nolga yaqin fade va old qismi ko'tarilgan hajmli Quiff",
        shapes: ["round", "oval", "square"],
        photo: "https://images.unsplash.com/photo-1500648767791-00dcc994a43e?w=720&auto=format&fit=crop&q=85"
      },
      {
        id: "classic_side_part",
        name: "Classic Side Part",
        badge: "👔 Klassika",
        desc: "Yonga taralgan rasmiy va tartibli jentlmen uslubi",
        shapes: ["oval", "square", "oblong", "diamond"],
        photo: "https://images.unsplash.com/photo-1519085360753-af0119f7cbe7?w=720&auto=format&fit=crop&q=85"
      },
      {
        id: "modern_pompadour",
        name: "Modern Pompadour",
        badge: "👑 Premium",
        desc: "Tepa qismi orqaga va yuqoriga silliq hajmli taralgan",
        shapes: ["round", "oval", "square"],
        photo: "https://images.unsplash.com/photo-1506794778202-cad84cf45f1d?w=720&auto=format&fit=crop&q=85"
      },
      {
        id: "buzz_cut_fade",
        name: "Buzz Cut + Fade",
        badge: "💪 Sport",
        desc: "Kalta, keskin konturli va jag'ni ochuvchi sport uslubi",
        shapes: ["square", "oval", "diamond"],
        photo: "https://images.unsplash.com/photo-1463453091185-61582044d556?w=720&auto=format&fit=crop&q=85"
      },
      {
        id: "undercut_slick",
        name: "Undercut Slick",
        badge: "✨ Kontrast",
        desc: "Yonlari kalta, tepasi uzun kontrastli zamonaviy uslub",
        shapes: ["oval", "round", "diamond"],
        photo: "https://images.unsplash.com/photo-1492562080023-ab3db95bfbce?w=720&auto=format&fit=crop&q=85"
      },
      {
        id: "french_crop",
        name: "French Crop",
        badge: "🎯 Trend 2026",
        desc: "Peshona chizig'i tekis va tepasi qalin teksturali Yevropa stili",
        shapes: ["oblong", "oval", "diamond", "square"],
        photo: "https://images.unsplash.com/photo-1539571696357-5a69c17a67c6?w=720&auto=format&fit=crop&q=85"
      },
      {
        id: "curly_taper",
        name: "Curly Drop Fade",
        badge: "🌊 Jingalak",
        desc: "To'lqinli/jingalak tabiiy hajm va toza yon fade",
        shapes: ["oval", "oblong", "diamond", "round"],
        photo: "https://images.unsplash.com/photo-1522075469751-3a6694fb2f61?w=720&auto=format&fit=crop&q=85"
      },
      {
        id: "modern_mullet",
        name: "Burst Fade Mullet",
        badge: "🔥 Yoshlarbop",
        desc: "Quloq atrofi yarim oy fade va teksturali zamonaviy ko'rinish",
        shapes: ["oval", "diamond", "square"],
        photo: "https://images.unsplash.com/photo-1501196354995-cbb51c65aaea?w=720&auto=format&fit=crop&q=85"
      },
      {
        id: "textured_fringe",
        name: "Textured Fringe",
        badge: "🌟 Tabiiy",
        desc: "Oldinga tushgan erkin va tabiiy teksturali turmak",
        shapes: ["oblong", "diamond", "oval"],
        photo: "https://images.unsplash.com/photo-1472099645785-5658abf4ff4e?w=720&auto=format&fit=crop&q=85"
      }
    ];

    const BEARDS = [
      { id: "fade_beard", name: "Fade Soqol" },
      { id: "stubble", name: "Yengil (3 kunlik)" },
      { id: "full_beard", name: "To'liq Qalin Soqol" },
      { id: "goatee", name: "Goatee (Espanyolka)" },
      { id: "none", name: "Soqolsiz (Toza)" }
    ];

    const imageCache = {};
    const nanoBananaCache = {};
    const state = {
      hasUserPhoto: false,
      viewMode: "model",
      userCanvas: document.createElement("canvas"),
      generatedImage: null,
      faceBox: { cx: 360, cy: 430, rx: 165, ry: 215, foreheadY: 250 },
      faceShape: "oval",
      styleId: "low_fade_crop",
      beardId: "fade_beard",
      hairColor: "natural_black",
      showOriginal: false,
      stream: null,
      faceLandmarker: null
    };
    state.userCanvas.width = 720;
    state.userCanvas.height = 864;

    const videoEl = document.getElementById("cameraVideo");
    const mainCanvas = document.getElementById("mainCanvas");
    const ctx = mainCanvas.getContext("2d");
    const faceGuideOverlay = document.getElementById("faceGuideOverlay");
    const cameraControls = document.getElementById("cameraControls");
    const photoControls = document.getElementById("photoControls");
    const runNanoBananaBtn = document.getElementById("runNanoBananaBtn");
    const aiLoadingOverlay = document.getElementById("aiLoadingOverlay");
    const compareBtn = document.getElementById("compareBtn");
    const variantsGrid = document.getElementById("variantsGrid");
    const aiAdviceBox = document.getElementById("aiAdviceBox");
    const faceShapeBadge = document.getElementById("faceShapeBadge");
    const matchBadge = document.getElementById("matchBadge");
    const aiStatusBadge = document.getElementById("aiStatusBadge");

    function loadStyleImage(styleObj) {
      if (imageCache[styleObj.id]) return Promise.resolve(imageCache[styleObj.id]);
      return new Promise((resolve) => {
        const img = new Image();
        img.crossOrigin = "anonymous";
        img.onload = () => {
          imageCache[styleObj.id] = img;
          resolve(img);
        };
        img.onerror = () => resolve(null);
        img.src = styleObj.photo;
      });
    }

    async function initMediaPipe() {
      try {
        const vision = await import("https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.14/vision_bundle.mjs");
        const filesetResolver = await vision.FilesetResolver.forVisionTasks(
          "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.14/wasm"
        );
        state.faceLandmarker = await vision.FaceLandmarker.createFromOptions(filesetResolver, {
          baseOptions: {
            modelAssetPath: "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task"
          },
          outputFaceBlendshapes: false,
          runningMode: "IMAGE",
          numFaces: 1
        });
      } catch (e) {}
    }

    function setViewMode(mode) {
      state.viewMode = mode;
      document.querySelectorAll(".mode-tab").forEach(btn => {
        btn.classList.toggle("active", btn.dataset.mode === mode);
      });
      renderMainStage();
    }

    document.querySelectorAll(".mode-tab").forEach(btn => {
      btn.onclick = () => {
        const m = btn.dataset.mode;
        if ((m === "nanobanana" || m === "split") && !state.hasUserPhoto) {
          startCamera();
          return;
        }
        setViewMode(m);
        if (m === "nanobanana" && state.hasUserPhoto && !state.generatedImage) {
          triggerNanoBananaGeneration();
        }
      };
    });

    function detectUserFaceAndShape() {
      const uc = state.userCanvas;
      const w = uc.width, h = uc.height;
      if (state.faceLandmarker) {
        try {
          const res = state.faceLandmarker.detect(uc);
          if (res && res.faceLandmarks && res.faceLandmarks.length > 0) {
            const lm = res.faceLandmarks[0];
            const top = lm[10], chin = lm[152], leftCheek = lm[234], rightCheek = lm[454];
            const leftJaw = lm[172], rightJaw = lm[397], leftFore = lm[103], rightFore = lm[332];

            const faceW = Math.hypot((rightCheek.x - leftCheek.x) * w, (rightCheek.y - leftCheek.y) * h);
            const faceH = Math.hypot((chin.x - top.x) * w, (chin.y - top.y) * h);
            const jawW = Math.hypot((rightJaw.x - leftJaw.x) * w, (rightJaw.y - leftJaw.y) * h);
            const foreW = Math.hypot((rightFore.x - leftFore.x) * w, (rightFore.y - leftFore.y) * h);

            const ratio = faceH / Math.max(1, faceW);
            const jawRatio = jawW / Math.max(1, faceW);
            let shape = "oval";
            if (ratio > 1.38) shape = "oblong";
            else if (ratio < 1.15 && jawRatio < 0.82) shape = "round";
            else if (jawRatio >= 0.84) shape = "square";
            else if (faceW > foreW * 1.16 && faceW > jawW * 1.18) shape = "diamond";
            else shape = "oval";

            setFaceShape(shape, false);
            return;
          }
        } catch (err) {}
      }
    }

    function drawImageCover(g, img, dx, dy, dw, dh) {
      const iw = img.width || 720, ih = img.height || 864;
      const targetRatio = dw / dh;
      const imgRatio = iw / ih;
      let sx = 0, sy = 0, sw = iw, sh = ih;
      if (imgRatio > targetRatio) {
        sw = ih * targetRatio;
        sx = (iw - sw) / 2;
      } else {
        sh = iw / targetRatio;
        sy = (ih - sh) / 2;
      }
      g.drawImage(img, sx, sy, sw, sh, dx, dy, dw, dh);
    }

    function applyColorFilter(g, colorKey) {
      if (colorKey === "dark_brown") g.filter = "sepia(0.28) saturate(1.35) brightness(0.96)";
      else if (colorKey === "warm_chestnut") g.filter = "sepia(0.45) saturate(1.55) brightness(1.04)";
      else if (colorKey === "ash_graphite") g.filter = "saturate(0.25) contrast(1.08) brightness(1.06)";
      else g.filter = "none";
    }

    async function renderMainStage() {
      const w = mainCanvas.width, h = mainCanvas.height;
      const stObj = HAIRSTYLES.find(s => s.id === state.styleId) || HAIRSTYLES[0];
      const styleImg = await loadStyleImage(stObj);

      ctx.save();
      ctx.clearRect(0, 0, w, h);

      if (state.showOriginal && state.hasUserPhoto) {
        ctx.drawImage(state.userCanvas, 0, 0, w, h);
        drawStageFooter(ctx, w, h, "Sizning asl suratingiz", "");
        ctx.restore();
        return;
      }

      // MODE 1: Nano Banana AI Generated Photo on User's Face
      if (state.viewMode === "nanobanana" && state.hasUserPhoto) {
        if (state.generatedImage) {
          drawImageCover(ctx, state.generatedImage, 0, 0, w, h);
          drawStageFooter(ctx, w, h, "🍌 " + stObj.name + " (Nano Banana AI)", "Sizning yuzingizda Gemini Nano Banana AI yaratgan jonli natija");
          ctx.restore();
          return;
        }
      }

      // MODE 2: Side-by-Side Split Studio Comparison
      if (state.viewMode === "split" && state.hasUserPhoto) {
        const halfW = w / 2;
        ctx.save();
        ctx.beginPath();
        ctx.rect(0, 0, halfW, h);
        ctx.clip();
        drawImageCover(ctx, state.userCanvas, 0, 0, halfW, h);
        ctx.restore();

        if (styleImg) {
          ctx.save();
          ctx.beginPath();
          ctx.rect(halfW, 0, halfW, h);
          ctx.clip();
          applyColorFilter(ctx, state.hairColor);
          drawImageCover(ctx, styleImg, halfW, 0, halfW, h);
          ctx.filter = "none";
          ctx.restore();
        }

        ctx.strokeStyle = "#d4af37";
        ctx.lineWidth = 3;
        ctx.beginPath();
        ctx.moveTo(halfW, 0);
        ctx.lineTo(halfW, h);
        ctx.stroke();

        ctx.fillStyle = "rgba(9, 11, 16, 0.82)";
        ctx.fillRect(12, 54, 155, 28);
        ctx.fillRect(halfW + 12, 54, 175, 28);
        ctx.fillStyle = "#f5e6b3";
        ctx.font = "bold 16px sans-serif";
        ctx.fillText("👤 Sizning yuzingiz", 18, 73);
        ctx.fillText("💈 " + stObj.name, halfW + 18, 73);

        drawStageFooter(ctx, w, h, stObj.name + " • Yuzingizga moslik", stObj.desc);
        ctx.restore();
        return;
      }

      // MODE 3: 4K Real Model Portrait
      if (styleImg) {
        applyColorFilter(ctx, state.hairColor);
        drawImageCover(ctx, styleImg, 0, 0, w, h);
        ctx.filter = "none";
      }
      drawStageFooter(
        ctx,
        w,
        h,
        stObj.name,
        state.hasUserPhoto
          ? "🍌 «AI Sochni Kiygizish» tugmasini bosing — Nano Banana AI o'z yuzingizda chizib beradi"
          : "📷 O'z yuzingizda Nano Banana AI bilan sinash uchun «Kamera (Selfi)» tugmasini bosing"
      );
      ctx.restore();
    }

    function drawStageFooter(g, w, h, title, subtitle) {
      const grad = g.createLinearGradient(0, h - 125, 0, h);
      grad.addColorStop(0, "rgba(8, 10, 15, 0)");
      grad.addColorStop(0.55, "rgba(8, 10, 15, 0.82)");
      grad.addColorStop(1, "rgba(8, 10, 15, 0.96)");
      g.fillStyle = grad;
      g.fillRect(0, h - 125, w, 125);

      g.fillStyle = "#f5e6b3";
      g.font = "bold 22px sans-serif";
      g.fillText("💈 " + title, 20, h - 46);

      if (subtitle) {
        g.fillStyle = "#cbd5e1";
        g.font = "15px sans-serif";
        g.fillText(subtitle, 20, h - 20);
      }
    }

    async function triggerNanoBananaGeneration() {
      if (!state.hasUserPhoto) {
        startCamera();
        return;
      }
      const cacheKey = `${state.styleId}_${state.beardId}_${state.hairColor}`;
      if (nanoBananaCache[cacheKey]) {
        state.generatedImage = nanoBananaCache[cacheKey];
        setViewMode("nanobanana");
        return;
      }

      aiLoadingOverlay.style.display = "flex";
      try {
        const jpegDataUrl = state.userCanvas.toDataURL("image/jpeg", 0.86);
        const resp = await fetch("/webapp/api/generate", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            style_id: state.styleId,
            beard_id: state.beardId,
            face_shape: state.faceShape,
            hair_color: state.hairColor,
            image: jpegDataUrl
          })
        });
        const data = await resp.json();
        if (data && data.ok) {
          matchBadge.textContent = "🔥 " + data.match_score + "% Mos";
          aiAdviceBox.innerHTML = "🍌 <b>Gemini Nano Banana AI:</b> " + data.ai_advice;

          if (data.generated_image) {
            const genImg = new Image();
            genImg.onload = () => {
              nanoBananaCache[cacheKey] = genImg;
              state.generatedImage = genImg;
              aiLoadingOverlay.style.display = "none";
              setViewMode("nanobanana");
            };
            genImg.src = data.generated_image;
            return;
          }
        }
      } catch (err) {}
      aiLoadingOverlay.style.display = "none";
      setViewMode("split");
    }

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
          if (state.hasUserPhoto) triggerNanoBananaGeneration();
          else requestAiAdvice();
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
          <div class="style-thumb-wrap">
            <img src="${s.photo}" alt="${s.name}" loading="lazy" crossorigin="anonymous">
            <span class="style-badge-float">${isRec ? "✅ Yuzga mos • " : ""}${s.badge}</span>
          </div>
          <div class="style-info">
            <div class="style-name">${s.name}</div>
            <div class="style-desc">${s.desc}</div>
          </div>
        `;
        card.onclick = () => {
          state.styleId = s.id;
          renderSelectors();
          renderVariantsBar();
          if (state.hasUserPhoto) triggerNanoBananaGeneration();
          else {
            renderMainStage();
            requestAiAdvice();
          }
        };
        stylesWrap.appendChild(card);
      });
    }

    function renderVariantsBar() {
      const recommended = HAIRSTYLES.filter(s => s.shapes.includes(state.faceShape)).slice(0, 4);
      if (!recommended.some(s => s.id === state.styleId)) {
        const cur = HAIRSTYLES.find(s => s.id === state.styleId);
        if (cur) recommended[3] = cur;
      }

      variantsGrid.innerHTML = "";
      recommended.forEach(s => {
        const item = document.createElement("div");
        item.className = "variant-item" + (s.id === state.styleId ? " active" : "");
        item.innerHTML = `
          <img src="${s.photo}" alt="${s.name}" crossorigin="anonymous">
          <div class="variant-label">${s.name}</div>
        `;
        item.onclick = () => {
          state.styleId = s.id;
          renderSelectors();
          renderVariantsBar();
          if (state.hasUserPhoto) triggerNanoBananaGeneration();
          else {
            renderMainStage();
            requestAiAdvice();
          }
        };
        variantsGrid.appendChild(item);
      });
    }

    function setFaceShape(shape, triggerUpdate = true) {
      state.faceShape = shape;
      document.querySelectorAll("#faceShapeChips .chip").forEach(btn => {
        btn.classList.toggle("active", btn.dataset.shape === shape);
      });
      const names = { oval: "Oval", square: "Kvadrat", round: "Dumaloq", diamond: "Olmos", oblong: "Uzunchoq" };
      faceShapeBadge.textContent = "🧠 Yuz: " + (names[shape] || "Oval");
      renderSelectors();
      renderVariantsBar();
      if (triggerUpdate) {
        renderMainStage();
        requestAiAdvice();
      }
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
          aiAdviceBox.innerHTML = "🍌 <b>Gemini Nano Banana AI:</b> " + data.ai_advice;
        }
      } catch (err) {}
    }

    async function startCamera() {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: "user", width: { ideal: 720 }, height: { ideal: 864 } },
          audio: false
        });
        state.stream = stream;
        videoEl.srcObject = stream;
        mainCanvas.style.display = "none";
        videoEl.style.display = "block";
        faceGuideOverlay.style.display = "flex";
        cameraControls.style.display = "flex";
        photoControls.style.display = "none";
      } catch (err) {
        alert("Kameraga ruxsat berilmadi. «🖼 Galereyadan rasm» tugmasi orqali rasmingizni tanlang.");
      }
    }

    function stopCamera() {
      if (state.stream) {
        state.stream.getTracks().forEach(t => t.stop());
        state.stream = null;
      }
    }

    function onUserPhotoLoaded() {
      state.hasUserPhoto = true;
      state.generatedImage = null;
      Object.keys(nanoBananaCache).forEach(k => delete nanoBananaCache[k]);

      videoEl.style.display = "none";
      faceGuideOverlay.style.display = "none";
      cameraControls.style.display = "none";
      photoControls.style.display = "flex";
      runNanoBananaBtn.style.display = "inline-flex";
      mainCanvas.style.display = "block";

      detectUserFaceAndShape();
      triggerNanoBananaGeneration();
    }

    document.getElementById("startCameraBtn").onclick = startCamera;
    runNanoBananaBtn.onclick = triggerNanoBananaGeneration;

    document.getElementById("cancelCameraBtn").onclick = () => {
      stopCamera();
      videoEl.style.display = "none";
      faceGuideOverlay.style.display = "none";
      cameraControls.style.display = "none";
      photoControls.style.display = "flex";
      mainCanvas.style.display = "block";
      renderMainStage();
    };

    document.getElementById("capturePhotoBtn").onclick = () => {
      const uc = state.userCanvas;
      const uctx = uc.getContext("2d");
      const vw = videoEl.videoWidth || 720;
      const vh = videoEl.videoHeight || 864;
      const targetRatio = uc.width / uc.height;
      const videoRatio = vw / vh;
      let sx = 0, sy = 0, sw = vw, sh = vh;
      if (videoRatio > targetRatio) {
        sw = vh * targetRatio;
        sx = (vw - sw) / 2;
      } else {
        sh = vw / targetRatio;
        sy = (vh - sh) / 2;
      }
      uctx.save();
      uctx.translate(uc.width, 0);
      uctx.scale(-1, 1);
      uctx.drawImage(videoEl, sx, sy, sw, sh, 0, 0, uc.width, uc.height);
      uctx.restore();
      stopCamera();
      onUserPhotoLoaded();
    };

    document.getElementById("fileInput").onchange = (ev) => {
      const file = ev.target.files && ev.target.files[0];
      if (!file) return;
      const reader = new FileReader();
      reader.onload = (e) => {
        const img = new Image();
        img.onload = () => {
          const uc = state.userCanvas;
          const uctx = uc.getContext("2d");
          drawImageCover(uctx, img, 0, 0, uc.width, uc.height);
          onUserPhotoLoaded();
        };
        img.src = e.target.result;
      };
      reader.readAsDataURL(file);
    };

    document.getElementById("downloadBtn").onclick = () => {
      const link = document.createElement("a");
      link.download = "jasur_barber_nanobanana_" + state.styleId + ".png";
      link.href = mainCanvas.toDataURL("image/png");
      link.click();
    };

    compareBtn.onmousedown = compareBtn.ontouchstart = (e) => {
      e.preventDefault();
      state.showOriginal = true;
      renderMainStage();
    };
    window.addEventListener("mouseup", () => {
      if (state.showOriginal) {
        state.showOriginal = false;
        renderMainStage();
      }
    });
    window.addEventListener("touchend", () => {
      if (state.showOriginal) {
        state.showOriginal = false;
        renderMainStage();
      }
    });

    document.querySelectorAll("#faceShapeChips .chip").forEach(btn => {
      btn.onclick = () => setFaceShape(btn.dataset.shape, true);
    });

    document.querySelectorAll("#colorSwatches .color-swatch").forEach(sw => {
      sw.onclick = () => {
        state.hairColor = sw.dataset.color;
        document.querySelectorAll("#colorSwatches .color-swatch").forEach(el => {
          el.classList.toggle("active", el.dataset.color === state.hairColor);
        });
        if (state.hasUserPhoto) triggerNanoBananaGeneration();
        else {
          renderMainStage();
          requestAiAdvice();
        }
      };
    });

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
        alert("Tanlangan uslub: " + stObj.name + " (" + bdObj.name + "). Botga qaytib navbatga yozilishingiz mumkin!");
      }
    };

    renderSelectors();
    renderVariantsBar();
    renderMainStage();
    requestAiAdvice();
    initMediaPipe();
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
