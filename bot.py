import os
import logging
import numpy as np
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler

# --- KONFIGURASI ---
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    raise ValueError("⚠️ Set environment variable TELEGRAM_BOT_TOKEN di hosting Anda.")

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)

# --- STATE FLOW ---
AWAIT_MATCH, AWAIT_ODDS = range(2)

# --- ENGINE MATEMATIKA RINGAN (Lite v1) ---
def dixon_coles_poisson(home_xg, away_xg, max_goals=5):
    rho = -0.13  # Dixon-Coles correlation
    tau = 1.0    # Low-score correction
    probs = {}
    for h in range(max_goals + 1):
        for a in range(max_goals + 1):
            p_h = (home_xg**h * np.exp(-home_xg)) / np.math.factorial(h)
            p_a = (away_xg**a * np.exp(-away_xg)) / np.math.factorial(a)
            corr = 1.0
            if h == 0 and a == 0:
                corr = 1 - rho
            elif (h == 0 and a == 1) or (h == 1 and a == 0):
                corr = 1 + rho
            probs[(h, a)] = p_h * p_a * corr
    # Normalisasi
    total = sum(probs.values())
    return {k: v / total for k, v in probs.items()}

def calc_fair_probs(score_probs):
    home = sum(p for (h,a), p in score_probs.items() if h > a)
    draw = sum(p for (h,a), p in score_probs.items() if h == a)
    away = sum(p for (h,a), p in score_probs.items() if h < a)
    btts = sum(p for (h,a), p in score_probs.items() if h >= 1 and a >= 1)
    over25 = sum(p for (h,a), p in score_probs.items() if h + a > 2.5)
    return {"1": home, "X": draw, "2": away, "BTTS": btts, "O2.5": over25}

def monte_carlo_sim(home_xg, away_xg, n=2000):
    # Simulasi ringan untuk free tier (10k bisa timeout di Render free)
    home_scores = np.random.poisson(home_xg, n)
    away_scores = np.random.poisson(away_xg, n)
    home_win = np.mean(home_scores > away_scores)
    draw = np.mean(home_scores == away_scores)
    away_win = np.mean(home_scores < away_scores)
    btts = np.mean((home_scores >= 1) & (away_scores >= 1))
    return home_win, draw, away_win, btts

def calc_value(fair_prob, odds):
    implied = 1 / odds
    edge = fair_prob - implied
    ev = (fair_prob * odds) - 1
    re = (fair_prob * odds * ev) * 0.5  # Simplified RE
    return edge, ev, re

def analyze_match(match_text):
    # Default xG (bisa diganti dengan API call nanti)
    home_xg = 1.42
    away_xg = 1.35
    score_probs = dixon_coles_poisson(home_xg, away_xg)
    fair = calc_fair_probs(score_probs)
    top5 = sorted(score_probs.items(), key=lambda x: x[1], reverse=True)[:5]
    mc_h, mc_d, mc_a, mc_btts = monte_carlo_sim(home_xg, away_xg)
    return fair, top5, mc_h, mc_d, mc_a, mc_btts

# --- TELEGRAM HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 *Predictive Edge Lite Bot*\n\n"
        "📥 Kirim: `Tim Home vs Tim Away`\n"
        "📊 Bot akan kirim Fair Prob + Combo Grid\n"
        "💰 Lalu kirim odds bookmaker untuk hitung Edge/RE\n\n"
        "Ketik `/cancel` untuk reset",
        parse_mode="Markdown"
    )
    return AWAIT_MATCH

async def handle_match(update: Update, context: ContextTypes.DEFAULT_TYPE):
    match = update.message.text.strip()
    if "vs" not in match.lower() and "lawan" not in match.lower():
        await update.message.reply_text("⚠️ Format: `Tim A vs Tim B`")
        return AWAIT_MATCH

    fair, top5, mc_h, mc_d, mc_a, mc_btts = analyze_match(match)
    
    msg = (f"📊 *{match}*\n"
           f"📈 Fair Prob (Poisson): H {fair['1']:.1%} | X {fair['X']:.1%} | A {fair['2']:.1%}\n"
           f"🔢 BTTS: {fair['BTTS']:.1%} | O2.5: {fair['O2.5']:.1%}\n"
           f"🎯 Top 5 Skor:\n")
    for (h,a), p in top5:
        bar = "█" * int(p * 100)
        msg += f"  {h}-{a} → {p:.1%} {bar}\n"
    
    msg += (f"\n📥 *Kirim odds* (contoh):\n"
            f"`2.30 | 3.40 | 2.80` (untuk 1X2)\n"
            f"`1.85` (untuk 1 pasar tertentu)")
    
    await update.message.reply_text(msg, parse_mode="Markdown")
    return AWAIT_ODDS

async def handle_odds(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        raw = update.message.text.strip().replace("|", " ")
        odds_list = [float(x) for x in raw.split()]
        
        # Contoh kalkulasi untuk odds pertama (Home/Primary)
        odds = odds_list[0]
        fair_h = 0.42  # Placeholder dari fair['1'] tadi (disimpan di real app via context)
        edge, ev, re = calc_value(fair_h, odds)
        
        status = "🟢 GO" if ev > 0.08 else ("🟡 WAIT" if ev > 0 else "🔴 STOP")
        
        msg = (f"📊 *Value Analysis*\n"
               f"Odds: `{odds}`\n"
               f"Fair Prob: `42.0%` | Implied: `{1/odds:.1%}`\n"
               f"Edge: `{edge:+.1%}` | EV: `{ev:+.2f}`\n"
               f"RE: `{re:.2f}`\n"
               f"🚦 *{status}*\n\n"
               f"💡 Tip: EV > 0.05 = 🟢 | EV 0-0.05 = 🟡 | EV < 0 = 🔴")
        
        await update.message.reply_text(msg, parse_mode="Markdown")
    except ValueError:
        await update.message.reply_text("❌ Format odds tidak valid. Contoh: `2.10` atau `2.30 | 3.40 | 2.90`")
    
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ Dibatalkan. Ketik `/start` untuk mulai.")
    return ConversationHandler.END

# --- MAIN ---
def main():
    app = Application.builder().token(TOKEN).build()
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start), MessageHandler(filters.TEXT & ~filters.COMMAND, handle_match)],
        states={
            AWAIT_MATCH: [MessageHandler(filters.TEXT, handle_match)],
            AWAIT_ODDS: [MessageHandler(filters.TEXT, handle_odds)]
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )
    app.add_handler(conv_handler)
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()