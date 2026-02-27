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
                        await channel.send("@everyone", embed=embed)

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

@app_commands.default_permissions(administrator=True)
@app_commands.checks.has_permissions(administrator=True)
@tree.command(name="set_match", description="Admin: sätt veckans match")
async def set_match(interaction: discord.Interaction, match: str, deadline: str, round: int):

    guild_id = str(interaction.guild.id)

    try:
        datetime.strptime(deadline, "%Y-%m-%d %H:%M")
    except:
        await interaction.response.send_message("Fel format YYYY-MM-DD HH:MM", ephemeral=True)
        return

    c.execute("DELETE FROM matchtips WHERE guild_id=?", (guild_id,))
    c.execute(
        "REPLACE INTO match_settings VALUES (?,?,?,?,?,?)",
        (guild_id, 1, deadline, round, 0, str(interaction.channel.id))
    )
    conn.commit()

    await interaction.response.send_message(
        f"@everyone ⚽ Omgång {round}\nMatch: {match}\nDeadline: {deadline} (svensk tid)"
    )

@app_commands.default_permissions(administrator=True)
@app_commands.checks.has_permissions(administrator=True)
@tree.command(name="rapportera_resultat", description="Admin: rapportera matchresultat")
async def rapportera_resultat(interaction: discord.Interaction, resultat: str):

    if resultat not in ["1", "X", "2"]:
        await interaction.response.send_message("Ange 1, X eller 2.", ephemeral=True)
        return

    guild_id = str(interaction.guild.id)

    rows = c.execute(
        "SELECT user_id, tip FROM matchtips WHERE guild_id=?",
        (guild_id,)
    ).fetchall()

    winners = 0

    for user_id, tip in rows:
        if tip == resultat:
            add_points(guild_id, user_id, 3)
            winners += 1

    c.execute("DELETE FROM matchtips WHERE guild_id=?", (guild_id,))
    conn.commit()

    await interaction.response.send_message(
        f"Resultat: {resultat}\n{winners} fick 3 poäng."
    )

@app_commands.default_permissions(administrator=True)
@app_commands.checks.has_permissions(administrator=True)
@tree.command(name="reset_points", description="Admin: nollställ ALLT")
async def reset_points(interaction: discord.Interaction):

    guild_id = str(interaction.guild.id)

    c.execute("DELETE FROM points WHERE guild_id=?", (guild_id,))
    c.execute("DELETE FROM matchtips WHERE guild_id=?", (guild_id,))
    c.execute("DELETE FROM tabell WHERE guild_id=?", (guild_id,))
    c.execute("DELETE FROM final_table WHERE guild_id=?", (guild_id,))
    c.execute("DELETE FROM match_settings WHERE guild_id=?", (guild_id,))
    conn.commit()

    await interaction.response.send_message("All data nollställd.")

@app_commands.default_permissions(administrator=True)
@app_commands.checks.has_permissions(administrator=True)
@tree.command(name="slut_tabell", description="Admin: mata in riktig sluttabell")
async def slut_tabell(interaction: discord.Interaction, tabell: str):

    guild_id = str(interaction.guild.id)
    teams = [t.strip() for t in tabell.split(",")]

    if len(teams) != 16 or len(set(teams)) != 16:
        await interaction.response.send_message("Du måste ange 16 unika lag.", ephemeral=True)
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

        points_to_add = 0

        for position, team in user_tips:
            real_position = c.execute(
                "SELECT position FROM final_table WHERE guild_id=? AND team=?",
                (guild_id, team)
            ).fetchone()

            if real_position and real_position[0] == position:
                points_to_add += 3

        if points_to_add > 0:
            add_points(guild_id, user_id, points_to_add)

    conn.commit()

    await interaction.response.send_message("Tabellpoäng tillagda.")

# ================= START =================

client.run(TOKEN)
