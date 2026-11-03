# Don't remove This Line From Here. Tg: @rohit_1888 | @Javpostr
import os
import sys
import time
import asyncio
import logging
import subprocess
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import FloodWait
from bot import Bot
from config import CHANNEL_ID, OWNER_ID
from helper_func import encode, is_admin

db_channel_id = CHANNEL_ID

@Bot.on_message(filters.command('update') & filters.private & is_admin)
async def update_bot(client, message):
    if message.from_user.id != OWNER_ID:
        return await message.reply_text("You are not authorized to update the bot.")

    try:
        msg = await message.reply_text("<b><blockquote>Pulling the latest updates and restarting the bot...</blockquote></b>")

        # Run git pull
        git_pull = subprocess.run(["git", "pull"], capture_output=True, text=True)

        if git_pull.returncode == 0:
            await msg.edit_text(f"<b><blockquote>Updates pulled successfully:\n\n{git_pull.stdout}</blockquote></b>")
        else:
            await msg.edit_text(f"<b><blockquote>Failed to pull updates:\n\n{git_pull.stderr}</blockquote></b>")
            return

        await asyncio.sleep(3)
        await msg.edit_text("<b><blockquote>✅ Bᴏᴛ ɪs ʀᴇsᴛᴀʀᴛɪɴɢ ɴᴏᴡ...</blockquote></b>")

    except Exception as e:
        await message.reply_text(f"An error occurred: {e}")
        return

    finally:
        os.execl(sys.executable, sys.executable, *sys.argv)


command_list = [
    'start', 'users', 'broadcast', 'stats', 'addpaid', 'removepaid',
    'listpaid', 'help', 'add_fsub', 'fsub_chnl', 'restart',
    'del_fsub', 'add_admins', 'del_admins', 'admin_list',
    'cancel', 'auto_del', 'forcesub', 'files', 'add_banuser',
    'settings', 'token', 'del_banuser', 'banuser_list', 'status',
    'req_fsub', 'myplan', 'short', 'check', 'free',
    'set_free_limit', 'update', 'genlink', 'batch', 'custom_batch', 'mask',
    'plink'
]
