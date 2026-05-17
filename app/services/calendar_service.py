import os
from datetime import datetime, timedelta, timezone
import psycopg2
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

DATABASE_URL = os.getenv("DATABASE_URL")

SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/calendar.events",
]

def get_user_credentials(user_id: str):
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute("""
            SELECT access_token, refresh_token, scopes, token_expiry
            FROM user_gmail_tokens WHERE user_id = %s
        """, (user_id,))
        row = cur.fetchone()
        cur.close()
        conn.close()

        if not row:
            return None, "NO_TOKEN"

        access_token, refresh_token, scopes, token_expiry = row

        if not refresh_token:
            return None, "INSUFFICIENT_SCOPE"

        stored_scopes = scopes or ""
        if "auth/calendar" not in stored_scopes:
            return None, "INSUFFICIENT_SCOPE"

        creds = Credentials(
            token=access_token,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=os.getenv("GOOGLE_CLIENT_ID"),
            client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
            scopes=SCOPES,
        )

        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            _save_refreshed_token(user_id, creds.token)

        return creds, None

    except Exception as e:
        return None, str(e)


def _save_refreshed_token(user_id: str, new_access_token: str):
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute("""
            UPDATE user_gmail_tokens
            SET access_token = %s, updated_at = NOW()
            WHERE user_id = %s
        """, (new_access_token, user_id))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[CALENDAR] Error refresh token: {e}")


def get_calendar_events(user_id: str, max_results: int = 10):
    creds, error = get_user_credentials(user_id)
    if error:
        return {"error": error, "reauth_required": True, "events": []}

    try:
        service = build("calendar", "v3", credentials=creds)
        now = datetime.now(timezone.utc).isoformat()
        result = service.events().list(
            calendarId="primary",
            timeMin=now,
            maxResults=max_results,
            singleEvents=True,
            orderBy="startTime",
        ).execute()
        events = result.get("items", [])
        return {"events": events, "error": None, "reauth_required": False}

    except HttpError as e:
        if e.resp.status == 403:
            return {"error": "INSUFFICIENT_SCOPE", "reauth_required": True, "events": []}
        return {"error": str(e), "reauth_required": False, "events": []}


def add_calendar_event(user_id: str, title: str, start: str, end: str, description: str = ""):
    creds, error = get_user_credentials(user_id)
    if error:
        return {"error": error, "reauth_required": True}

    try:
        service = build("calendar", "v3", credentials=creds)
        event = {
            "summary": title,
            "description": description,
            "start": {"dateTime": start, "timeZone": "Asia/Jakarta"},
            "end": {"dateTime": end, "timeZone": "Asia/Jakarta"},
            "reminders": {
                "useDefault": False,
                "overrides": [
                    {"method": "popup", "minutes": 30},
                    {"method": "popup", "minutes": 10},
                ],
            },
        }
        result = service.events().insert(calendarId="primary", body=event).execute()
        return {"event": result, "error": None, "reauth_required": False}

    except HttpError as e:
        if e.resp.status == 403:
            return {"error": "INSUFFICIENT_SCOPE", "reauth_required": True}
        return {"error": str(e), "reauth_required": False}
