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

# --------------------------
# 設定
# --------------------------
VIRTUALCRYPTO_ID = 800892182633381950
CASHOUT_CHANNEL_ID = 1401258844180451489  # 送金チャンネルID

# --------------------------
# Flask サーバーとセッション管理
# --------------------------
SESSION_DATA = {}

app = Flask(__name__, static_folder='public')
CORS(app)

@app.route('/')
def serve_index_any_query():
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

@app.route('/api/cashout', methods=["POST"])
def cashout():
    data = request.get_json()
    session_id = data.get("session")
    coins = data.get("coins")

    if not session_id or session_id not in SESSION_DATA:
        return jsonify({"error": "Invalid session"}), 400

    user_id = SESSION_DATA[session_id]["user_id"]
    SESSION_DATA[session_id]["cashout"] = {
        "coins": coins,
        "timestamp": datetime.now(timezone.utc)
    }

    print(f"[INFO] 清算要求: user={user_id}, coins={coins}")
    try:
        # 非同期送金処理を bot.loop に投げる
        asyncio.run_coroutine_threadsafe(
            send_payout(user_id, coins),
            bot.loop
        )
    except Exception as e:
        print("❌ 清算エラー:", e)
        return jsonify({"error": "Failed to send payout"}), 500

    return jsonify({"status": "ok"})

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
    print(f"✅ Bot connected as {bot.user}")

# --------------------------
# /slot コマンド
# --------------------------
@bot.tree.command(name="slot", description="スロットゲームを開始します")
@app_commands.describe(coins="初期コイン数（例：1000）")
async def slot(interaction: discord.Interaction, coins: int):
    if coins <= 0:
        await interaction.response.send_message("コイン数は1以上にしてください。", ephemeral=True)
        return

    await interaction.response.send_message(
        f"💰 `{coins}Spt` を VirtualCrypto 経由で「ベル」宛に送金してください。\n"
        f"制限時間：**3分以内**に送金が確認されるとスロットURLを発行します。",
        ephemeral=True
    )

    def check(msg: discord.Message):
        description = msg.embeds[0].description if msg.embeds else ""
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

        slot_url = f"https://slot-production-be36.up.railway.app/?session={session_id}"
        await interaction.followup.send(
            f"✅ 送金を確認しました！\n🎰 スロットはこちらからどうぞ:\n<{slot_url}>",
            ephemeral=True
        )

    except asyncio.TimeoutError:
        await interaction.followup.send("⏳ 時間内に送金が確認できませんでした。再度 `/slot` を実行してください。", ephemeral=True)

# --------------------------
# 送金処理関数
# --------------------------
async def send_payout(user_id: int, coins: int):
    await bot.wait_until_ready()
    try:
        user = await bot.fetch_user(user_id)
        cashout_channel = bot.get_channel(CASHOUT_CHANNEL_ID)
        if not cashout_channel:
            print("❌ 送金チャンネルが見つかりません")
            return

        await cashout_channel.send(f"/pay Spt {user.mention} {coins}")
        print(f"✅ /pay {user.mention} {coins} spt を送信しました")

    except Exception as e:
        print("❌ 送金失敗:", e)

# --------------------------
# 起動
# --------------------------
if __name__ == "__main__":
    keep_alive()
    bot.run(os.environ["DISCORD_TOKEN"])



