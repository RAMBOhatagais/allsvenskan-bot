import discord
from discord import app_commands
import sqlite3
import os
from datetime import datetime
import time

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

# ================= READY =================

@client.event
async def on_ready():
    await tree.sync()
    print("Bot ready")

# ================= ADMIN =================

@tree.command(name="set_match", description="Admin: sätt veckans match")
@app_commands.describe(
    match="Matchen (ex: Hammarby - Mjällby)",
    deadline="YYYY-MM-DD HH:MM",
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
        "REPLACE INTO match_settings (guild_id, is_open, deadline, round, live_sent) VALUES (?, ?, ?, ?, ?)",
        (guild_id, 1, deadline, round, 0)
    )

    conn.commit()

    message = "@everyone ⚽ **Ny omgång är satt!**\n\n"

    if text:
        message += f"{text}\n\n"

    message += f"**Veckans match:** {match}\n"
    message += f"⏳ Deadline: {deadline}\n\n"
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
        "SELECT is_open, deadline, round, live_sent FROM match_settings WHERE guild_id=?",
        (guild_id,)
    ).fetchone()

    if not status:
        await interaction.response.send_message("Ingen match är satt.", ephemeral=True)
        return

    is_open, deadline_str, round_number, live_sent = status
    deadline_dt = datetime.strptime(deadline_str, "%Y-%m-%d %H:%M")

    # Deadline passerad
    if datetime.now() >= deadline_dt:

        c.execute(
            "UPDATE match_settings SET is_open=0 WHERE guild_id=?",
            (guild_id,)
        )

        # Skicka LIVE-meddelande en gång
        if live_sent == 0:
            await interaction.channel.send(
                f"@everyone 🚨 **OMGÅNG {round_number} ÄR LIVE!!!**"
            )

            c.execute(
                "UPDATE match_settings SET live_sent=1 WHERE guild_id=?",
                (guild_id,)
            )

        conn.commit()

        await interaction.response.send_message(
            "Deadline har passerat. Matchtips är stängda.",
            ephemeral=True
        )
        return

    if is_open == 0:
        await interaction.response.send_message(
            "Matchtips är stängda.",
            ephemeral=True
        )
        return

    # Spara tips
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

# ================= TABELL =================

@tree.command(name="tippa_tabell", description="Tippa sluttabell")
async def tippa_tabell(interaction: discord.Interaction, tips: str):

    if datetime.now() > TABELL_DEADLINE:
        await interaction.response.send_message("Tabelltips stängda.", ephemeral=True)
        return

    guild_id = str(interaction.guild.id)
    user_id = str(interaction.user.id)

    existing = c.execute(
        "SELECT * FROM tabell WHERE guild_id=? AND user_id=?",
        (guild_id, user_id)
    ).fetchone()

    if existing:
        await interaction.response.send_message("Du har redan tippat.", ephemeral=True)
        return

    teams = [t.strip() for t in tips.split(",")]

    if len(teams) != 16 or len(set(teams)) != 16:
        await interaction.response.send_message("Fel antal lag eller dubletter.", ephemeral=True)
        return

    for lag in teams:
        if lag not in ALLSVENSKA_LAG:
            await interaction.response.send_message(f"{lag} är inte giltigt lag.", ephemeral=True)
            return

    for i, t in enumerate(teams):
        c.execute(
            "INSERT INTO tabell VALUES (?,?,?,?)",
            (guild_id, user_id, i + 1, t)
        )

    conn.commit()
    await interaction.response.send_message("Tabelltips låst!", ephemeral=True)

# ================= LEADERBOARD =================

@tree.command(name="leaderboard", description="Poäng")
async def leaderboard(interaction: discord.Interaction):

    guild_id = str(interaction.guild.id)

    rows = c.execute(
        "SELECT user_id, pts FROM points WHERE guild_id=? ORDER BY pts DESC",
        (guild_id,)
    ).fetchall()

    if not rows:
        await interaction.response.send_message("Inga poäng ännu.")
        return

    msg = "🏆 Leaderboard\n"
    for u, p in rows:
        msg += f"<@{u}> - {p}p\n"

    await interaction.response.send_message(msg)

# ================= START =================

client.run(TOKEN)

while True:
    time.sleep(3600)
