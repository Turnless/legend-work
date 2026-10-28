import os, secrets, string, logging
from datetime import datetime, timedelta, timezone
from typing import Any
import httpx
from fastapi import FastAPI, Request, HTTPException
from supabase import create_client

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("legend-webhook")
TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
GROUP_ID = str(os.environ["TELEGRAM_GROUP_ID"])
GROUP_URL = os.getenv("TELEGRAM_GROUP_URL", "https://t.me/the_legend_mm")
HOURS = max(1, int(os.getenv("QUALIFICATION_HOURS", "24")))
WEBHOOK_SECRET = os.environ["TELEGRAM_WEBHOOK_SECRET"]
DB = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])
TG = f"https://api.telegram.org/bot{TOKEN}"
ALPHABET = string.ascii_uppercase + string.digits
app = FastAPI(title="LEGEND Telegram Webhook")


def now():
    return datetime.now(timezone.utc)


def referral_code():
    return "".join(secrets.choice(ALPHABET) for _ in range(8))


def valid_member(member: dict[str, Any]) -> bool:
    status = member.get("status", "")
    return status in {"creator", "administrator", "member"} or (
        status == "restricted" and bool(member.get("is_member", False))
    )


def participant(uid: int):
    rows = DB.table("participants").select("*").eq("telegram_id", uid).limit(1).execute().data
    return rows[0] if rows else None


def register(user: dict[str, Any], incoming: str | None):
    existing = participant(int(user["id"]))
    if existing:
        return existing
    referrer = None
    if incoming and len(incoming) == 8:
        rows = DB.table("participants").select("telegram_id").eq("referral_code", incoming.upper()).limit(1).execute().data
        if rows and int(rows[0]["telegram_id"]) != int(user["id"]):
            referrer = int(rows[0]["telegram_id"])
    record = {
        "telegram_id": int(user["id"]), "username": user.get("username"),
        "display_name": " ".join(filter(None, [user.get("first_name"), user.get("last_name")]))[:100] or "LEGEND member",
        "referral_code": referral_code(), "referred_by": referrer,
        "human_verified": False, "membership_status": "unknown"
    }
    return DB.table("participants").insert(record).execute().data[0]


async def tg(method: str, payload: dict[str, Any]):
    async with httpx.AsyncClient(timeout=12) as client:
        response = await client.post(f"{TG}/{method}", json=payload)
        response.raise_for_status()
        data = response.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram API {method} failed")
        return data.get("result")


async def send(chat_id: int, text: str, reply_markup: dict | None = None):
    payload = {"chat_id": chat_id, "text": text}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    await tg("sendMessage", payload)


def membership_keyboard():
    return {"inline_keyboard": [
        [{"text": "Join LEGEND Telegram", "url": GROUP_URL}],
        [{"text": "Verify membership", "callback_data": "verify"}]
    ]}


async def answer_callback(callback_id: str, text: str, alert: bool = False):
    await tg("answerCallbackQuery", {"callback_query_id": callback_id, "text": text, "show_alert": alert})


async def handle_message(message: dict[str, Any]):
    user = message.get("from") or {}
    if not user.get("id"):
        return
    uid = int(user["id"])
    chat_id = int(message.get("chat", {}).get("id", uid))
    text = (message.get("text") or "").strip()
	

    if text.startswith("/start"):
        parts = text.split(maxsplit=1)
        payload = parts[1] if len(parts) > 1 else ""
        incoming = payload.removeprefix("ref_") if payload.startswith("ref_") else None
        try:
            register(user, incoming)
            a, b = secrets.randbelow(8) + 2, secrets.randbelow(8) + 2
            DB.table("participants").update({
                "challenge_answer": str(a + b),
                "challenge_expires_at": (now() + timedelta(minutes=10)).isoformat()
            }).eq("telegram_id", uid).execute()
            await send(chat_id, f"Welcome to LEGEND referrals.\nHuman check: what is {a} + {b}? Reply with the number.")
        except Exception:
            log.exception("start failed")
    if text.startswith("/link"):
        p = participant(uid)
        if not p or not p.get("human_verified"):
            await send(chat_id, "Use /start and complete the human check first.")
            return
        me = await tg("getMe", {})
        await send(chat_id, f"Your referral link:\nhttps://t.me/{me['username']}?start=ref_{p['referral_code']}")
        return
    if text.startswith("/status"):
        p = participant(uid)
        if not p:
            await send(chat_id, "Use /start to register.")
            return
        rows = DB.table("referrals").select("id", count="exact").eq("referrer_telegram_id", uid).eq("status", "eligible").execute()
        await send(chat_id, f"Membership: {p['membership_status']}\nHuman check: {'complete' if p['human_verified'] else 'pending'}\nEligible referrals: {rows.count or 0}")
        return

    # Persisted challenge works across serverless invocations/restarts.
    p = participant(uid)
    if not p or p.get("human_verified") or not p.get("challenge_answer"):
        return
    expiry = p.get("challenge_expires_at")
    try:
        expired = not expiry or datetime.fromisoformat(expiry.replace("Z", "+00:00")) < now()
    except ValueError:
        expired = True
    if expired:
        DB.table("participants").update({"challenge_answer": None, "challenge_expires_at": None}).eq("telegram_id", uid).execute()
        await send(chat_id, "Human check expired. Send /start to retry.")
        return
    if text != str(p["challenge_answer"]):
        await send(chat_id, "Incorrect answer. Try again or send /start.")
        return
    DB.table("participants").update({
        "human_verified": True, "human_verified_at": now().isoformat(),
        "challenge_answer": None, "challenge_expires_at": None
    }).eq("telegram_id", uid).execute()
    await send(chat_id, "Human check complete. Join the group, then verify membership.", membership_keyboard())


async def handle_callback(callback: dict[str, Any]):
    callback_id = callback["id"]
    user = callback.get("from", {})
    uid = int(user.get("id", 0))
    if callback.get("data") != "verify":
        await answer_callback(callback_id, "Unknown action.", True)
        return
    try:
        p = participant(uid)
        if not p or not p.get("human_verified"):
            await answer_callback(callback_id, "Complete /start and the human check first.", True)
            return
        member = await tg("getChatMember", {"chat_id": GROUP_ID, "user_id": uid})
        if not valid_member(member):
            await answer_callback(callback_id, "Join the official group first.", True)
            return
        joined = now()
        DB.table("participants").update({
            "membership_status": "member", "joined_at": joined.isoformat(),
            "qualified_at": (joined + timedelta(hours=HOURS)).isoformat()
        }).eq("telegram_id", uid).execute()
        DB.table("referrals").update({"status": "pending", "qualified_at": None}).eq("invitee_telegram_id", uid).execute()
        await tg("sendMessage", {"chat_id": callback["message"]["chat"]["id"], "text": f"Membership confirmed. Stay for {HOURS} hours to qualify. Leaving resets the timer."})
        await answer_callback(callback_id, "Membership verified")
    except Exception:
        log.exception("membership verification failed")
        await answer_callback(callback_id, "Could not verify. Check group setup and try again.", True)


async def handle_membership_event(event: dict[str, Any]):
    chat = event.get("chat", {})
    if str(chat.get("id")) != GROUP_ID:
        return
    new_member = event.get("new_chat_member", {})
    old_member = event.get("old_chat_member", {})
    uid = int((new_member.get("user") or {}).get("id", 0))
    if not uid or not participant(uid):
        return
    old, new = valid_member(old_member), valid_member(new_member)
    if new and not old:
        joined = now()
        DB.table("participants").update({"membership_status": "member", "joined_at": joined.isoformat(), "qualified_at": (joined + timedelta(hours=HOURS)).isoformat()}).eq("telegram_id", uid).execute()
        DB.table("referrals").update({"status": "pending", "qualified_at": None}).eq("invitee_telegram_id", uid).execute()
    elif old and not new:
        DB.table("participants").update({"membership_status": "left", "joined_at": None, "qualified_at": None}).eq("telegram_id", uid).execute()
        DB.table("referrals").update({"status": "revoked", "qualified_at": None}).eq("invitee_telegram_id", uid).execute()


@app.get("/api/health")
async def health():
    return {"ok": True, "service": "legend-telegram-webhook"}


@app.post("/api/webhook")
async def webhook(request: Request):
    if request.headers.get("x-telegram-bot-api-secret-token") != WEBHOOK_SECRET:
        raise HTTPException(status_code=403, detail="Forbidden")
    try:
        update = await request.json()
        if "message" in update:
            await handle_message(update["message"])
        elif "callback_query" in update:
            await handle_callback(update["callback_query"])
        elif "chat_member" in update:
            await handle_membership_event(update["chat_member"])
        return {"ok": True}
    except HTTPException:
        raise
    except Exception:
        log.exception("webhook update failed")
        # 500 asks Telegram to retry delivery instead of silently dropping the update.
        raise HTTPException(status_code=500, detail="Update processing failed")
