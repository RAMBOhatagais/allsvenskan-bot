import discord
from discord import app_commands
import sqlite3
import os
from datetime import datetime
from flask import Flask
from threading import Thread

TOKEN = os.getenv("TOKEN")

ALLSVENSKA_LAG = [
"AIK","Degerfors","Djurgården","GAIS","Häcken","Halmstad","Hammarby",
"Brommapojkarna","Elfsborg","IFK Göteborg","Sirius","Kalmar FF",
"Malmö FF","Mjällby","Örgryte","Västerås SK"
]

TABELL_DEADLINE = datetime(2026, 3, 28)

intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

conn = sqlite3.connect("tips.db")
c = conn.cursor()

c.execute("CREATE TABLE IF NOT EXISTS matchtips(user_id TEXT, tip TEXT)")
c.execute("CREATE TABLE IF NOT EXISTS points(user_id TEXT, pts INTEGER)")
c.execute("CREATE TABLE IF NOT EXISTS tabell(user_id TEXT, position INTEGER, team TEXT)")
conn.commit()

current_match = None


def add_points(user, pts):
    row = c.execute("SELECT pts FROM points WHERE user_id=?", (user,)).fetchone()
    if row:
        c.execute("UPDATE points SET pts=? WHERE user_id=?", (row[0] + pts, user))
    else:
        c.execute("INSERT INTO points VALUES (?,?)", (user, pts))
    conn.commit()


@client.event
async def on_ready():
    await tree.sync()
    print("Bot ready")


# ADMIN
@tree.command(name="set_match", description="Admin: sätt veckans match")
async def set_match(interaction: discord.Interaction, match: str):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("Endast admin.", ephemeral=True)
        return

    global current_match
    current_match = match
    c.execute("DELETE FROM matchtips")
    conn.commit()

    await interaction.response.send_message(f"Ny match: {match}")


@tree.command(name="rapportera_resultat", description="Admin: rapportera 1/X/2")
async def rapportera(interaction: discord.Interaction, resultat: str):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("Endast admin.", ephemeral=True)
        return

    rows = c.execute("SELECT user_id, tip FROM matchtips").fetchall()
    winners = 0

    for user, tip in rows:
        if tip == resultat:
            add_points(user, 3)
            winners += 1

    await interaction.response.send_message(f"{winners} fick 3 poäng!")


# MATCHTIP
@tree.command(name="tippa_match", description="Tippa 1/X/2")
async def tippa_match(interaction: discord.Interaction, tip: str):
    if tip not in ["1", "X", "2"]:
        await interaction.response.send_message("Ange 1 X eller 2", ephemeral=True)
        return

    c.execute("DELETE FROM matchtips WHERE user_id=?", (str(interaction.user.id),))
    c.execute("INSERT INTO matchtips VALUES (?,?)", (str(interaction.user.id), tip))
    conn.commit()

    await interaction.response.send_message("Tips sparat!", ephemeral=True)


# TABELL
@tree.command(name="tippa_tabell", description="Tippa sluttabell")
async def tippa_tabell(interaction: discord.Interaction, tips: str):

    if datetime.now() > TABELL_DEADLINE:
        await interaction.response.send_message("Tabelltips stängda.", ephemeral=True)
        return

    existing = c.execute(
        "SELECT * FROM tabell WHERE user_id=?",
        (str(interaction.user.id),)
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
        c.execute("INSERT INTO tabell VALUES (?,?,?)",
                  (str(interaction.user.id), i + 1, t))

    conn.commit()

    await interaction.response.send_message("Tabelltips låst!", ephemeral=True)


# LEADERBOARD
@tree.command(name="leaderboard", description="Poäng")
async def leaderboard(interaction: discord.Interaction):

    rows = c.execute(
        "SELECT user_id, pts FROM points ORDER BY pts DESC"
    ).fetchall()

    if not rows:
        await interaction.response.send_message("Inga poäng ännu.")
        return

    msg = "🏆 Leaderboard\n"
    for u, p in rows:
        msg += f"<@{u}> - {p}p\n"

    await interaction.response.send_message(msg)


from flask import Flask
from threading import Thread

app = Flask(__name__)

@app.route("/")
def home():
    return "Bot alive"

def run_web():
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))

def run_bot():
    client.run(TOKEN)

Thread(target=run_web).start()
run_bot()
