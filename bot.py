import os, math, logging, re
import numpy as np
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    logger.error("❌ TELEGRAM_BOT_TOKEN tidak ditemukan. Set di environment variables!")
    exit(1)

AWAIT_MATCH, AWAIT_ODDS = range(2)

def dixon_coles(h, a, max_g=5):
    rho = -0.13
    probs = {}
    for i in range(max_g+1):
        for j in range(max_g+1):
            ph = (h**i * math.exp(-h)) / math.factorial(i)
            pa = (a**j * math.exp(-a)) / math.factorial(j)
            corr = 1 - rho if (i==0 and j==0) else (1 + rho if (i<=1 and j<=1) else 1)
            probs[(i,j)] = ph * pa * corr
    total = sum(probs.values())
    return {k: v/total for k,v in probs.items()}

def monte_carlo(h, a, n=2000):
    hs, as_ = np.random.poisson(h, n), np.random.poisson(a, n)
    return {
        "H": float(np.mean(hs > as_)), "D": float(np.mean(hs == as_)),
        "A": float(np.mean(hs < as_)), "BTTS": float(np.mean((hs>=1) & (as_>=1))),
        "O2.5": float(np.mean((hs+as_) > 2.5))
    }

def parse_odds(text):
    odds = {}
    m = re.search(r"1X2\s*[:=]?\s*(\d+\.?\d*)\s*\|\s*(\d+\.?\d*)\s*\|\s*(\d+\.?\d*)", text, re.I)
    if m: odds["1X2"] = [float(m.group(1)), float(m.group(2)), float(m.group(3))]
    m = re.search(r"O[./]?U\s*2\.5\s*[:=]?\s*(\d+\.?\d*)\s*[/\-]\s*(\d+\.?\d*)", text, re.I)
    if m: odds.update({"O2.5": float(m.group(1)), "U2.5": float(m.group(2))})
    m = re.search(r"BTTS\s*[:=]?\s*(\d+\.?\d*)\s*[/\-]\s*(\d+\.?\d*)", text, re.I)
    if m: odds.update({"BTTS_Y": float(m.group(1)), "BTTS_N": float(m.group(2))})
    if not odds:
        nums = [float(x) for x in re.findall(r"\d+\.\d+", text)]
        if len(nums) >= 3: odds["1X2"] = nums[:3]
    return odds

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🤖 *Edge Lite*\n📥 Kirim: `Tim A vs Tim B`\n💰 Lalu kirim odds\n`/cancel` reset", parse_mode="Markdown")
    return AWAIT_MATCH

async def handle_match(update: Update, context: ContextTypes.DEFAULT_TYPE):
    match = update.message.text.strip()
    if "vs" not in match.lower():
        await update.message.reply_text("⚠️ Format: `Tim A vs Tim B`")
        return AWAIT_MATCH
    await update.message.reply_text("⏳ Running model...")
    h_xg, a_xg = 1.42, 1.35
    fair = monte_carlo(h_xg, a_xg)
    dc = dixon_coles(h_xg, a_xg)
    top5 = sorted(dc.items(), key=lambda x: x[1], reverse=True)[:5]
    context.user_data["fair"] = fair
    msg = f"📊 *{match}*\n📈 Fair: H {fair['H']:.1%} | X {fair['D']:.1%} | A {fair['A']:.1%}\n🔢 BTTS: {fair['BTTS']:.1%} | O2.5: {fair['O2.5']:.1%}\n🎯 Top:\n"
    for (i,j), p in top5: msg += f"  {i}-{j} → {p:.1%}\n"
    msg += "\n📥 *Kirim odds*:\n`1X2: 2.35 | 3.48 | 2.82`"
    await update.message.reply_text(msg, parse_mode="Markdown")
    return AWAIT_ODDS

async def handle_odds(update: Update, context: ContextTypes.DEFAULT_TYPE):
    fair = context.user_data.get("fair")
    if not fair:
        await update.message.reply_text("❌ Expired. `/start`")
        return ConversationHandler.END
    odds = parse_odds(update.message.text)
    res = []
    if "1X2" in odds:
        for lbl, f, o in zip(["H","X","A"], [fair["H"], fair["D"], fair["A"]], odds["1X2"]):
            ev = (f * o) - 1
            status = "🟢" if ev > 0.05 else ("🟡" if ev > 0 else "🔴")
            res.append(f"🔹 {lbl} @ {o} → EV {ev:+.2f} {status}")
    await update.message.reply_text("📊 *VALUE*\n" + "\n".join(res) + "\n\n💡 EV>0.05=🟢 | 0-0.05=🟡 | <0=🔴", parse_mode="Markdown")
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ Reset. `/start`")
    return ConversationHandler.END

def main():
    try:
        app = Application.builder().token(TOKEN).build()
        conv = ConversationHandler(
            entry_points=[CommandHandler("start", start)],
            states={
                AWAIT_MATCH: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_match)],
                AWAIT_ODDS: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_odds)]
            },
            fallbacks=[CommandHandler("cancel", cancel)]
        )
        app.add_handler(conv)
        logger.info("🚀 Polling started...")
        app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)
    except Exception as e:
        logger.error(f"💥 CRASH: {e}")
        raise

if __name__ == "__main__":
    main()
