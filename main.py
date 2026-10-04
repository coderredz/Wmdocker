from aiogram import Bot, Dispatcher, F
from aiogram.types import Message

import asyncio, os, subprocess

TOKEN = ""

dp = Dispatcher()
bot = Bot(token=TOKEN)

@dp.message(F.document)
async def recive_file(message: Message, bot: Bot):
	document = message.document
	if (!document.file_name.endswitch(".zip") or !document.file_name.startswitch("jni.zip")) await message.ansver("that is not zip file or is not jni.zip")

	file = await bot.get_file(document.file_id)

	path = f"zip/{document.file_name}"

	await bot.download_file(file.file_path, destination=path)

@dp.message(Command("/unzip"))
async def unzip(message: Message):
	os.system("unzip zip/jni.zip")

@dp.message(Command("/compile"))
async def cmp(message: Message):
	result = subprocess([f".{NDKPATH}+ndk-build"], capture_output=True, text=True)
	await message.ansver(result.stdout)

def init():
	os.mkdir("zip")
