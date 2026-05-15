from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
import os, json, httpx

router = APIRouter()

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
REDIRECT_URI = "https://web-production-d2935.up.railway.app/auth/google/callback"

SCOPES = [
    "openid",
    "email",
    "profile",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
]

@router.get("/auth/google/login")
async def google_login(user_id: str = "default"):
    scope = " ".join(SCOPES)
    url = (
        f"https://accounts.google.com/o/oauth2/v2/auth"
        f"?client_id={GOOGLE_CLIENT_ID}"
        f"&redirect_uri={REDIRECT_URI}"
        f"&response_type=code"
        f"&scope={scope}"
        f"&access_type=offline"
        f"&prompt=consent"
        f"&state={user_id}"
    )
    return RedirectResponse(url)

@router.get("/auth/google/callback")
async def google_callback(code: str, state: str = "default"):
    user_id = state
    async with httpx.AsyncClient() as client:
        token_res = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "redirect_uri": REDIRECT_URI,
                "grant_type": "authorization_code",
            }
        )
        tokens = token_res.json()
        access_token = tokens.get("access_token", "")
        refresh_token = tokens.get("refresh_token", "")

        # Simpan token ke database
        if access_token:
            from app.services.database_service import get_connection, save_user_gmail_token
            save_user_gmail_token(user_id, access_token, refresh_token)

        # Simpan refresh token ke gmail_service cache
        if refresh_token:
            token_data = {
                "token": access_token,
                "refresh_token": refresh_token,
                "token_uri": "https://oauth2.googleapis.com/token",
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "scopes": SCOPES
            }
            from app.services.database_service import get_connection, DB_PATH
            import sqlite3
            conn, _db_type = get_connection()
            c = conn.cursor()
            c.execute('''
                CREATE TABLE IF NOT EXISTS user_gmail_tokens (
                    user_id TEXT PRIMARY KEY,
                    access_token TEXT,
                    refresh_token TEXT,
                    token_json TEXT,
                    updated_at TIMESTAMP DEFAULT NOW()
                )
            ''')
            c.execute('''
                INSERT INTO user_gmail_tokens (user_id, access_token, refresh_token, token_json, updated_at)
                VALUES (?, ?, ?, ?, NOW())
                ON CONFLICT(user_id) DO UPDATE SET
                    access_token = excluded.access_token,
                    refresh_token = excluded.refresh_token,
                    token_json = excluded.token_json,
                    updated_at = excluded.updated_at
            ''', (user_id, access_token, refresh_token, json.dumps(token_data)))
            conn.commit()
            conn.close()

    return {"status": "success", "user_id": user_id, "message": "Gmail berhasil terhubung!"}
