# Button Icons (Premium Custom Emoji Table)

This document lists the custom emoji mappings used for Telegram buttons across the bot.
When `USE_PREMIUM_EMOJI=true` and the bot owner has Telegram Premium, these custom emoji IDs are attached as `icon_custom_emoji_id` and the leading legacy emoji is stripped from the button text.

| Icon Name | Legacy Emoji | Custom Emoji ID | Notes |
|:---|:---:|:---:|:---|
| check | ✅ | 5224400190244401421 | Confirmation / success actions |
| cross | ❌ | 5222214769150276151 | Rejection / cancellation |
| forbidden | 🚫 | 5929331428780151040 | Block user / cancel order |
| card | 💳 | 5787190619990396653 | Card payment / transfer |
| play | ▶️ | 5224457150100680165 | Start work |
| pause | ⏸ | 5224457150100680165 | Take break |
| refresh | 🔄 | 5465368548702446780 | Refresh / toggle / refunds |
| lang | 🌐 | 5217952701303788099 | Language switch |
| money | 💰 | 5222076153375789857 | Payments menu |
| queue | 📋 | 5303166093701959050 | Queue list |
| plus | ➕ | 5359651386160068849 | Add walk-in / add service |
| history | 📜 | 5433653135799228968 | Client queue history |
| barbershop | 💈 | 5334882760735598374 | Join queue menu |
| ticket | 🎫 | 5334882760735598374 | My ticket / queue position |
| back | ⬅️ | 5877536313623711363 | Back navigation buttons |
| home | 🏠 | 5350404270032166927 | Back to main menu |
| green | 🟢 | 6084384451154941172 | Active / work day |
| red | 🔴 | 6082387218347857432 | Inactive / day off |
| edit | ✏️ | 5334720483986256027 | Edit hours / details |
| download | 📥 | 5433811242135331842 | Download CSV reports |
| user | 👤 | 5886496611835581345 | Barber / user info |
| stats | 📊 | 5931472654660800739 | All queues overview |
| users | 👥 | 5422518677897512402 | Barbers list |
| chart | 📈 | 5350723128404228854 | Reports & analytics |
| attach | 📎 | 6050592962730005028 | Send payment receipt photo |
| instagram | — | 5440699214331926774 | Instagram channel link |

## Special Button Handling
- **💵 (Cash buttons)**: Ordinary 💵 emoji is kept in the button text; no premium emoji ID is assigned.
- **✂️ (Services & Done buttons)**: Automatically replaced with 💇 in button texts across all languages (`uz`, `uz_cyrl`, `ru`).
- **Button Styles**: Exactly 8 buttons use Telegram Bot API `style` colors (`success`, `danger`, `primary`).
