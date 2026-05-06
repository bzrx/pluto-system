import discord
from discord.ext import commands
import asyncio

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

import os
TOKEN = os.getenv("TOKEN")

SELLER_ROLE_NAME = "Seller"
BUYER_ROLE_NAME = "Buyers"
TICKET_CATEGORY_NAME = "Tickets"

active_orders = {}
order_locks = {}

# ---------------- LOCK ----------------
def get_lock(order_id):
    if order_id not in order_locks:
        order_locks[order_id] = asyncio.Lock()
    return order_locks[order_id]

# ---------------- TICKET NUMBER ----------------
ticket_numbers = {}  # {guild_id: next_ticket_number}

def get_next_ticket_number(guild):
    guild_id = guild.id
    if guild_id not in ticket_numbers:
        category = discord.utils.get(guild.categories, name=TICKET_CATEGORY_NAME)
        if category:
            existing_numbers = [int(c.name) for c in category.channels if c.name.isdigit()]
            ticket_numbers[guild_id] = max(existing_numbers, default=0) + 1
        else:
            ticket_numbers[guild_id] = 1
    num = ticket_numbers[guild_id]
    ticket_numbers[guild_id] += 1
    return str(num)

# ---------------- MODAL ----------------
class AcceptModal(discord.ui.Modal, title="Accept Order"):
    contact = discord.ui.TextInput(
        label="Your Contact (LTC / Phone)",
        required=True
    )

    def __init__(self, order_id, seller):
        super().__init__()
        self.order_id = order_id
        self.seller = seller

    async def on_submit(self, interaction: discord.Interaction):
        order = active_orders.get(self.order_id)

        if not order:
            await interaction.response.send_message("❌ Order not found.", ephemeral=True)
            return

        lock = get_lock(self.order_id)

        async with lock:
            if order.get("claimed"):
                await interaction.response.send_message(
                    "❌ Already taken.",
                    ephemeral=True
                )
                return

            guild = order.get("guild")
            if not guild:
                await interaction.response.send_message(
                    "❌ Server error (no guild).",
                    ephemeral=True
                )
                return

            buyer = order["buyer"]
            seller = self.seller

            try:
                await interaction.response.send_message(
                    "✅ Creating ticket...",
                    ephemeral=True
                )

                # Create category if missing
                category = discord.utils.get(guild.categories, name=TICKET_CATEGORY_NAME)
                if not category:
                    category = await guild.create_category(TICKET_CATEGORY_NAME)

                # Create ticket channel with sequential number
                channel_name = get_next_ticket_number(guild)

                overwrites = {
                    guild.default_role: discord.PermissionOverwrite(read_messages=False),
                    buyer: discord.PermissionOverwrite(read_messages=True, send_messages=True),
                    seller: discord.PermissionOverwrite(read_messages=True, send_messages=True),
                }

                channel = await guild.create_text_channel(
                    name=channel_name,
                    category=category,
                    overwrites=overwrites
                )

                await channel.send(
                    f"🛒 **ORDER STARTED**\n\n"
                    f"Buyer: {buyer.mention}\n"
                    f"Seller: {seller.mention}\n"
                    f"{order['info']}\n\n"
                    f"Contact: `{self.contact.value}`"
                )

                # Mark claimed
                order["claimed"] = True
                order["seller"] = seller
                order["contact"] = self.contact.value

            except Exception as e:
                print("ERROR:", e)
                await interaction.followup.send(
                    "❌ Failed to create ticket.",
                    ephemeral=True
                )

# ---------------- VIEW ----------------
class AcceptView(discord.ui.View):
    def __init__(self, order_id):
        super().__init__(timeout=None)
        self.order_id = order_id

    @discord.ui.button(label="Accept Order", style=discord.ButtonStyle.green)
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        order = active_orders.get(self.order_id)

        if not order:
            await interaction.response.send_message("❌ Order missing.", ephemeral=True)
            return

        await interaction.response.send_modal(
            AcceptModal(self.order_id, interaction.user)
        )

# ---------------- COMMAND ----------------
@bot.command()
@commands.has_role(BUYER_ROLE_NAME)
async def need(ctx, amount: str):
    role = discord.utils.get(ctx.guild.roles, name=SELLER_ROLE_NAME)

    if not role:
        await ctx.send("❌ Seller role not found.")
        return

    order_id = str(ctx.message.id)
    order_info = f"💰 Need: {amount}"

    active_orders[order_id] = {
        "info": order_info,
        "claimed": False,
        "buyer": ctx.author,
        "seller": None,
        "guild": ctx.guild
    }

    view = AcceptView(order_id)

    sent = 0
    for member in role.members:
        try:
            await member.send(
                f"📢 **NEW ORDER**\n{order_info}",
                view=view
            )
            sent += 1
        except discord.Forbidden:
            pass

    await ctx.send(f"✅ Sent to {sent} sellers.")

# ---------------- ERROR HANDLER ----------------
@need.error
async def need_error(ctx, error):
    if isinstance(error, commands.MissingRole):
        await ctx.send("❌ You need the Buyers role to use this command.")

# ---------------- READY ----------------
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")

bot.run(TOKEN)
