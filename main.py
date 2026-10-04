import asyncio
import logging
import os
import shutil
from pathlib import Path

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message
from dotenv import load_dotenv

# ---------- Конфигурация ----------
load_dotenv()

TOKEN = os.getenv("BOT_TOKEN", "").strip()
NDK_BUILD = os.getenv("NDK_BUILD", "ndk-build").strip()
ADMIN_IDS = {
    int(x) for x in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",") if x
}
MAX_FILE_MB = int(os.getenv("MAX_FILE_MB", "20"))
BUILD_TIMEOUT = int(os.getenv("BUILD_TIMEOUT", "180"))

WORKDIR = Path("work")
WORKDIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("ndk-bot")

if not TOKEN:
    raise SystemExit("BOT_TOKEN не задан в .env")

dp = Dispatcher()
bot = Bot(token=TOKEN)


# ---------- Вспомогательные функции ----------
def user_dir(user_id: int) -> Path:
    d = WORKDIR / str(user_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def admin_only(func):
    async def wrapper(message: Message, *args, **kwargs):
        if not message.from_user or not is_admin(message.from_user.id):
            await message.answer("⛔ Доступ запрещён.")
            return
        return await func(message, *args, **kwargs)
    return wrapper


def truncate(text: str, limit: int = 3500) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n... (обрезано)"


async def run_cmd(*args: str, cwd: Path | None = None, timeout: int = 60):
    """Асинхронный запуск внешней команды с таймаутом."""
    proc = await asyncio.create_subprocess_exec(
        *args,
        cwd=str(cwd) if cwd else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return 124, f"⏱ Таймаут {timeout} сек."
    return proc.returncode, out.decode(errors="ignore")


# ---------- Хэндлеры ----------
@dp.message(CommandStart())
@admin_only
async def cmd_start(message: Message):
    await message.answer(
        "👋 Привет!\n\n"
        "Как пользоваться:\n"
        "1. Отправь файл <b>jni.zip</b> (архив с проектом).\n"
        "2. /unzip — распаковать.\n"
        "3. /compile — собрать через ndk-build.\n"
        "4. /clean — удалить свои файлы."
    )


@dp.message(Command("help"))
@admin_only
async def cmd_help(message: Message):
    await cmd_start(message)


@dp.message(F.document)
@admin_only
async def receive_file(message: Message):
    doc = message.document
    name = doc.file_name or ""

    # Проверка имени
    if not (name.startswith("jni") and name.endswith(".zip")):
        await message.answer("❌ Нужен архив с именем вида <b>jni*.zip</b>.")
        return

    # Проверка размера (Telegram даёт file_size)
    if doc.file_size and doc.file_size > MAX_FILE_MB * 1024 * 1024:
        await message.answer(f"❌ Файл больше {MAX_FILE_MB} МБ.")
        return

    udir = user_dir(message.from_user.id)
    dest = udir / name

    try:
        file = await bot.get_file(doc.file_id)
        await bot.download_file(file.file_path, destination=dest)
    except Exception as e:
        log.exception("download failed")
        await message.answer(f"❌ Ошибка скачивания: {e}")
        return

    await message.answer(
        f"✅ Сохранил: <code>{dest}</code>\n"
        f"Теперь /unzip"
    )


@dp.message(Command("unzip"))
@admin_only
async def cmd_unzip(message: Message):
    udir = user_dir(message.from_user.id)
    archives = list(udir.glob("jni*.zip"))
    if not archives:
        await message.answer("❌ Нет загруженного архива. Сначала отправь jni.zip.")
        return

    archive = archives[0]
    await message.answer(f"📦 Распаковываю <code>{archive.name}</code>...")

    code, out = await run_cmd(
        "unzip", "-o", str(archive), "-d", str(udir),
        timeout=60,
    )
    if code != 0:
        await message.answer(f"❌ unzip вернул код {code}:\n<pre>{truncate(out)}</pre>")
        return

    await message.answer(f"✅ Распаковано.\n<pre>{truncate(out, 1500)}</pre>")


@dp.message(Command("compile"))
@admin_only
async def cmd_compile(message: Message):
    udir = user_dir(message.from_user.id)

    if not udir.exists() or not any(udir.iterdir()):
        await message.answer("❌ Нечего собирать. Сначала загрузи и распакуй архив.")
        return

    # Проверяем наличие ndk-build
    ndk_path = shutil.which(NDK_BUILD) or (NDK_BUILD if Path(NDK_BUILD).exists() else None)
    if not ndk_path:
        await message.answer(
            f"❌ <code>ndk-build</code> не найден по пути <code>{NDK_BUILD}</code>.\n"
            "Проверь переменную NDK_BUILD в .env."
        )
        return

    await message.answer("🔨 Запускаю сборку, подожди...")

    # Ищем каталог с jni/ (обычно после unzip это udir/jni или udir/<project>/jni)
    project_dir = udir
    if not (project_dir / "jni").exists():
        for sub in udir.iterdir():
            if sub.is_dir() and (sub / "jni").exists():
                project_dir = sub
                break

    if not (project_dir / "jni").exists():
        await message.answer("❌ Не найден каталог <code>jni/</code> в архиве.")
        return

    code, out = await run_cmd(
        ndk_path, "-C", str(project_dir),
        timeout=BUILD_TIMEOUT,
    )

    status = "✅ Успех" if code == 0 else f"❌ Ошибка (код {code})"
    await message.answer(f"{status}\n<pre>{truncate(out)}</pre>")


@dp.message(Command("clean"))
@admin_only
async def cmd_clean(message: Message):
    udir = user_dir(message.from_user.id)
    shutil.rmtree(udir, ignore_errors=True)
    await message.answer("🧹 Твои файлы удалены.")


@dp.message(Command("id"))
async def cmd_id(message: Message):
    """Показывает ID — полезно для настройки ADMIN_IDS."""
    await message.answer(f"Твой ID: <code>{message.from_user.id}</code>")


@dp.message()
async def fallback(message: Message):
    await message.answer("Не понимаю. /help")


# ---------- Запуск ----------
async def main():
    log.info("Бот запускается. Админов: %d", len(ADMIN_IDS))
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
