import discord
from discord.ext import commands
from discord import app_commands
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from threading import Thread
from datetime import datetime, timedelta, timezone
import uuid
import os
import asyncio

VIRTUALCRYPTO_ID = 800892182633381950

# --------------------------
# Flask サーバーとセッション管理
# --------------------------
SESSION_DATA = {}

app = Flask(__name__, static_folder='public')
CORS(app)

@app.route('/')
def serve_index():
    return send_from_directory('public', 'index.html')

@app.route('/<path:path>')
def serve_file(path):
    return send_from_directory('public', path)

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
# Discord Bot 初期化
# --------------------------
intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"Bot connected as {bot.user}")

# --------------------------
# /slot コマンド（送金確認付き）
# --------------------------
@bot.tree.command(name="slot", description="スロットゲームを開始します")
@app_commands.describe(coins="初期コイン数（例：1000）")
async def slot(interaction: discord.Interaction, coins: int):
    if coins <= 0:
        await interaction.response.send_message("コイン数は1以上にしてください。", ephemeral=True)
        return

    await interaction.response.send_message(
        f"💰 まず `{coins}Spt` を VirtualCrypto Bot 経由で「ベル」宛に送金してください。\n"
        f"制限時間：**3分以内**に送金が確認されるとスロットURLを配布します。",
        ephemeral=True
    )

    def check(msg: discord.Message):
        description = msg.embeds[0].description if msg.embeds else ""
        print("受信（embed）:", repr(description))
        return (
        msg.author.id == VIRTUALCRYPTO_ID and
        f"<@{interaction.user.id}>から<@{bot.user.id}>へ" in description and
        f"{coins}" in description and
        "Spt" in description
    )
    try:
        msg = await bot.wait_for("message", timeout=180, check=check)

        session_id = str(uuid.uuid4())
        SESSION_DATA[session_id] = {
            "user_id": interaction.user.id,
            "coins": coins,
            "expires_at": datetime.now(timezone.utc) + timedelta(minutes=10)
        }

        slot_url = f"https://bo4-production.up.railway.app/?session={session_id}"
        await interaction.followup.send(
            f"✅ 送金を確認しました！\n🎰 スロットはこちらからどうぞ:\n<{slot_url}>",
            ephemeral=True
        )
    except asyncio.TimeoutError:
        await interaction.followup.send("⏳ 時間内に送金が確認できませんでした。再度 `/slot` を実行してください。", ephemeral=True)

# --------------------------
# 起動
# --------------------------
if __name__ == "__main__":
    keep_alive()
    bot.run(os.environ["DISCORD_TOKEN"])




