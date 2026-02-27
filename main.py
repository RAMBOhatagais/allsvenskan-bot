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
intents.members = True

client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

conn = sqlite3.connect("tips.db", check_same_thread=False)
c = conn.cursor()

# ===== DATABASE =====
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

# ===== CHANNEL CHECK =====
def correct_channel(interaction: discord.Interaction):
    guild_id = str(interaction.guild.id)
    row = c.execute(
        "SELECT channel_id FROM match_settings WHERE guild_id=?",
        (guild_id,)
    ).fetchone()

    if not row:
        return True  # om ingen kanal är satt än

    return str(interaction.channel.id) == row[0]

# ===== POINT SYSTEM =====
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

# ===== READY =====
@client.event
async def on_ready():
    await tree.sync()
    print("Global commands synced")
    print("Bot ready")

# ===== ADMIN =====

@app_commands.checks.has_permissions(administrator=True)
@tree.command(name="set_tipskanal", description="Admin: sätt kanal för boten")
async def set_tipskanal(interaction: discord.Interaction):

    guild_id = str(interaction.guild.id)

    c.execute("""
        INSERT INTO match_settings (guild_id, channel_id)
        VALUES (?,?)
        ON CONFLICT(guild_id) DO UPDATE SET channel_id=excluded.channel_id
    """, (guild_id, str(interaction.channel.id)))

    conn.commit()

    await interaction.response.send_message(
        "✅ Denna kanal är nu botens officiella tipskanal."
    )

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
        f"@everyone ⚽ Omgång {round}\nMatch: {match}\nDeadline: {deadline}"
    )

@app_commands.checks.has_permissions(administrator=True)
@tree.command(name="rapportera_resultat", description="Admin: rapportera matchresultat")
async def rapportera_resultat(interaction: discord.Interaction, resultat: str):

    if not correct_channel(interaction):
        return

    if resultat not in ["1","X","2"]:
        return

    guild_id = str(interaction.guild.id)

    rows = c.execute(
        "SELECT user_id, tip FROM matchtips WHERE guild_id=?",
        (guild_id,)
    ).fetchall()

    for user_id, tip in rows:
        if tip == resultat:
            add_points(guild_id, user_id, 3)

    c.execute("DELETE FROM matchtips WHERE guild_id=?", (guild_id,))
    conn.commit()

    await interaction.response.send_message("Resultat registrerat.")

@app_commands.checks.has_permissions(administrator=True)
@tree.command(name="reset_points", description="Admin: nollställ ALLT")
async def reset_points(interaction: discord.Interaction):

    if not correct_channel(interaction):
        return

    guild_id = str(interaction.guild.id)

    c.execute("DELETE FROM points WHERE guild_id=?", (guild_id,))
    c.execute("DELETE FROM matchtips WHERE guild_id=?", (guild_id,))
    c.execute("DELETE FROM tabell WHERE guild_id=?", (guild_id,))
    c.execute("DELETE FROM final_table WHERE guild_id=?", (guild_id,))
    conn.commit()

    await interaction.response.send_message("All data nollställd.")

@app_commands.checks.has_permissions(administrator=True)
@tree.command(name="slut_tabell", description="Admin: mata in riktig sluttabell")
async def slut_tabell(interaction: discord.Interaction, tabell: str):

    if not correct_channel(interaction):
        return

    guild_id = str(interaction.guild.id)
    teams = [t.strip() for t in tabell.split(",")]

    if len(teams) != 16:
        return

    c.execute("DELETE FROM final_table WHERE guild_id=?", (guild_id,))
    for i, team in enumerate(teams):
        c.execute("INSERT INTO final_table VALUES (?,?,?)", (guild_id, i+1, team))

    users = c.execute(
        "SELECT DISTINCT user_id FROM tabell WHERE guild_id=?",
        (guild_id,)
    ).fetchall()

    for (user_id,) in users:
        user_tips = c.execute(
            "SELECT position, team FROM tabell WHERE guild_id=? AND user_id=?",
            (guild_id, user_id)
        ).fetchall()

        for position, team in user_tips:
            real = c.execute(
                "SELECT position FROM final_table WHERE guild_id=? AND team=?",
                (guild_id, team)
            ).fetchone()

            if real and real[0] == position:
                add_points(guild_id, user_id, 3)

    conn.commit()
    await interaction.response.send_message("Tabellpoäng tillagda.")

# ===== USER =====

@tree.command(name="tippa_match", description="Tippa 1/X/2")
async def tippa_match(interaction: discord.Interaction, tip: str):

    if not correct_channel(interaction):
        return

    if tip not in ["1","X","2"]:
        return

    guild_id = str(interaction.guild.id)
    user_id = str(interaction.user.id)

    c.execute("DELETE FROM matchtips WHERE guild_id=? AND user_id=?", (guild_id,user_id))
    c.execute("INSERT INTO matchtips VALUES (?,?,?)", (guild_id,user_id,tip))
    conn.commit()

    await interaction.response.send_message("Tips sparat!", ephemeral=True)

@tree.command(name="tippa_tabell", description="Tippa sluttabell")
async def tippa_tabell(interaction: discord.Interaction, tips: str):

    if not correct_channel(interaction):
        return

    if datetime.now() > TABELL_DEADLINE:
        return

    guild_id = str(interaction.guild.id)
    user_id = str(interaction.user.id)

    teams = [t.strip() for t in tips.split(",")]
    if len(teams) != 16:
        return

    c.execute("DELETE FROM tabell WHERE guild_id=? AND user_id=?", (guild_id,user_id))

    for i, team in enumerate(teams):
        c.execute("INSERT INTO tabell VALUES (?,?,?,?)", (guild_id,user_id,i+1,team))

    conn.commit()
    await interaction.response.send_message("Tabelltips sparat!", ephemeral=True)

@tree.command(name="leaderboard", description="Topp 20")
async def leaderboard(interaction: discord.Interaction):

    if not correct_channel(interaction):
        return

    guild_id = str(interaction.guild.id)

    rows = c.execute(
        "SELECT user_id, pts FROM points WHERE guild_id=? ORDER BY pts DESC LIMIT 20",
        (guild_id,)
    ).fetchall()

    if not rows:
        return

    msg = "🏆 Leaderboard\n\n"

    for i,(user_id,pts) in enumerate(rows):
        member = interaction.guild.get_member(int(user_id))
        name = member.display_name if member else f"<@{user_id}>"
        msg += f"{i+1}. {name} - {pts}p\n"

    await interaction.response.send_message(msg)

@tree.command(name="placering", description="Se din placering")
async def placering(interaction: discord.Interaction):

    if not correct_channel(interaction):
        return

    guild_id = str(interaction.guild.id)
    user_id = str(interaction.user.id)

    rows = c.execute(
        "SELECT user_id, pts FROM points WHERE guild_id=? ORDER BY pts DESC",
        (guild_id,)
    ).fetchall()

    for index,(uid,pts) in enumerate(rows):
        if uid == user_id:
            await interaction.response.send_message(
                f"Din placering: {index+1}/{len(rows)}\nPoäng: {pts}",
                ephemeral=True
            )
            return

# ===== START =====
client.run(TOKEN)
