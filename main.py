import asyncio
import logging
import random
import aiohttp
from io import BytesIO # Import untuk mengirim file dalam memori

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# Konfigurasi logging untuk melihat apa yang terjadi di balik layar
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)

# ASCII art, untuk sentuhan estetik yang brutal
ascii_art = r"""
 █████  ██████  ███    ███ ██ ███    ██       ███████ ██ ███    ██ ██████  ███████ ██████
██   ██ ██   ██ ████  ████ ██ ████   ██       ██      ██ ████   ██ ██   ██ ██      ██   ██
███████ ██   ██ ██ ████ ██ ██ ██ ██  ██ █████ █████   ██ ██ ██  ██ ██   ██ █████   ██████
██   ██ ██   ██ ██  ██  ██ ██ ██  ██ ██       ██      ██ ██  ██ ██ ██   ██ ██      ██   ██
██   ██ ██████  ██      ██ ██ ██   ████       ██      ██ ██   ████ ██████  ███████ ██   ██

    Admin Finder By Rev
"""

# Daftar jalur admin yang akan dipindai
admin_paths = [
    # Common
    "admin", "admin/login", "administrator", "adminpanel", "admin_area", "admin1", "admin2", "admincp",
    "adm", "cpanel", "controlpanel", "admin_login", "admin-login", "adminLogon", "adminLogin",
    "administrator/login", "administratorlogin", "siteadmin", "siteadmin/login", "webadmin",
    "webmaster", "moderator", "moderator/login", "panel", "dashboard", "auth/login", "login",
    "logon", "signin", "admin-signin", "admin-signin.php",

    # CMS-specific
    "wp-admin", "wp-login.php", "wp-admin/admin-ajax.php", "wp-admin/admin.php",
    "administrator/index.php?option=com_login", "administrator/index.php",
    "admin.php", "admin.html", "admin.asp", "admin.aspx", "admin.jsp",
    "login.php", "login.html", "login.asp", "login.jsp",

    # Frameworks & misc
    "user", "usuarios", "usuario", "memberadmin", "vue-element-admin", "processwire", "admin/dashboard",
    "adminarea", "admincontrol", "adminmaster", "adminmodule", "adminmanager", "adminmenu", "admin_media",
    "admin_messages", "admin_messages.php", "admin_news", "admin_news.php", "admin_new", "admin_log",
    "adminlist", "adminsignin", "admin_login.jsp", "admin_login.aspx", "admin_login.html",

    # International
    "acceso", "adminka", "administração", "administração/login", "administratorr", "adminpanel/login",
    "yonetici", "yonetici.php", "painel", "panel-administracion", "pan-admon", "beheer", "beheerder",
    "logowanie", "zaloguj", "dangnhap", "giris", "admin/giris",

    # Hosting/CPanel
    "webcp", "webadmin", "admincp/login", "cpanel/login", "hostadmin", "cpaneladmin",

    # Hidden/obscure
    "admin123", "secretadmin", "hiddenadmin", "adminaccess", "secureadmin", "privateadmin",
    "portal/admin", "secure/login", "dashboardadmin", "admin-console", "adminpanelv2",
    "manage/admin", "management", "manage", "backend", "securearea", "securelogin"
]

# Daftar User-Agent untuk menghindari deteksi bot
user_agents = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:109.0) Gecko/20100101 Firefox/110.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.1 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Linux; Android 10; SM-G973F) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Mobile Safari/537.36"
]

async def detect_cms_and_initial_admin(session: aiohttp.ClientSession, url: str) -> tuple[str, list[str]]:
    """
    Mendeteksi CMS dan mengembalikan URL admin awal yang ditemukan selama deteksi.
    Ini memastikan jalur penting seperti wp-login.php tidak terlewat.
    """
    found_initial_admins = []
    cms_type = "generic"
    base_url_normalized = url.rstrip('/')

    try:
        # Periksa WordPress
        wp_login_url = f"{base_url_normalized}/wp-login.php"
        async with session.get(wp_login_url, timeout=5, allow_redirects=False) as wp_res:
            if wp_res.status == 200:
                cms_type = "wordpress"
                found_initial_admins.append(wp_login_url)
                logging.info(f"CMS terdeteksi: WordPress di {wp_login_url}")

        # Periksa Joomla
        joomla_admin_url = f"{base_url_normalized}/administrator"
        async with session.get(joomla_admin_url, timeout=5, allow_redirects=False) as joomla_res:
            if joomla_res.status == 200:
                # Jika sudah WordPress, kita tetap prioritaskan WordPress,
                # tapi tambahkan URL Joomla jika berbeda.
                if cms_type != "wordpress":
                    cms_type = "joomla"
                found_initial_admins.append(joomla_admin_url)
                logging.info(f"CMS terdeteksi: Joomla di {joomla_admin_url}")

    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
        logging.warning(f"Error saat deteksi CMS untuk {url}: {e}")
        pass # Abaikan error selama deteksi, asumsikan generik jika ada masalah

    return cms_type, list(set(found_initial_admins)) # Hapus duplikat dari hasil awal

async def scan_path_async(
    session: aiohttp.ClientSession,
    base_url: str,
    path: str,
) -> str | None:
    """Memindai jalur admin secara asinkron."""
    full_url = f"{base_url.rstrip('/')}/{path.lstrip('/')}"
    headers = {'User-Agent': random.choice(user_agents)}

    try:
        async with session.get(full_url, headers=headers, timeout=7, allow_redirects=True) as res:
            content = await res.text()
            content_lower = content.lower()

            # Pemeriksaan kata kunci yang lebih kuat untuk halaman admin
            if res.status == 200 and any(keyword in content_lower for keyword in ['login', 'admin', 'dashboard', 'control panel', 'sign in', 'account', 'masuk', 'panel administrasi']):
                return full_url
            # Kita bisa memilih untuk melaporkan 403 sebagai potensi, tapi untuk saat ini, hanya 200 OK yang dicatat.
            elif res.status == 403:
                logging.info(f"Akses Ditolak (403) untuk: {full_url} - Mungkin halaman admin terlarang.")
                return None
            else:
                pass
    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
        logging.debug(f"Error atau timeout saat memindai {full_url}: {e}")
        pass
    return None

async def admin_finder_task(update: Update, context: ContextTypes.DEFAULT_TYPE, base_url: str) -> None:
    """Tugas utama pemindai admin yang berjalan di latar belakang."""
    chat_id = update.effective_chat.id
    all_found_pages = set() # Menggunakan set untuk menghindari duplikat dan menjaga keunikan URL

    await context.bot.send_message(chat_id=chat_id, text=f"⚡ Memulai pemindaian untuk: `{base_url}`...", parse_mode='Markdown')

    try:
        async with aiohttp.ClientSession() as session:
            await context.bot.send_message(chat_id=chat_id, text="🔎 Mendeteksi CMS dan jalur admin awal...")
            cms, initial_admins = await detect_cms_and_initial_admin(session, base_url)
            
            # Tambahkan hasil deteksi CMS awal ke daftar temuan
            for admin_url in initial_admins:
                if admin_url not in all_found_pages:
                    all_found_pages.add(admin_url)
                    await context.bot.send_message(chat_id=chat_id, text=f"✅ Ditemukan (deteksi CMS): `{admin_url}`", parse_mode='Markdown')

            await context.bot.send_message(chat_id=chat_id, text=f"ℹ️ CMS terdeteksi: *{cms}*", parse_mode='Markdown')

            tasks = []
            paths_to_scan = set(admin_paths)
            
            # Hapus jalur yang sudah ditemukan selama deteksi awal untuk menghindari pemindaian berlebihan
            for initial_admin_full_url in initial_admins:
                for path in admin_paths:
                    if initial_admin_full_url.endswith(path.lstrip('/')): # Memastikan perbandingan yang benar
                        paths_to_scan.discard(path)
                        break # Keluar dari loop path setelah menemukan kecocokan

            # Mulai pemindaian jalur admin lainnya
            for path in paths_to_scan:
                task = asyncio.create_task(scan_path_async(session, base_url, path))
                tasks.append(task)

            # Menunggu semua tugas selesai dan mengumpulkan hasil dari pemindaian jalur
            scan_results = await asyncio.gather(*tasks)
            for url in scan_results:
                if url is not None and url not in all_found_pages:
                    all_found_pages.add(url)
                    await context.bot.send_message(chat_id=chat_id, text=f"✅ Ditemukan: `{url}`", parse_mode='Markdown')


        if all_found_pages:
            final_results_list = sorted(list(all_found_pages)) # Urutkan untuk output yang konsisten
            await context.bot.send_message(chat_id=chat_id, text=f"🎉 Pemindaian Selesai! Ditemukan *{len(final_results_list)}* halaman admin:", parse_mode='Markdown')
            
            results_text = "\n".join(final_results_list)
            
            # Kirim file results.txt
            try:
                await context.bot.send_document(
                    chat_id=chat_id,
                    document=BytesIO(results_text.encode('utf-8')),
                    filename=f"results_{base_url.replace('http://', '').replace('https://', '').replace('/', '_')}.txt", # Nama file yang lebih deskriptif
                    caption=f"Hasil pemindaian admin untuk `{base_url}`"
                )
            except Exception as file_e:
                await context.bot.send_message(chat_id=chat_id, text=f"❌ Gagal mengirim file results.txt: `{file_e}`", parse_mode='Markdown')

        else:
            await context.bot.send_message(chat_id=chat_id, text="🙁 Pemindaian Selesai! Tidak ada halaman admin yang ditemukan.")

    except Exception as e:
        await context.bot.send_message(chat_id=chat_id, text=f"❌ Terjadi kesalahan fatal saat memindai: `{e}`", parse_mode='Markdown')

# --- Handler Perintah Telegram ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Mengirim pesan selamat datang dengan gambar thumbnail saat perintah /start dipanggil."""
    # Ganti ini dengan URL gambar thumbnailmu yang sebenarnya, user!
    # Aku sudah menaruh URL contoh yang bisa diakses publik.
    image_url = "https://files.catbox.moe/5pbhma.jpg" 
    welcome_message = f"<pre>{ascii_art}</pre>\n\nHaha! Selamat datang, user! Aku Sando-Ai, siap membantumu menjelajahi kedalaman web. Untuk memulai pemindaian admin, kirimkan perintah `/scan` diikuti dengan URL targetmu. Contoh:\n\n`/scan http://targetku.com`"
    
    await update.message.reply_photo(
        photo=image_url,
        caption=welcome_message,
        parse_mode='HTML'
    )

async def scan_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Memulai pemindaian admin untuk URL yang diberikan."""
    if not context.args:
        await update.message.reply_text("⛔ Kamu lupa URL targetnya! Gunakan format: `/scan http://example.com`", parse_mode='Markdown')
        return

    base_url = context.args[0]
    if not base_url.startswith("http://") and not base_url.startswith("https://"):
        base_url = "http://" + base_url

    await update.message.reply_text(f"⏳ Permintaan pemindaian diterima untuk: `{base_url}`. Aku akan segera memulainya...", parse_mode='Markdown')

    # Memulai tugas pemindai di latar belakang
    context.application.create_task(admin_finder_task(update, context, base_url))

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Mengirimkan pesan bantuan."""
    await update.message.reply_text(
        "Aku Sando-Ai, siap melayanimu! Ini perintah yang bisa kamu gunakan:\n"
        "`/start` - Sambutan dari Sando-Ai dengan gambar pembuka.\n"
        "`/scan <URL>` - Memulai pemindaian halaman admin pada URL yang diberikan.\n"
        "`/help` - Menampilkan pesan bantuan ini.\n\n"
        "Ingat, kekuatan ada di tanganmu!", parse_mode='Markdown'
    )

def main() -> None:
    """Fungsi utama untuk menjalankan bot."""
    # Ganti 'YOUR_TELEGRAM_BOT_TOKEN_HERE' dengan token bot Telegrammu yang sebenarnya, user!
    BOT_TOKEN = "8525678245:AAFLTlDxCx3WrszxgEL4JT3vJ5t1Mx-QYWo" 
    
    if BOT_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN_HERE":
        print("❌ Error: Harap ganti 'YOUR_TELEGRAM_BOT_TOKEN_HERE' dengan token bot Telegrammu yang asli.")
        return

    application = Application.builder().token(BOT_TOKEN).build()

    # Menambahkan handler perintah
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("scan", scan_command))
    application.add_handler(CommandHandler("help", help_command))

    print("🚀 Rex-i Bot telah aktif! Siap menerima perintah...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
