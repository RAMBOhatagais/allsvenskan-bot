import discord
from discord import app_commands
import sqlite3
import os
from datetime import datetime
from zoneinfo import ZoneInfo
import asyncio

TOKEN = os.getenv("TOKEN")

ALLSVENSKA_LAG = [
    "AIK","Degerfors","Djurgården","GAIS","Häcken","Halmstad","Hammarby",
    "Brommapojkarna","Elfsborg","Göteborg","Sirius","Kalmar","Malmö",
    "Mjällby","Örgryte","Västerås"
]

TABELL_DEADLINE = datetime(2026, 4, 1)

intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

conn = sqlite3.connect("tips.db", check_same_thread=False)
c = conn.cursor()

# ================= DATABAS =================

c.execute("CREATE TABLE IF NOT EXISTS matchtips(guild_id TEXT, user_id TEXT, tip TEXT)")
c.execute("CREATE TABLE IF NOT EXISTS points(guild_id TEXT, user_id TEXT, pts INTEGER)")
c.execute("CREATE TABLE IF NOT EXISTS tabell(guild_id TEXT, user_id TEXT, position INTEGER, team TEXT)")

c.execute("""
CREATE TABLE IF NOT EXISTS match_settings(
    guild_id TEXT PRIMARY KEY,
    is_open INTEGER
)
""")

# ================= AUTO MIGRATION =================

def column_exists(table, column):
    columns = c.execute(f"PRAGMA table_info({table})").fetchall()
    return any(col[1] == column for col in columns)

if not column_exists("match_settings", "deadline"):
    c.execute("ALTER TABLE match_settings ADD COLUMN deadline TEXT")

if not column_exists("match_settings", "round"):
    c.execute("ALTER TABLE match_settings ADD COLUMN round INTEGER")

if not column_exists("match_settings", "live_sent"):
    c.execute("ALTER TABLE match_settings ADD COLUMN live_sent INTEGER DEFAULT 0")

if not column_exists("match_settings", "channel_id"):
    c.execute("ALTER TABLE match_settings ADD COLUMN channel_id TEXT")

conn.commit()

# ================= POÄNG =================

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

# ================= BACKGROUND TASK =================

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

                # Lås match
                c.execute(
                    "UPDATE match_settings SET is_open=0 WHERE guild_id=?",
                    (guild_id,)
                )

                if live_sent == 0 and channel_id:
                    channel = client.get_channel(int(channel_id))
                    if channel:
                        await channel.send(
                            f"@everyone 🚨 **OMGÅNG {round_number} ÄR LIVE!!!**"
                        )

                    c.execute(
                        "UPDATE match_settings SET live_sent=1 WHERE guild_id=?",
                        (guild_id,)
                    )

                conn.commit()

        await asyncio.sleep(30)  # kollar var 30:e sekund

# ================= READY =================

@client.event
async def on_ready():
    await tree.sync()
    client.loop.create_task(deadline_checker())
    print("Bot ready")

# ================= ADMIN =================

@tree.command(name="set_match", description="Admin: sätt veckans match")
@app_commands.describe(
    match="Matchen (ex: Hammarby - Mjällby)",
    deadline="YYYY-MM-DD HH:MM (svensk tid)",
    round="Omgångsnummer (1-30)",
    text="Valfri hype-text"
)
async def set_match(
    interaction: discord.Interaction,
    match: str,
    deadline: str,
    round: int,
    text: str = None
):

    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("Endast admin.", ephemeral=True)
        return

    guild_id = str(interaction.guild.id)

    try:
        datetime.strptime(deadline, "%Y-%m-%d %H:%M")
    except:
        await interaction.response.send_message(
            "Fel format. Använd: YYYY-MM-DD HH:MM",
            ephemeral=True
        )
        return

    # Rensa gamla tips
    c.execute("DELETE FROM matchtips WHERE guild_id=?", (guild_id,))

    # Spara inställningar
    c.execute(
        "REPLACE INTO match_settings (guild_id, is_open, deadline, round, live_sent, channel_id) VALUES (?, ?, ?, ?, ?, ?)",
        (guild_id, 1, deadline, round, 0, str(interaction.channel.id))
    )

    conn.commit()

    message = "@everyone ⚽ **Ny omgång är satt!**\n\n"

    if text:
        message += f"{text}\n\n"

    message += f"**Veckans match:** {match}\n"
    message += f"⏳ Deadline: {deadline} (svensk tid)\n\n"
    message += "Tippa med `/tippa_match 1`, `/tippa_match X` eller `/tippa_match 2`"

    await interaction.response.send_message(message)

@tree.command(name="rapportera_resultat", description="Admin: rapportera 1/X/2")
async def rapportera(interaction: discord.Interaction, resultat: str):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("Endast admin.", ephemeral=True)
        return

    guild_id = str(interaction.guild.id)

    rows = c.execute(
        "SELECT user_id, tip FROM matchtips WHERE guild_id=?",
        (guild_id,)
    ).fetchall()

    winners = 0

    for user, tip in rows:
        if tip == resultat:
            add_points(guild_id, user, 3)
            winners += 1

    await interaction.response.send_message(f"{winners} fick 3 poäng!")

@tree.command(name="reset_points", description="Admin: nollställ poäng")
async def reset_points(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("Endast admin.", ephemeral=True)
        return

    guild_id = str(interaction.guild.id)
    c.execute("DELETE FROM points WHERE guild_id=?", (guild_id,))
    conn.commit()

    await interaction.response.send_message("Poäng resetade.")

# ================= MATCHTIP =================

@tree.command(name="tippa_match", description="Tippa 1/X/2")
async def tippa_match(interaction: discord.Interaction, tip: str):

    if tip not in ["1", "X", "2"]:
        await interaction.response.send_message("Ange 1 X eller 2", ephemeral=True)
        return

    guild_id = str(interaction.guild.id)
    user_id = str(interaction.user.id)

    status = c.execute(
        "SELECT is_open FROM match_settings WHERE guild_id=?",
        (guild_id,)
    ).fetchone()

    if not status or status[0] == 0:
        await interaction.response.send_message("Matchtips är stängda.", ephemeral=True)
        return

    c.execute(
        "DELETE FROM matchtips WHERE guild_id=? AND user_id=?",
        (guild_id, user_id)
    )

    c.execute(
        "INSERT INTO matchtips VALUES (?,?,?)",
        (guild_id, user_id, tip)
    )

    conn.commit()
    await interaction.response.send_message("Tips sparat!", ephemeral=True)

# ================= START =================

client.run(TOKEN)
