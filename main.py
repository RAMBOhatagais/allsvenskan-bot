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

TABELL_DEADLINE = datetime(2026, 3, 28)

intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

conn = sqlite3.connect("tips.db")
c = conn.cursor()

# =========================
# TABELLER PER SERVER
# =========================
c.execute("CREATE TABLE IF NOT EXISTS matchtips(guild_id TEXT, user_id TEXT, tip TEXT)")
c.execute("CREATE TABLE IF NOT EXISTS points(guild_id TEXT, user_id TEXT, pts INTEGER)")
c.execute("CREATE TABLE IF NOT EXISTS tabell(guild_id TEXT, user_id TEXT, position INTEGER, team TEXT)")
conn.commit()

current_match = None


# =========================
# POÄNG PER SERVER
# =========================
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


@client.event
async def on_ready():
    await tree.sync()
    print("Bot ready")


# =========================
# ADMIN: SÄTT MATCH
# =========================
@tree.command(name="set_match", description="Admin: sätt veckans match")
async def set_match(interaction: discord.Interaction, match: str):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("Endast admin.", ephemeral=True)
        return

    global current_match
    current_match = match

    c.execute(
        "DELETE FROM matchtips WHERE guild_id=?",
        (str(interaction.guild.id),)
    )
    conn.commit()

    await interaction.response.send_message(f"Ny match: {match}")


# =========================
# ADMIN: RAPPORTERA RESULTAT
# =========================
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


# =========================
# TIPPA MATCH
# =========================
@tree.command(name="tippa_match", description="Tippa 1/X/2")
async def tippa_match(interaction: discord.Interaction, tip: str):
    if tip not in ["1", "X", "2"]:
        await interaction.response.send_message("Ange 1 X eller 2", ephemeral=True)
        return

    guild_id = str(interaction.guild.id)
    user_id = str(interaction.user.id)

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


# =========================
# TIPPA TABELL
# =========================
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

    if len(teams) != 16:
        await interaction.response.send_message("Du måste ange 16 lag.", ephemeral=True)
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


# =========================
# LEADERBOARD
# =========================
@tree.command(name="leaderboard", description="Poäng")
async def leaderboard(interaction: discord.Interaction):

    rows = c.execute(
        "SELECT user_id, pts FROM points WHERE guild_id=? ORDER BY pts DESC",
        (str(interaction.guild.id),)
    ).fetchall()

    if not rows:
        await interaction.response.send_message("Inga poäng ännu.")
        return

    msg = "🏆 Leaderboard\n"
    for u, p in rows:
        msg += f"<@{u}> - {p}p\n"

    await interaction.response.send_message(msg)


# =========================
# ADMIN: RESET POÄNG (SERVER)
# =========================
@tree.command(name="reset_poäng", description="Admin: nollställ poäng i denna server")
async def reset_poang(interaction: discord.Interaction):

    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("Endast admin.", ephemeral=True)
        return

    c.execute(
        "DELETE FROM points WHERE guild_id=?",
        (str(interaction.guild.id),)
    )
    conn.commit()

    await interaction.response.send_message("Poängen är nollställda i denna server.")


# =========================
# ADMIN: RESET ALLT (SERVER)
# =========================
@tree.command(name="reset_allt", description="Admin: nollställ allt i denna server")
async def reset_allt(interaction: discord.Interaction):

    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("Endast admin.", ephemeral=True)
        return

    guild_id = str(interaction.guild.id)

    c.execute("DELETE FROM points WHERE guild_id=?", (guild_id,))
    c.execute("DELETE FROM matchtips WHERE guild_id=?", (guild_id,))
    c.execute("DELETE FROM tabell WHERE guild_id=?", (guild_id,))
    conn.commit()

    await interaction.response.send_message("Allt är nu nollställt i denna server.")


# =========================
# START BOT (RAILWAY)
# =========================
client.run(TOKEN)

# håller containern igång på Railway
while True:
    time.sleep(3600)
