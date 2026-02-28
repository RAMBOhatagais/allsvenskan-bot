import discord
from discord import app_commands
import sqlite3
import os
from datetime import datetime
from zoneinfo import ZoneInfo
import asyncio

TOKEN = os.getenv("TOKEN")
ALLSVENSKAN_ROLE_ID = 1476904406191702116

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

# ================= TABELL DROPDOWN =================

class TabellDropdown(discord.ui.View):
    def __init__(self, interaction: discord.Interaction):
        super().__init__(timeout=300)
        self.guild_id = str(interaction.guild.id)
        self.user_id = str(interaction.user.id)
        self.position = 1
        self.selected_teams = []
        self.available_teams = ALLSVENSKA_LAG.copy()
        self.message = None
        self.add_item(self.create_select())

    def create_select(self):
        select = discord.ui.Select(
            placeholder=f"Välj lag för plats {self.position}",
            min_values=1,
            max_values=1,
            options=[discord.SelectOption(label=team) for team in self.available_teams]
        )
        select.callback = self.select_callback
        return select

    async def select_callback(self, interaction: discord.Interaction):
        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message(
                "Detta är inte din tabell!",
                ephemeral=True
            )
            return

        chosen = interaction.data["values"][0]
        self.selected_teams.append(chosen)
        self.available_teams.remove(chosen)
        self.position += 1

        if self.position > 16:

            c.execute(
                "DELETE FROM tabell WHERE guild_id=? AND user_id=?",
                (self.guild_id, self.user_id)
            )

            for i, team in enumerate(self.selected_teams):
                c.execute(
                    "INSERT INTO tabell VALUES (?,?,?,?)",
                    (self.guild_id, self.user_id, i+1, team)
                )

            conn.commit()

            summary = ""
            for i, team in enumerate(self.selected_teams):
                summary += f"{i+1}. {team}\n"

            embed = discord.Embed(
                title="✅ Tabelltips sparat!",
                description=summary,
                color=discord.Color.green()
            )
            embed.set_footer(text="Du kan ändra ditt tips fram till 1 april 2026")

            await interaction.response.edit_message(
                content=None,
                embed=embed,
                view=None
            )

            self.stop()
            return

        self.clear_items()
        self.add_item(self.create_select())

        await interaction.response.edit_message(
            content=f"Välj lag för plats {self.position}",
            view=self
        )

    async def on_timeout(self):
        if self.message:
            await self.message.edit(
                content="⏳ Tiden gick ut. Kör /tippa_tabell igen.",
                view=None
            )

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
                            title=f"🚨 OMGÅNG {round_number} ÄR LIVE!",
                            description="Matchen har startat.\nTips är nu stängda.",
                            color=discord.Color.red()
                        )
                        embed.set_footer(text="Allsvenskan Tipset 2026")
                        embed.set_thumbnail(
                            url="https://upload.wikimedia.org/wikipedia/sv/2/25/Allsvenskan_logo.svg"
                        )

                        await channel.send(
                            f"<@&{ALLSVENSKAN_ROLE_ID}>",
                            embed=embed
                        )

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

    await interaction.response.send_message(
        "✅ Denna kanal är nu botens officiella tipskanal."
    )

@app_commands.checks.has_permissions(administrator=True)
@tree.command(name="set_match", description="Admin: sätt veckans match")
async def set_match(interaction: discord.Interaction, match: str, deadline: str, round: int):

    if not correct_channel(interaction):
        await interaction.response.send_message(
            "Fel kanal. Använd tipskanalen.",
            ephemeral=True
        )
        return

    guild_id = str(interaction.guild.id)

    try:
        datetime.strptime(deadline, "%Y-%m-%d %H:%M")
    except:
        await interaction.response.send_message(
            "Fel format. Använd YYYY-MM-DD HH:MM",
            ephemeral=True
        )
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

@app_commands.checks.has_permissions(administrator=True)
@tree.command(name="rapportera_resultat", description="Admin: rapportera matchresultat")
async def rapportera_resultat(interaction: discord.Interaction, resultat: str):

    if not correct_channel(interaction):
        await interaction.response.send_message(
            "Fel kanal.",
            ephemeral=True
        )
        return

    resultat = resultat.upper()

    if resultat not in ["1","X","2"]:
        await interaction.response.send_message(
            "Ange 1, X eller 2.",
            ephemeral=True
        )
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
        f"📢 Rätt resultat: {resultat}\n{winners} fick 3 poäng!"
    )

@app_commands.checks.has_permissions(administrator=True)
@tree.command(name="reset_points", description="Admin: nollställ ALLT")
async def reset_points(interaction: discord.Interaction):

    if not correct_channel(interaction):
        await interaction.response.send_message(
            "Fel kanal.",
            ephemeral=True
        )
        return

    guild_id = str(interaction.guild.id)

    c.execute("DELETE FROM points WHERE guild_id=?", (guild_id,))
    c.execute("DELETE FROM matchtips WHERE guild_id=?", (guild_id,))
    c.execute("DELETE FROM tabell WHERE guild_id=?", (guild_id,))
    c.execute("DELETE FROM final_table WHERE guild_id=?", (guild_id,))
    c.execute("DELETE FROM match_settings WHERE guild_id=?", (guild_id,))
    conn.commit()

    await interaction.response.send_message("⚠️ All data nollställd.")

@app_commands.checks.has_permissions(administrator=True)
@tree.command(name="slut_tabell", description="Admin: mata in riktig sluttabell")
async def slut_tabell(interaction: discord.Interaction, tabell: str):

    if not correct_channel(interaction):
        await interaction.response.send_message("Fel kanal.", ephemeral=True)
        return

    guild_id = str(interaction.guild.id)
    teams = [t.strip() for t in tabell.split(",")]

    if len(teams) != 16 or len(set(teams)) != 16:
        await interaction.response.send_message(
            "Du måste ange 16 unika lag.",
            ephemeral=True
        )
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

    await interaction.response.send_message("🏁 Tabellpoäng tillagda!")

# ================= USER =================

@tree.command(name="tippa_match", description="Tippa 1/X/2")
async def tippa_match(interaction: discord.Interaction, tip: str):

    if not correct_channel(interaction):
        await interaction.response.send_message(
            "Fel kanal.",
            ephemeral=True
        )
        return

    tip = tip.upper()

    if tip not in ["1","X","2"]:
        await interaction.response.send_message(
            "Ange 1, X eller 2.",
            ephemeral=True
        )
        return

    guild_id = str(interaction.guild.id)
    user_id = str(interaction.user.id)

    status = c.execute(
        "SELECT is_open FROM match_settings WHERE guild_id=?",
        (guild_id,)
    ).fetchone()

    if not status or status[0] == 0:
        await interaction.response.send_message(
            "Matchtips är stängda.",
            ephemeral=True
        )
        return

    c.execute("DELETE FROM matchtips WHERE guild_id=? AND user_id=?", (guild_id,user_id))
    c.execute("INSERT INTO matchtips VALUES (?,?,?)", (guild_id,user_id,tip))
    conn.commit()

    embed = discord.Embed(
        title="✅ Tips sparat!",
        description=f"Du tippade: **{tip}**",
        color=discord.Color.green()
    )

    await interaction.response.send_message(embed=embed, ephemeral=True)

@tree.command(name="tippa_tabell", description="Tippa sluttabell")
async def tippa_tabell(interaction: discord.Interaction):

    if not correct_channel(interaction):
        await interaction.response.send_message("Fel kanal.", ephemeral=True)
        return

    if datetime.now() > TABELL_DEADLINE:
        await interaction.response.send_message(
            "Tabelltips är låsta.",
            ephemeral=True
        )
        return

    view = TabellDropdown(interaction)
    await interaction.response.send_message(
        "Välj lag för plats 1",
        view=view,
        ephemeral=True
    )
    view.message = await interaction.original_response()

@tree.command(name="leaderboard", description="Topp 20")
async def leaderboard(interaction: discord.Interaction):

    if not correct_channel(interaction):
        await interaction.response.send_message("Fel kanal.", ephemeral=True)
        return

    guild_id = str(interaction.guild.id)

    rows = c.execute(
        "SELECT user_id, pts FROM points WHERE guild_id=? ORDER BY pts DESC LIMIT 20",
        (guild_id,)
    ).fetchall()

    if not rows:
        await interaction.response.send_message(
            "Inga poäng ännu.",
            ephemeral=True
        )
        return

    embed = discord.Embed(
        title="🏆 Leaderboard",
        description="Topp 20 i tävlingen",
        color=discord.Color.gold()
    )

    medals = ["🥇","🥈","🥉"]

    for i,(user_id,pts) in enumerate(rows):
        member = interaction.guild.get_member(int(user_id))
        name = member.display_name if member else f"<@{user_id}>"
        prefix = medals[i] if i < 3 else f"{i+1}."
        embed.add_field(
            name=f"{prefix} {name}",
            value=f"{pts} poäng",
            inline=False
        )

    embed.set_footer(text="Allsvenskan Tipset 2026")

    await interaction.response.send_message(embed=embed, ephemeral=True)

@tree.command(name="placering", description="Se din placering")
async def placering(interaction: discord.Interaction):

    if not correct_channel(interaction):
        await interaction.response.send_message("Fel kanal.", ephemeral=True)
        return

    guild_id = str(interaction.guild.id)
    user_id = str(interaction.user.id)

    rows = c.execute(
        "SELECT user_id, pts FROM points WHERE guild_id=? ORDER BY pts DESC",
        (guild_id,)
    ).fetchall()

    if not rows:
        await interaction.response.send_message(
            "Inga poäng ännu.",
            ephemeral=True
        )
        return

    for index,(uid,pts) in enumerate(rows):
        if uid == user_id:
            await interaction.response.send_message(
                f"📍 Din placering: {index+1}/{len(rows)}\nPoäng: {pts}",
                ephemeral=True
            )
            return

# ================= START =================

client.run(TOKEN)
