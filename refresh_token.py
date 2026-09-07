"""Force OAuth re-authentication. Run weekly (or when scheduled task fails)."""
import os
import sys

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from main import TOKEN_FILE, get_youtube_service

print("=" * 50)
print("    ContentBot — OAuth Token Refresh")
print("=" * 50)

if os.path.exists(TOKEN_FILE):
    os.remove(TOKEN_FILE)
    print(f"🗑️  Deleted old token: {TOKEN_FILE}")
else:
    print("ℹ️  No existing token (first auth?)")

print("\n🌐 Browser akan terbuka untuk re-authorization...")
print("   1. Login dengan akun YouTube kamu")
print("   2. Klik 'Continue' di warning 'Google hasn't verified this app'")
print("   3. Klik 'Allow' untuk izin upload")
print("   4. Browser auto-close setelah selesai\n")

try:
    get_youtube_service()
    print(f"\n✅ Re-authorized successfully!")
    print(f"   Token saved to: {TOKEN_FILE}")
    print(f"   Valid untuk ~7 hari ke depan.\n")
    print("   Scheduled task akan jalan normal lagi.")
except Exception as e:
    print(f"\n❌ Authorization failed: {e}")
    sys.exit(1)
