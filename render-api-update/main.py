import os
from datetime import datetime, timezone
import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from supabase import create_client

DB = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
GROUP_ID = os.getenv("TELEGRAM_GROUP_ID", "")
origins = [x.strip() for x in os.getenv("CORS_ORIGINS", "https://getthelegend.vercel.app").split(",") if x.strip()]
app = FastAPI(title="LEGEND Referral API", version="1.1.0")
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=False, allow_methods=["GET"], allow_headers=["*"])


def is_member(member: dict) -> bool:
    status = member.get("status", "")
    return status in {"creator", "administrator", "member"} or (status == "restricted" and bool(member.get("is_member")))


def promote_matured_referrals():
    """Promote matured referrals when the public leaderboard is requested."""
    if not TOKEN or not GROUP_ID:
        return
    now = datetime.now(timezone.utc)
    rows = DB.table("participants").select("telegram_id,referred_by,qualified_at").eq("human_verified", True).eq("membership_status", "member").not_.is_("qualified_at", "null").lte("qualified_at", now.isoformat()).execute().data
    with httpx.Client(timeout=8) as client:
        for p in rows:
            uid = int(p["telegram_id"])
            try:
                response = client.post(f"https://api.telegram.org/bot{TOKEN}/getChatMember", json={"chat_id": GROUP_ID, "user_id": uid})
                response.raise_for_status()
                payload = response.json()
                if not payload.get("ok") or not is_member(payload.get("result", {})):
                    DB.table("participants").update({"membership_status": "left", "joined_at": None, "qualified_at": None}).eq("telegram_id", uid).execute()
                    DB.table("referrals").update({"status": "revoked", "qualified_at": None}).eq("invitee_telegram_id", uid).execute()
                elif p.get("referred_by"):
                    DB.table("referrals").upsert({"invitee_telegram_id": uid, "referrer_telegram_id": int(p["referred_by"]), "status": "eligible", "qualified_at": now.isoformat()}, on_conflict="invitee_telegram_id").execute()
            except Exception:
                # Don't break the public leaderboard because one Telegram check failed.
                continue


@app.get("/health")
def health():
    return {"ok": True, "service": "legend-referral-api"}


@app.get("/api/leaderboard")
def leaderboard(limit: int = Query(100, ge=1, le=200)):
    try:
        promote_matured_referrals()
        rows = DB.table("referrals").select("referrer_telegram_id").eq("status", "eligible").execute().data
        counts = {}
        for row in rows:
            uid = int(row["referrer_telegram_id"])
            counts[uid] = counts.get(uid, 0) + 1
        if not counts:
            return {"updated_at": datetime.now(timezone.utc).isoformat(), "entries": []}
        people = DB.table("participants").select("telegram_id,username,display_name").in_("telegram_id", list(counts)).execute().data
        names = {int(p["telegram_id"]): (p.get("username") or p.get("display_name") or "LEGEND member") for p in people}
        ranked = sorted(counts.items(), key=lambda item: (-item[1], names.get(item[0], "").casefold()))[:limit]
        return {"updated_at": datetime.now(timezone.utc).isoformat(), "entries": [{"rank": i, "name": names.get(uid, "LEGEND member"), "eligible_referrals": n} for i, (uid, n) in enumerate(ranked, 1)]}
    except Exception as exc:
        raise HTTPException(503, "Leaderboard temporarily unavailable") from exc
