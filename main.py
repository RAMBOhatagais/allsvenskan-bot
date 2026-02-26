import discord
from discord import app_commands
import sqlite3
import os

TOKEN = os.getenv("TOKEN")

intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

conn = sqlite3.connect("tips.db")
c = conn.cursor()

c.execute("""CREATE TABLE IF NOT EXISTS tabell (
    user_id TEXT,
    position INTEGER,
    team TEXT
)""")

c.execute("""CREATE TABLE IF NOT EXISTS matchtips (
    user_id TEXT,
    omgang INTEGER,
    tip TEXT
)""")

c.execute("""CREATE TABLE IF NOT EXISTS poang (
    user_id TEXT,
    points INTEGER
)""")

conn.commit()

current_omgang = 1
tabell_open = True


@client.event
async def on_ready():
    await tree.sync()
    print("Bot is ready!")


@tree.command(name="tippa_tabell", description="Tippa sluttabellen")
async def tippa_tabell(interaction: discord.Interaction, tips: str):
    global tabell_open
    if not tabell_open:
        await interaction.response.send_message("Tabelltippningen är stängd.", ephemeral=True)
        return
    
    teams = tips.split(",")
    if len(teams) != 16:
        await interaction.response.send_message("Du måste ange 16 lag separerade med kommatecken.", ephemeral=True)
        return
    
    c.execute("DELETE FROM tabell WHERE user_id=?", (str(interaction.user.id),))
    for i, team in enumerate(teams):
        c.execute("INSERT INTO tabell VALUES (?, ?, ?)", (str(interaction.user.id), i+1, team.strip()))
    conn.commit()

    await interaction.response.send_message("Din tabelltippning är sparad!", ephemeral=True)


@tree.command(name="tippa_match", description="Tippa 1/X/2")
async def tippa_match(interaction: discord.Interaction, tip: str):
    if tip not in ["1", "X", "2"]:
        await interaction.response.send_message("Ange 1, X eller 2.", ephemeral=True)
        return
    
    c.execute("DELETE FROM matchtips WHERE user_id=? AND omgang=?", (str(interaction.user.id), current_omgang))
    c.execute("INSERT INTO matchtips VALUES (?, ?, ?)", (str(interaction.user.id), current_omgang, tip))
    conn.commit()

    await interaction.response.send_message(f"Ditt tips ({tip}) är sparat för omgång {current_omgang}!", ephemeral=True)


@tree.command(name="leaderboard", description="Visa poängställning")
async def leaderboard(interaction: discord.Interaction):
    c.execute("SELECT user_id, points FROM poang ORDER BY points DESC")
    rows = c.fetchall()

    if not rows:
        await interaction.response.send_message("Inga poäng ännu.")
        return
    
    message = "🏆 Leaderboard:\n"
    for row in rows:
        message += f"<@{row[0]}> - {row[1]} poäng\n"
    
    await interaction.response.send_message(message)


client.run(TOKEN)
