import discord
from discord.ext import commands
from discord import app_commands
import uuid
from datetime import datetime, timedelta
from keep_alive import keep_alive, SESSION_DATA  # FlaskからSESSION_DATAを共有
import os

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    bot.add_view(JoinView(None))
    bot.add_view(PokerJoinView(None))
    
    # 特定ギルド用
    await bot.tree.sync(guild=discord.Object(id=1398607685158440991))
    
    # グローバルにも同期（/slot など）
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
        "expires_at": datetime.utcnow() + timedelta(minutes=10)
    }

    slot_url = f"https://your-slot-domain.com/?session={session_id}"
    await interaction.response.send_message(f"🎰 スロットゲームを開始します！\n[こちらからプレイ](<{slot_url}>)", ephemeral=True)

keep_alive()
bot.run(os.environ["DISCORD_TOKEN"])

