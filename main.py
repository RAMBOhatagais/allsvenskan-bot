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

c.execute("""
CREATE TABLE IF NOT EXISTS final_table(
    guild_id TEXT,
    position INTEGER,
    team TEXT
)
""")

c.execute("""
CREATE TABLE IF NOT EXISTS season_settings(
    guild_id TEXT PRIMARY KEY,
    season_finished INTEGER
)
""")

# ================= AUTO MIGRATION =================

def column_exists(table, column):
    columns = c.execute(f"PRAGMA table_info({table})").fetchall()
    return any(col[1] == column for col in columns)

for col in ["deadline TEXT", "round INTEGER", "live_sent INTEGER DEFAULT 0", "channel_id TEXT"]:
    name = col.split()[0]
    if not column_exists("match_settings", name):
        c.execute(f"ALTER TABLE match_settings ADD COLUMN {col}")

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

                c.execute(
                    "UPDATE match_settings SET is_open=0 WHERE guild_id=?",
                    (guild_id,)
                )

                if live_sent == 0 and channel_id:
                    channel = client.get_channel(int(channel_id))
                    if channel:
                        embed = discord.Embed(
                            title=f"🚨 OMGÅNG {round_number} ÄR LIVE!!!",
                            description="Matchen har startat.\nTips är nu stängda.",
                            color=discord.Color.red()
                        )
                        embed.set_footer(text="Allsvenskan Tipset")
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
    client.loop.create_task(deadline_checker())
    print("Bot ready")

# ================= ADMIN =================

@tree.command(name="set_match", description="Admin: sätt veckans match")
async def set_match(interaction: discord.Interaction, match: str, deadline: str, round: int, text: str = None):

    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("Endast admin.", ephemeral=True)
        return

    guild_id = str(interaction.guild.id)

    try:
        datetime.strptime(deadline, "%Y-%m-%d %H:%M")
    except:
        await interaction.response.send_message("Fel format. YYYY-MM-DD HH:MM", ephemeral=True)
        return

    c.execute("DELETE FROM matchtips WHERE guild_id=?", (guild_id,))

    c.execute(
        "REPLACE INTO match_settings (guild_id, is_open, deadline, round, live_sent, channel_id) VALUES (?, ?, ?, ?, ?, ?)",
        (guild_id, 1, deadline, round, 0, str(interaction.channel.id))
    )

    conn.commit()

    embed = discord.Embed(
        title=f"⚽ Omgång {round}",
        description=f"**Veckans match:** {match}",
        color=discord.Color.green()
    )

    if text:
        embed.add_field(name="Info", value=text, inline=False)

    embed.add_field(name="Deadline", value=f"{deadline} (svensk tid)", inline=False)
    embed.set_footer(text="Tippa med /tippa_match 1 X 2")

    await interaction.response.send_message("@everyone", embed=embed)

# ================= SLUTTABELL =================

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

    c.execute(
        "REPLACE INTO season_settings (guild_id, season_finished) VALUES (?, ?)",
        (guild_id, 1)
    )

    conn.commit()

    # === ANNONSERA TOPP 5 ===
    rows = c.execute(
        "SELECT user_id, pts FROM points WHERE guild_id=? ORDER BY pts DESC LIMIT 5",
        (guild_id,)
    ).fetchall()

    embed = discord.Embed(
        title="🏆 SLUTRESULTAT – TOPP 5",
        color=discord.Color.gold()
    )

    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]

    for i, (user_id, pts) in enumerate(rows):
        member = interaction.guild.get_member(int(user_id))
        name = member.display_name if member else f"User {user_id}"
        embed.add_field(name=f"{medals[i]} {name}", value=f"{pts} poäng", inline=False)

    embed.set_footer(text="Allsvenskan Tipset – Säsongen är avslutad!")

    await interaction.response.send_message("@everyone", embed=embed)

# ================= LEADERBOARD =================

@tree.command(name="leaderboard", description="Matchpoäng – Topp 20")
async def leaderboard(interaction: discord.Interaction):

    guild_id = str(interaction.guild.id)

    rows = c.execute(
        "SELECT user_id, pts FROM points WHERE guild_id=? ORDER BY pts DESC LIMIT 20",
        (guild_id,)
    ).fetchall()

    if not rows:
        await interaction.response.send_message("Inga poäng ännu.")
        return

    embed = discord.Embed(
        title="🏆 Leaderboard – Matchpoäng",
        color=discord.Color.gold()
    )

    medals = ["🥇", "🥈", "🥉"]

    for index, (user_id, pts) in enumerate(rows):
        member = interaction.guild.get_member(int(user_id))
        name = member.display_name if member else f"User {user_id}"

        prefix = medals[index] if index < 3 else f"{index+1}."

        embed.add_field(name=f"{prefix} {name}", value=f"{pts} poäng", inline=False)

    await interaction.response.send_message(embed=embed)

# ================= PLACERING =================

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

    if position is None:
        await interaction.response.send_message("Du har inga poäng ännu.", ephemeral=True)
        return

    embed = discord.Embed(title="📍 Din placering", color=discord.Color.blue())
    embed.add_field(name="Placering", value=f"{position} / {total}", inline=False)
    embed.add_field(name="Poäng", value=f"{user_points}", inline=False)

    await interaction.response.send_message(embed=embed, ephemeral=True)

# ================= START =================

client.run(TOKEN)
