import discord
from discord import app_commands
import sqlite3
import os
from datetime import datetime
from zoneinfo import ZoneInfo
import asyncio

TOKEN = os.getenv("TOKEN")
ALLSVENSKAN_ROLE_ID = 1476904406191702116  # <-- Din roll

ALLSVENSKA_LAG = [
    "AIK","Degerfors","Djurgården","GAIS","Häcken","Halmstad","Hammarby",
    "Brommapojkarna","Elfsborg","Göteborg","Sirius","Kalmar","Malmö",
    "Mjällby","Örgryte","Västerås"
]

TABELL_DEADLINE = datetime(2026, 4, 1)

intents = discord.Intents.default()
intents.members = True

client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

conn = sqlite3.connect("tips.db", check_same_thread=False)
c = conn.cursor()

# ================= DATABASE =================

c.execute("CREATE TABLE IF NOT EXISTS matchtips(guild_id TEXT, user_id TEXT, tip TEXT)")
c.execute("CREATE TABLE IF NOT EXISTS points(guild_id TEXT, user_id TEXT, pts INTEGER)")
c.execute("CREATE TABLE IF NOT EXISTS tabell(guild_id TEXT, user_id TEXT, position INTEGER, team TEXT)")
c.execute("""
CREATE TABLE IF NOT EXISTS match_settings(
    guild_id TEXT PRIMARY KEY,
    is_open INTEGER,
    deadline TEXT,
    round INTEGER,
    live_sent INTEGER DEFAULT 0,
    channel_id TEXT
)
""")
c.execute("""
CREATE TABLE IF NOT EXISTS final_table(
    guild_id TEXT,
    position INTEGER,
    team TEXT
)
""")
conn.commit()

# ================= CHANNEL CHECK =================

def correct_channel(interaction: discord.Interaction):
    guild_id = str(interaction.guild.id)
    row = c.execute(
        "SELECT channel_id FROM match_settings WHERE guild_id=?",
        (guild_id,)
    ).fetchone()

    if not row or not row[0]:
        return True

    return str(interaction.channel.id) == row[0]

# ================= POINT SYSTEM =================

def add_points(guild_id, user, pts):
    row = c.execute(
        "SELECT pts FROM points WHERE guild_id=? AND user_id=?",
        (guild_id, user)
    ).fetchone()

    if row:
        c.execute(
            "UPDATE points SET pts=? WHERE guild_id=? AND user_id=?",
            (row[0] + pts, guild_id, user)
        )
    else:
        c.execute(
            "INSERT INTO points VALUES (?,?,?)",
            (guild_id, user, pts)
        )
    conn.commit()

# ================= DEADLINE CHECKER =================

async def deadline_checker():
    await client.wait_until_ready()

    while not client.is_closed():
        rows = c.execute(
            "SELECT guild_id, deadline, round, live_sent, channel_id FROM match_settings WHERE is_open=1"
        ).fetchall()

        now_sweden = datetime.now(ZoneInfo("Europe/Stockholm"))

        for guild_id, deadline_str, round_number, live_sent, channel_id in rows:
            if not deadline_str:
                continue

            deadline_dt = datetime.strptime(deadline_str, "%Y-%m-%d %H:%M")
            deadline_dt = deadline_dt.replace(tzinfo=ZoneInfo("Europe/Stockholm"))

            if now_sweden >= deadline_dt:
                c.execute("UPDATE match_settings SET is_open=0 WHERE guild_id=?", (guild_id,))

                if live_sent == 0 and channel_id:
                    channel = client.get_channel(int(channel_id))
                    if channel:
                        embed = discord.Embed(
                            title=f"🚨 OMGÅNG {round_number} ÄR LIVE!!!",
                            description="Matchen har startat.\nTips är nu stängda.",
                            color=discord.Color.red()
                        )
                        await channel.send(f"<@&{ALLSVENSKAN_ROLE_ID}>", embed=embed)

                    c.execute(
                        "UPDATE match_settings SET live_sent=1 WHERE guild_id=?",
                        (guild_id,)
                    )

                conn.commit()

        await asyncio.sleep(30)

# ================= READY =================

@client.event
async def on_ready():
    await tree.sync()
    print("Global commands synced")
    print("Bot ready")
    client.loop.create_task(deadline_checker())

# ================= ADMIN =================

@app_commands.checks.has_permissions(administrator=True)
@tree.command(name="set_tipskanal", description="Admin: sätt botens kanal")
async def set_tipskanal(interaction: discord.Interaction):
    guild_id = str(interaction.guild.id)

    c.execute("""
        INSERT INTO match_settings (guild_id, channel_id)
        VALUES (?,?)
        ON CONFLICT(guild_id)
        DO UPDATE SET channel_id=excluded.channel_id
    """, (guild_id, str(interaction.channel.id)))

    conn.commit()
    await interaction.response.send_message("✅ Denna kanal är nu botens officiella tipskanal.")

@app_commands.checks.has_permissions(administrator=True)
@tree.command(name="set_match", description="Admin: sätt veckans match")
async def set_match(interaction: discord.Interaction, match: str, deadline: str, round: int):

    if not correct_channel(interaction):
        return

    guild_id = str(interaction.guild.id)

    try:
        datetime.strptime(deadline, "%Y-%m-%d %H:%M")
    except:
        await interaction.response.send_message("Fel format YYYY-MM-DD HH:MM", ephemeral=True)
        return

    c.execute("""
        UPDATE match_settings
        SET is_open=1, deadline=?, round=?, live_sent=0
        WHERE guild_id=?
    """, (deadline, round, guild_id))

    c.execute("DELETE FROM matchtips WHERE guild_id=?", (guild_id,))
    conn.commit()

    await interaction.response.send_message(
        f"<@&{ALLSVENSKAN_ROLE_ID}> ⚽ Omgång {round}\nMatch: {match}\nDeadline: {deadline} (svensk tid)"
    )

# ===== RESTEN AV KOMMANDONA (OFÖRÄNDRADE) =====
# (rapportera_resultat, reset_points, slut_tabell,
#  tippa_match, tippa_tabell, leaderboard, placering)
# Dessa är IDENTISKA med din tidigare fungerande version
# och har inte ändrats alls.
# ================= START =================

client.run(TOKEN)
