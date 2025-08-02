import discord
from discord.ext import commands
from discord import app_commands
from flask import Flask, request, jsonify
from flask_cors import CORS  # ← 追加！
from threading import Thread
from datetime import datetime, timedelta, timezone
import uuid
import os

# --------------------------
# Flask サーバーとセッション管理
# --------------------------
SESSION_DATA = {}

app = Flask(__name__)
CORS(app)  # ← CORS有効化！

@app.route('/')
def home():
    return "I'm alive"

@app.route('/api/session')
def get_session():
    session_id = request.args.get("session")
    if not session_id or session_id not in SESSION_DATA:
        return jsonify({"error": "Session not found"}), 404

    data = SESSION_DATA[session_id]
    if data["expires_at"] < datetime.now(timezone.utc):
        return jsonify({"error": "Session expired"}), 410

    return jsonify({
        "user_id": data["user_id"],
        "coins": data["coins"]
    })

def run_flask():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run_flask)
    t.start()

# --------------------------
# Discord Bot の初期化
# --------------------------
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"Bot connected as {bot.user}")

@bot.tree.command(name="slot", description="スロットゲームを開始します")
@app_commands.describe(coins="初期コイン数（例：100）")
async def slot(interaction: discord.Interaction, coins: int):
    if coins <= 0:
        await interaction.response.send_message("コイン数は1以上にしてください。", ephemeral=True)
        return

    session_id = str(uuid.uuid4())
    SESSION_DATA[session_id] = {
        "user_id": interaction.user.id,
        "coins": coins,
        "expires_at": datetime.now(timezone.utc) + timedelta(minutes=10)
    }

    # あなたのRailwayドメインに置き換えてください（デプロイ済のURL）
    slot_url = f"https://slot-production-be36.up.railway.app/?session={session_id}"
    
    await interaction.response.send_message(
        f"🎰 スロットゲームを開始します！\n[こちらからプレイ](<{slot_url}>)",
        ephemeral=True
    )

# --------------------------
# 起動
# --------------------------
if __name__ == "__main__":
    keep_alive()
    bot.run(os.environ["DISCORD_TOKEN"])
