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
import json
import logging
from typing import Optional, Dict, Any, List

# =========================================================
# 設定（既存：スロット）
# =========================================================
VIRTUALCRYPTO_ID = 800892182633381950
CASHOUT_CHANNEL_ID = 1401466622149005493  # 送金チャンネルID

# =========================================================
# 追加設定（VCガード）
# =========================================================
# コマンド即時反映したいギルド（必要に応じて複数可）
GUILD_IDS = [1398607685158440991]
# コマンド実行を許可するロール（管理者は常にOK）
ALLOWED_ROLE_ID = 1398724601256874014
# 保護ロールの初期値（起動後にコマンドで上書き推奨）
DEFAULT_PROTECTED_ROLE_ID = 111111111111111111  # ←必要なら初期値差し替え
# 設定ファイル
CONFIG_PATH = "config.json"

# =========================================================
# ログ
# =========================================================
logging.basicConfig(
    level=logging.INFO,
    format="(%(asctime)s) [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("slot_vc_guard")

# =========================================================
# Flask サーバーとセッション管理（既存：スロット）
# =========================================================
SESSION_DATA: Dict[str, Dict[str, Any]] = {}

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

    if data.get("used", False):
        return jsonify({
            "user_id": data["user_id"],
            "coins": 0,
            "used": True
        })

    # 初回アクセス：コイン返して使用済みにする
    data["used"] = True
    return jsonify({
        "user_id": data["user_id"],
        "coins": data["coins"],
        "used": False
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

# =========================================================
# 設定ロード/保存（VCガード）
# =========================================================
def load_config() -> Dict[str, Any]:
    data: Dict[str, Any] = {}
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError:
            data = {}

    changed = False
    if "protected_role_id" not in data:
        data["protected_role_id"] = DEFAULT_PROTECTED_ROLE_ID
        changed = True
    # targets: { user_id(str): {"f1": bool, "f2": bool} }
    if "targets" not in data:
        data["targets"] = {}
        changed = True

    if changed:
        save_config(data)
    return data

def save_config(data: Dict[str, Any]) -> None:
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

CONFIG = load_config()

# =========================================================
# Discord Bot 初期化（スロット＋VCガード）
# =========================================================
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True   # VCイベントに必須
intents.members = True        # ロール/メンバー情報に必須
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# ---- 権限チェック（管理者 or 指定ロール） ----
def has_access(member: discord.Member) -> bool:
    if member.guild_permissions.administrator:
        return True
    return any(r.id == ALLOWED_ROLE_ID for r in member.roles)

async def ensure_access(interaction: discord.Interaction) -> bool:
    if not isinstance(interaction.user, discord.Member):
        await interaction.response.send_message("サーバー内で実行してください。", ephemeral=True)
        return False
    if not has_access(interaction.user):
        await interaction.response.send_message("権限がありません。", ephemeral=True)
        return False
    return True

# =========================================================
# 既存：起動時
# =========================================================
@bot.event
async def on_ready():
    # ギルド限定同期（即反映）
    for gid in GUILD_IDS:
        try:
            await tree.sync(guild=discord.Object(id=gid))
            log.info(f"Slash commands synced to Guild {gid}")
        except Exception as e:
            log.warning(f"Failed to sync to Guild {gid}: {e}")

    # グローバル同期（必要なら）
    # await tree.sync()

    print(f"✅ Bot connected as {bot.user}")

# =========================================================
# 既存：/slot コマンド
# =========================================================
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
            "expires_at": datetime.now(timezone.utc) + timedelta(minutes=10),
            "used": False  # 初期状態は未使用
        }

        slot_url = f"https://slot-production-be36.up.railway.app/?session={session_id}"
        await interaction.followup.send(
            f"✅ 送金を確認しました！\n🎰 スロットはこちらからどうぞ:\n<{slot_url}>",
            ephemeral=True
        )

    except asyncio.TimeoutError:
        await interaction.followup.send("⏳ 時間内に送金が確認できませんでした。再度 `/slot` を実行してください。", ephemeral=True)

# =========================================================
# 既存：送金処理関数
# =========================================================
async def send_payout(user_id: int, coins: int):
    await bot.wait_until_ready()
    try:
        user = await bot.fetch_user(user_id)
        cashout_channel = bot.get_channel(CASHOUT_CHANNEL_ID)
        if not cashout_channel:
            print("❌ 送金チャンネルが見つかりません")
            return

        await cashout_channel.send(f"/pay Spt {user.mention} {coins}　清算処理")
        print(f"✅ /pay {user.mention} {coins} spt を送信しました")

    except Exception as e:
        print("❌ 送金失敗:", e)

# =========================================================
# 追加：VCガード ロジック
# =========================================================
def is_protected(member: discord.Member) -> bool:
    pr = CONFIG.get("protected_role_id")
    return any(r.id == pr for r in member.roles)

def is_target_user(user_id: int) -> bool:
    return str(user_id) in CONFIG["targets"]

def get_target_flags(user_id: int) -> Optional[Dict[str, bool]]:
    return CONFIG["targets"].get(str(user_id))

async def disconnect_member(m: discord.Member, reason: str):
    try:
        await m.move_to(None, reason=reason)
        log.info(f"Disconnected {m.id} -> {reason}")
    except discord.Forbidden:
        log.warning(f"Missing Move Members permission to disconnect {m.id}")
    except discord.HTTPException as e:
        log.warning(f"Failed to disconnect {m.id}: {e}")

async def enforce_on_join(member: discord.Member, channel: Optional[discord.VoiceChannel | discord.StageChannel]):
    """機能1：対象ユーザー（B）がAのいるVCへ参加/移動してきた場合に切断"""
    if channel is None:
        return
    flags = get_target_flags(member.id)
    if not flags or not flags.get("f1", False):
        return
    try:
        members = list(channel.members)
    except Exception:
        return
    # そのVCにAがいる？
    if any(is_protected(m) for m in members if m.id != member.id):
        await disconnect_member(member, "VC Guard F1: Protected user present")

async def enforce_on_protected_enter(channel: Optional[discord.VoiceChannel | discord.StageChannel]):
    """機能2：Aが入ってきたVCにいる対象ユーザー（B）を切断"""
    if channel is None:
        return
    try:
        members = list(channel.members)
    except Exception:
        return
    if not any(is_protected(m) for m in members):
        return
    for m in members:
        flags = get_target_flags(m.id)
        if flags and flags.get("f2", False):
            await disconnect_member(m, "VC Guard F2: Protected user entered")

@bot.event
async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
    # 参加/移動時のみチェック
    if after.channel and after.channel != before.channel:
        # 1) 対象ユーザー（B）が入った/移動してきた → 機能1適用
        if is_target_user(member.id):
            await enforce_on_join(member, after.channel)
        # 2) 保護対象（A）が入った/移動してきた → 機能2適用
        if is_protected(member):
            await enforce_on_protected_enter(after.channel)

# =========================================================
# 追加：スラッシュコマンド（VCガード設定）
# =========================================================
vc_guard = app_commands.Group(name="vc_guard", description="VCガード設定")
tree.add_command(vc_guard)

@vc_guard.command(name="show", description="現在の設定を表示")
async def vc_guard_show(interaction: discord.Interaction):
    if not await ensure_access(interaction):
        return
    pr = CONFIG.get("protected_role_id")
    count = len(CONFIG["targets"])
    await interaction.response.send_message(
        f"保護ロール（A）: `{pr}`\n対象ユーザー数: {count}",
        ephemeral=True
    )

@vc_guard.command(name="set_protected", description="保護対象（A）のロールIDを設定")
@app_commands.describe(role_id="ロールID（数値）")
async def vc_guard_set_protected(interaction: discord.Interaction, role_id: str):
    if not await ensure_access(interaction):
        return
    try:
        rid = int(role_id)
    except ValueError:
        await interaction.response.send_message("role_id は数値で指定してください。", ephemeral=True)
        return
    CONFIG["protected_role_id"] = rid
    save_config(CONFIG)
    await interaction.response.send_message(f"保護ロール（A）を `{rid}` に設定しました。", ephemeral=True)

target_group = app_commands.Group(name="target", description="対象ユーザー設定")
vc_guard.add_command(target_group)

@target_group.command(name="add", description="対象ユーザーを追加（f1/f2省略で両方ON）")
@app_commands.describe(user="対象ユーザー", f1="機能1を有効にするか", f2="機能2を有効にするか")
async def target_add(interaction: discord.Interaction, user: discord.Member, f1: Optional[bool] = None, f2: Optional[bool] = None):
    if not await ensure_access(interaction):
        return
    uid = str(user.id)
    f1_val = True if f1 is None else f1
    f2_val = True if f2 is None else f2
    CONFIG["targets"][uid] = {"f1": f1_val, "f2": f2_val}
    save_config(CONFIG)
    await interaction.response.send_message(
        f"追加しました：{user.mention}（ID: `{uid}`）\n- f1: {f1_val}\n- f2: {f2_val}",
        ephemeral=True
    )

@target_group.command(name="set", description="対象ユーザーの機能ON/OFFを更新（未指定の項目は変更しない）")
@app_commands.describe(user="対象ユーザー", f1="機能1の新設定（true/false/未指定）", f2="機能2の新設定（true/false/未指定）")
async def target_set(interaction: discord.Interaction, user: discord.Member, f1: Optional[bool] = None, f2: Optional[bool] = None):
    if not await ensure_access(interaction):
        return
    uid = str(user.id)
    if uid not in CONFIG["targets"]:
        await interaction.response.send_message("このユーザーは対象に登録されていません。まず /vc_guard target add を実行してください。", ephemeral=True)
        return
    if f1 is not None:
        CONFIG["targets"][uid]["f1"] = f1
    if f2 is not None:
        CONFIG["targets"][uid]["f2"] = f2
    save_config(CONFIG)
    vals = CONFIG["targets"][uid]
    await interaction.response.send_message(
        f"更新しました：{user.mention}（ID: `{uid}`）\n- f1: {vals['f1']}\n- f2: {vals['f2']}",
        ephemeral=True
    )

@target_group.command(name="remove", description="対象ユーザーを解除")
@app_commands.describe(user="対象ユーザー")
async def target_remove(interaction: discord.Interaction, user: discord.Member):
    if not await ensure_access(interaction):
        return
    uid = str(user.id)
    if uid in CONFIG["targets"]:
        CONFIG["targets"].pop(uid)
        save_config(CONFIG)
        await interaction.response.send_message(f"解除しました：{user.mention}（ID: `{uid}`）", ephemeral=True)
    else:
        await interaction.response.send_message("登録が見つかりませんでした。", ephemeral=True)

@target_group.command(name="show", description="対象ユーザーの設定を表示")
@app_commands.describe(user="対象ユーザー")
async def target_show(interaction: discord.Interaction, user: discord.Member):
    if not await ensure_access(interaction):
        return
    uid = str(user.id)
    flags = CONFIG["targets"].get(uid)
    if not flags:
        await interaction.response.send_message("このユーザーは対象に登録されていません。", ephemeral=True)
        return
    await interaction.response.send_message(
        f"{user.mention}（ID: `{uid}`）\n- f1: {flags['f1']}\n- f2: {flags['f2']}",
        ephemeral=True
    )

@target_group.command(name="list", description="対象ユーザー一覧（最大25件/ページ）")
@app_commands.describe(page="ページ番号（1始まり）")
async def target_list(interaction: discord.Interaction, page: Optional[int] = 1):
    if not await ensure_access(interaction):
        return
    page = max(1, page or 1)
    items = list(CONFIG["targets"].items())  # [(uid, {"f1":..,"f2":..}), ...]
    total = len(items)
    page_size = 25
    start = (page - 1) * page_size
    end = min(start + page_size, total)
    if start >= total:
        await interaction.response.send_message("指定ページに対象がありません。", ephemeral=True)
        return

    lines: List[str] = []
    for idx, (uid, flags) in enumerate(items[start:end], start=start+1):
        mention = f"<@{uid}>"
        lines.append(f"{idx}. {mention} / ID `{uid}` / f1={flags['f1']} / f2={flags['f2']}")
    await interaction.response.send_message(
        f"対象ユーザー一覧（{start+1}-{end}/{total}）\n" + "\n".join(lines),
        ephemeral=True
    )

# =========================================================
# 起動
# =========================================================
if __name__ == "__main__":
    keep_alive()
    bot.run(os.environ["DISCORD_TOKEN"])
