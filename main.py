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

@tree.command(name="set_match", description="Admin: sätt veckans match")
async def set_match(interaction: discord.Interaction, match: str, deadline: str, round: int):

    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("Endast admin.", ephemeral=True)
        return

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

@tree.command(name="rapportera_resultat", description="Admin: rapportera matchresultat")
async def rapportera_resultat(interaction: discord.Interaction, resultat: str):

    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("Endast admin.", ephemeral=True)
        return

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

@tree.command(name="reset_points", description="Admin: nollställ ALLT")
async def reset_points(interaction: discord.Interaction):

    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("Endast admin.", ephemeral=True)
        return

    guild_id = str(interaction.guild.id)

    c.execute("DELETE FROM points WHERE guild_id=?", (guild_id,))
    c.execute("DELETE FROM matchtips WHERE guild_id=?", (guild_id,))
    c.execute("DELETE FROM tabell WHERE guild_id=?", (guild_id,))
    c.execute("DELETE FROM final_table WHERE guild_id=?", (guild_id,))
    c.execute("DELETE FROM match_settings WHERE guild_id=?", (guild_id,))

    conn.commit()

    await interaction.response.send_message("All data nollställd.")

@tree.command(name="slut_tabell", description="Admin: mata in riktig sluttabell")
async def slut_tabell(interaction: discord.Interaction, tabell: str):

    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("Endast admin.", ephemeral=True)
        return

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

# ================= TIPS =================

@tree.command(name="tippa_match", description="Tippa 1/X/2")
async def tippa_match(interaction: discord.Interaction, tip: str):

    if tip not in ["1", "X", "2"]:
        await interaction.response.send_message("Ange 1, X eller 2.", ephemeral=True)
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

    c.execute("DELETE FROM matchtips WHERE guild_id=? AND user_id=?", (guild_id, user_id))
    c.execute("INSERT INTO matchtips VALUES (?,?,?)", (guild_id, user_id, tip))

    conn.commit()
    await interaction.response.send_message("Tips sparat!", ephemeral=True)

@tree.command(name="tippa_tabell", description="Tippa sluttabell")
async def tippa_tabell(interaction: discord.Interaction, tips: str):

    if datetime.now() > TABELL_DEADLINE:
        await interaction.response.send_message("Tabelltips är stängda.", ephemeral=True)
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
        await interaction.response.send_message("Du måste ange 16 unika lag.", ephemeral=True)
        return

    for lag in teams:
        if lag not in ALLSVENSKA_LAG:
            await interaction.response.send_message(f"{lag} är inte giltigt lag.", ephemeral=True)
            return

    for i, team in enumerate(teams):
        c.execute(
            "INSERT INTO tabell VALUES (?,?,?,?)",
            (guild_id, user_id, i+1, team)
        )

    conn.commit()
    await interaction.response.send_message("Tabelltips sparat!", ephemeral=True)

# ================= LEADERBOARD =================

@tree.command(name="leaderboard", description="Topp 20")
async def leaderboard(interaction: discord.Interaction):

    guild_id = str(interaction.guild.id)

    rows = c.execute(
        "SELECT user_id, pts FROM points WHERE guild_id=? ORDER BY pts DESC LIMIT 20",
        (guild_id,)
    ).fetchall()

    if not rows:
        await interaction.response.send_message("Inga poäng ännu.")
        return

    msg = "🏆 Leaderboard\n\n"

    for i, (user_id, pts) in enumerate(rows):
        member = interaction.guild.get_member(int(user_id))
        name = member.display_name if member else user_id
        msg += f"{i+1}. {name} - {pts}p\n"

    await interaction.response.send_message(msg)

@tree.command(name="placering", description="Se din placering")
async def placering(interaction: discord.Interaction):

    guild_id = str(interaction.guild.id)
    user_id = str(interaction.user.id)

    rows = c.execute(
        "SELECT user_id, pts FROM points WHERE guild_id=? ORDER BY pts DESC",
        (guild_id,)
    ).fetchall()

    if not rows:
        await interaction.response.send_message("Inga poäng ännu.", ephemeral=True)
        return

    total = len(rows)
    position = None
    user_points = 0

    for index, (uid, pts) in enumerate(rows):
        if uid == user_id:
            position = index + 1
            user_points = pts
            break

    await interaction.response.send_message(
        f"Din placering: {position}/{total}\nPoäng: {user_points}",
        ephemeral=True
    )

# ================= START =================

client.run(TOKEN)
