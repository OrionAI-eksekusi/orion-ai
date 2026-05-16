from fastapi import APIRouter
from fastapi.responses import RedirectResponse, JSONResponse
import os, urllib.parse, httpx
from datetime import datetime

router = APIRouter()

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
REDIRECT_URI = "https://web-production-d2935.up.railway.app/auth/google/callback"
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")

SCOPES = [
    "openid", "email", "profile",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
]

@router.get("/auth/google/login")
async def google_login():
    scope = " ".join(SCOPES)
    url = (
        f"https://accounts.google.com/o/oauth2/v2/auth"
        f"?client_id={GOOGLE_CLIENT_ID}"
        f"&redirect_uri={REDIRECT_URI}"
        f"&response_type=code"
        f"&scope={scope}"
        f"&access_type=offline"
        f"&prompt=consent"
    )
    return RedirectResponse(url)

@router.get("/auth/google/callback")
async def google_callback(code: str, state: str = "default"):
    try:
        async with httpx.AsyncClient() as client:

            # 1. Tukar code dengan token
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

            # Cek token valid
            if not access_token:
                print(f"Token error: {tokens}")
                return RedirectResponse(f"{FRONTEND_URL}/login?error=token_failed")

            # 2. Ambil info user dari Google
            user_res = await client.get(
                "https://www.googleapis.com/oauth2/v2/userinfo",
                headers={"Authorization": f"Bearer {access_token}"}
            )
            user_info = user_res.json()
            email = user_info.get("email", "")
            name = user_info.get("name", "")
            photo = user_info.get("picture", "")

            if not email:
                return RedirectResponse(f"{FRONTEND_URL}/login?error=no_email")

            # 3. Buat user_id dari email
            user_id = email.upper().replace("@", "").replace(".", "")

            # 4. Simpan Gmail token
            try:
                from app.services.database_service import save_user_gmail_token
                save_user_gmail_token(user_id, access_token, refresh_token)
            except Exception as e:
                print(f"Error saving gmail token: {e}")

            # 5. Simpan user profile
            plan = 'trial'
            trial_days_left = 3
            try:
                from app.services.database_service import get_connection
                conn, db_type = get_connection()
                c = conn.cursor()
                if db_type == "postgresql":
                    c.execute('''
                        INSERT INTO users (user_id, name, email, plan, created_at, updated_at)
                        VALUES (%s, %s, %s, %s, NOW(), NOW())
                        ON CONFLICT(user_id) DO UPDATE SET
                            name = excluded.name,
                            updated_at = NOW()
                        RETURNING plan, trial_end_date
                    ''', (user_id, name, email, 'trial'))
                    row = c.fetchone()
                    if row:
                        plan = row[0] or 'trial'
                        trial_end = row[1]
                        if trial_end:
                            diff = trial_end - datetime.now()
                            trial_days_left = max(0, diff.days)
                conn.commit()
                conn.close()
            except Exception as e:
                print(f"Error saving user: {e}")

            # 6. Redirect ke frontend
            params = urllib.parse.urlencode({
                "user_id": user_id,
                "name": name,
                "email": email,
                "photo": photo,
                "plan": plan,
                "trial_days_left": trial_days_left,
            })
            return RedirectResponse(f"{FRONTEND_URL}/auth/callback?{params}")

    except Exception as e:
        print(f"Auth error: {e}")
        return RedirectResponse(f"{FRONTEND_URL}/login?error=server_error")
