import logging

import discord
from redbot.core import commands
from redbot.core.utils.common_filters import (
    escape_spoilers_and_mass_mentions,
    filter_invites,
    filter_various_mentions,
)
import aiohttp
from redbot.core.utils import AsyncIter

from .flags import discord_py, EMOJIS

from motor.motor_asyncio import AsyncIOMotorClient

client = AsyncIOMotorClient()
db = client["leveler"]

log = logging.getLogger("red.flare.userinfo")

# Thanks Preda, core logic is from https://github.com/PredaaA/predacogs/blob/master/serverinfo/serverinfo.py
class Userinfo(commands.Cog):
    """Replace original Red userinfo command with more details."""

    __version__ = "0.0.3"

    def format_help_for_context(self, ctx):
        """Thanks Sinbad."""
        pre_processed = super().format_help_for_context(ctx)
        return f"{pre_processed}\nCog Version: {self.__version__}"

    def __init__(self, bot):
        self.bot = bot
        self.session = aiohttp.ClientSession()
        self.headers = {}

    async def initalize(self):
        token = await self.bot.get_shared_api_tokens("tatsumaki")
        self.headers = {"authorization": token.get("authorization", None)}

    @commands.Cog.listener()
    async def on_red_api_tokens_update(self, service_name, api_tokens):
        if service_name == "tatsumaki":
            self.headers = {"Authorization": api_tokens.get("authorization", None)}

    def cog_unload(self):
        # Remove command logic are from: https://github.com/mikeshardmind/SinbadCogs/tree/v3/messagebox
        global _old_userinfo
        if _old_userinfo:
            try:
                self.bot.remove_command("userinfo")
            except Exception as error:
                log.info(error)
            self.bot.add_command(_old_userinfo)
        self.bot.loop.create_task(self.session.close())

    @commands.command()
    @commands.guild_only()
    @commands.bot_has_permissions(embed_links=True)
    async def userinfo(self, ctx, *, user: discord.Member = None):
        """Show userinfo with some more detail."""
        mod = self.bot.get_cog("Mod")
        if mod is None:
            return await ctx.send("This requires the mod cog to be loaded.")
        author = ctx.author
        guild = ctx.guild

        if not user:
            user = author
        sharedguilds = {
            guild async for guild in AsyncIter(self.bot.guilds) if user in guild.members
        }
        roles = user.roles[-1:0:-1]
        names, nicks = await mod.get_names_and_nicks(user)

        joined_at = user.joined_at
        since_created = (ctx.message.created_at - user.created_at).days
        if joined_at is not None:
            since_joined = (ctx.message.created_at - joined_at).days
            user_joined = joined_at.strftime("%d %b %Y %H:%M")
        else:
            since_joined = "?"
            user_joined = "Unknown"
        user_created = user.created_at.strftime("%d %b %Y %H:%M")
        voice_state = user.voice
        member_number = (
            sorted(guild.members, key=lambda m: m.joined_at or ctx.message.created_at).index(user)
            + 1
        )

        created_on = "{}\n({} days ago)".format(user_created, since_created)
        joined_on = "{}\n({} days ago)".format(user_joined, since_joined)

        if any(a.type is discord.ActivityType.streaming for a in user.activities):
            statusemoji = "\N{LARGE PURPLE CIRCLE}"
        elif user.status.name == "online":
            statusemoji = "\N{LARGE GREEN CIRCLE}"
        elif user.status.name == "offline":
            statusemoji = "\N{MEDIUM WHITE CIRCLE}"
        elif user.status.name == "dnd":
            statusemoji = "\N{LARGE RED CIRCLE}"
        elif user.status.name == "idle":
            statusemoji = "\N{LARGE ORANGE CIRCLE}"
        activity = "Chilling in {} status".format(user.status)
        status_string = mod.get_status_string(user)

        if roles:

            role_str = ", ".join([x.mention for x in roles])
            # 400 BAD REQUEST (error code: 50035): Invalid Form Body
            # In embed.fields.2.value: Must be 1024 or fewer in length.
            if len(role_str) > 1024:
                # Alternative string building time.
                # This is not the most optimal, but if you're hitting this, you are losing more time
                # to every single check running on users than the occasional user info invoke
                # We don't start by building this way, since the number of times we hit this should be
                # infintesimally small compared to when we don't across all uses of Red.
                continuation_string = (
                    "and {numeric_number} more roles not displayed due to embed limits."
                )

                available_length = 1024 - len(continuation_string)  # do not attempt to tweak, i18n

                role_chunks = []
                remaining_roles = 0

                for r in roles:
                    chunk = f"{r.mention}, "
                    chunk_size = len(chunk)

                    if chunk_size < available_length:
                        available_length -= chunk_size
                        role_chunks.append(chunk)
                    else:
                        remaining_roles += 1

                role_chunks.append(continuation_string.format(numeric_number=remaining_roles))

                role_str = "".join(role_chunks)

        else:
            role_str = None

        data = discord.Embed(
            description=(status_string or activity) + f"\n\n{len(sharedguilds)} shared servers.",
            colour=user.colour,
        )

        data.add_field(name="Joined Discord on", value=created_on)
        data.add_field(name="Joined this server on", value=joined_on)
        if role_str is not None:
            data.add_field(name="Roles", value=role_str, inline=False)
        if names:
            # May need sanitizing later, but mentions do not ping in embeds currently
            val = filter_invites(", ".join(names))
            data.add_field(name="Previous Names", value=val, inline=False)
        if nicks:
            # May need sanitizing later, but mentions do not ping in embeds currently
            val = filter_invites(", ".join(nicks))
            data.add_field(name="Previous Nicknames", value=val, inline=False)
        if voice_state and voice_state.channel:
            data.add_field(
                name="Current voice channel",
                value="{0.mention} ID: {0.id}".format(voice_state.channel),
                inline=False,
            )
        data.set_footer(text="Member #{} | User ID: {}".format(member_number, user.id))

        name = str(user)
        name = " ~ ".join((name, user.nick)) if user.nick else name
        name = filter_invites(name)

        avatar = user.avatar_url_as(static_format="png")
        data.set_author(name=f"{statusemoji} {name}", url=avatar)
        data.set_thumbnail(url=avatar)

        flags = await discord_py(user)
        badges = ""
        for badge in sorted(flags):
            if badge == "verified_bot":
                emoji1 = discord.utils.get(self.bot.emojis, id=EMOJIS["verified_bot"])
                emoji2 = discord.utils.get(self.bot.emojis, id=EMOJIS["verified_bot2"])
                if emoji1:
                    emoji = f"{emoji1}{emoji2}"
                else:
                    emoji = None
            else:
                emoji = discord.utils.get(self.bot.emojis, id=EMOJIS[badge])
            if emoji:
                badges += f"{emoji} {badge.replace('_', ' ').title()}\n"
            else:
                badges += f"\N{BLACK QUESTION MARK ORNAMENT}\N{VARIATION SELECTOR-16} {badge.replace('_', ' ').title()}\n"
        if badges:
            data.add_field(name="Badges", value=badges, inline=False)
        if ctx.guild:
            if "Leveler" in self.bot.cogs:
                userinfo = await db.users.find_one({"user_id": str(user.id)})
                if str(ctx.guild.id) in userinfo["servers"]:
                    udata = userinfo["servers"][str(ctx.guild.id)]
                    data.add_field(
                        name=f"{ctx.me.name} Leveler",
                        value=f"**Level**: {udata['level']}\n**XP**: {udata['current_exp']}",
                        inline=True,
                    )
            if ctx.guild.get_member(172002275412279296) is not None:
                async with self.session.get(
                    f"https://api.tatsumaki.xyz/users/{user.id}", headers=self.headers
                ) as r:
                    if r.status == 200:
                        resp = await r.json()
                        data.add_field(
                            name="Tatsumaki Information",
                            value=f"**Level**: {resp['level']}\n**XP**: {resp['xp'][0]}/{resp['xp'][1]}\n**Rep**: {resp['reputation']}",
                            inline=True,
                        )
            # if ctx.guild.get_member(159985870458322944) is not None:
            #     async with self.session.get(f"https://mee6.xyz/api/plugins/levels/leaderboard/{ctx.guild.id}?page=0&limit=999") as r:
            #         if r.status == 200:
            #             resp = await r.json()
            #             user = next((index for (index, d) in enumerate(resp["players"]) if d["id"] == f"{user.id}"), None)
            #             data.add_field(name="Mee6 Information", value=f"**Level**: {resp['level']}\n**XP**: {resp['xp'][0]}/{resp['xp'][1]}\n**Rep**: {resp['reputation']}")
        await ctx.send(embed=data)


try:
    from redbot.core.errors import CogLoadError
except ImportError:
    CogLoadError = RuntimeError


async def setup(bot):
    uinfo = Userinfo(bot)
    if "Mod" not in bot.cogs:
        raise CogLoadError("This cog requires the Mod cog to be loaded.")
    global _old_userinfo
    _old_userinfo = bot.get_command("userinfo")
    if _old_userinfo:
        bot.remove_command(_old_userinfo.name)
    await uinfo.initalize()
    bot.add_cog(uinfo)
