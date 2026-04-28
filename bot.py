import os, json, time, logging, math
import numpy as np
import httpx
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler

# ─────────────────────────────────────────────────────────────
# 1. KONFIGURASI
# ─────────────────────────────────────────────────────────────
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    raise ValueError("⚠️ Set environment variable: TELEGRAM_BOT_TOKEN")

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

AWAIT_MATCH, AWAIT_ODDS = range(2)

# ─────────────────────────────────────────────────────────────
# 2. MATH ENGINE (Fixed & Free-Tier Safe)
# ─────────────────────────────────────────────────────────────
def dixon_coles(h_xg, a_xg, max_g=5):
    rho = -0.13
    probs = {}
    for h in range(max_g+1):
        for a in range(max_g+1):
            ph = (h_xg**h * math.exp(-h_xg)) / math.factorial(h)
            pa = (a_xg**a * math.exp(-a_xg)) / math.factorial(a)
            corr = 1 - rho if (h==0 and a==0) else (1 + rho if (h<=1 and a<=1) else 1)
            probs[(h,a)] = ph * pa * corr
    total = sum(probs.values())
    return {k: v/total for k,v in probs.items()}

def monte_carlo(h_xg, a_xg, n=3000):
    hs = np.random.poisson(h_xg, n)
    as_ = np.random.poisson(a_xg, n)
    return {
        "H": float(np.mean(hs > as_)),
        "D": float(np.mean(hs == as_)),
        "A": float(np.mean(hs < as_)),
        "BTTS": float(np.mean((hs>=1) & (as_>=1))),
        "O2.
