import os
import json
import base64
import sqlite3
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from dotenv import load_dotenv

load_dotenv()

SCOPES = [
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/gmail.send',
    'https://www.googleapis.com/auth/drive.readonly',
    'https://www.googleapis.com/auth/contacts.readonly',
]

_cached_creds = None


def _build_creds_from_env() -> Credentials:
    token_json = os.getenv("GMAIL_TOKEN_JSON")
    if not token_json:
        raise ValueError("GMAIL_TOKEN_JSON tidak ada di env var")
    token_data = json.loads(token_json)
    return Credentials(
        token=token_data.get("token"),
        refresh_token=token_data.get("refresh_token"),
        token_uri=token_data.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=token_data.get("client_id"),
        client_secret=token_data.get("client_secret"),
        scopes=token_data.get("scopes", SCOPES)
    )


def _save_token_to_db(creds: Credentials):
    try:
        DB_PATH = os.getenv("DB_PATH", "orion.db")
        token_data = {
            "token": creds.token,
            "refresh_token": creds.refresh_token,
            "token_uri": creds.token_uri,
            "client_id": creds.client_id,
            "client_secret": creds.client_secret,
            "scopes": list(creds.scopes) if creds.scopes else SCOPES
        }
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''
            CREATE TABLE IF NOT EXISTS gmail_tokens (
                id INTEGER PRIMARY KEY,
                token_json TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT NOW()
            )
        ''')
        c.execute('''
            INSERT INTO gmail_tokens (id, token_json, updated_at)
            VALUES (1, ?, datetime('now'))
            ON CONFLICT(id) DO UPDATE SET
                token_json = excluded.token_json,
                updated_at = excluded.updated_at
        ''', (json.dumps(token_data),))
        conn.commit()
        conn.close()
        print("[GMAIL] ✅ Token disimpan ke DB")
    except Exception as e:
        print(f"[GMAIL] ❌ Gagal simpan token: {e}")


def _load_token_from_db() -> Credentials:
    try:
        DB_PATH = os.getenv("DB_PATH", "orion.db")
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT token_json FROM gmail_tokens WHERE id = 1")
        row = c.fetchone()
        conn.close()
        if row:
            token_data = json.loads(row[0])
            return Credentials(
                token=token_data.get("token"),
                refresh_token=token_data.get("refresh_token"),
                token_uri=token_data.get("token_uri", "https://oauth2.googleapis.com/token"),
                client_id=token_data.get("client_id"),
                client_secret=token_data.get("client_secret"),
                scopes=token_data.get("scopes", SCOPES)
            )
        return None
    except Exception as e:
        print(f"[GMAIL] Gagal load token dari DB: {e}")
        return None


def _get_valid_creds() -> Credentials:
    global _cached_creds
    if _cached_creds and not _cached_creds.expired:
        return _cached_creds
    creds = _load_token_from_db()
    if not creds:
        creds = _build_creds_from_env()
    if creds and creds.expired and creds.refresh_token:
        print("[GMAIL] 🔄 Token expired — auto refresh...")
        try:
            creds.refresh(Request())
            print("[GMAIL] ✅ Token berhasil di-refresh!")
            _save_token_to_db(creds)
        except Exception as e:
            print(f"[GMAIL] ❌ Gagal refresh token: {e}")
            creds = _build_creds_from_env()
            if creds and creds.expired:
                creds.refresh(Request())
                _save_token_to_db(creds)
    _cached_creds = creds
    return creds


def _get_user_creds(user_id: str) -> Credentials:
    """Ambil credentials untuk user tertentu — multi-user support"""
    try:
        from app.services.database_service import get_user_gmail_token
        user_token = get_user_gmail_token(user_id)
        if user_token and user_token.get('access_token'):
            # Ambil client_id dan client_secret dari env
            base_token = json.loads(os.getenv("GMAIL_TOKEN_JSON", "{}"))
            creds = Credentials(
                token=user_token['access_token'],
                refresh_token=base_token.get('refresh_token', ''),
                token_uri='https://oauth2.googleapis.com/token',
                client_id=base_token.get('client_id', ''),
                client_secret=base_token.get('client_secret', ''),
                scopes=SCOPES
            )
            if creds.expired and creds.refresh_token:
                creds.refresh(Request())
            return creds
    except Exception as e:
        print(f"[GMAIL] Error get user creds: {e}")
    # Fallback ke default
    return _get_valid_creds()


# ── Service Builders ──────────────────────────────────────

def get_gmail_service():
    try:
        creds = _get_valid_creds()
        return build('gmail', 'v1', credentials=creds)
    except Exception as e:
        print(f"[GMAIL SERVICE ERROR] {e}")
        global _cached_creds
        _cached_creds = None
        raise e


def get_gmail_service_for_user(user_id: str):
    """Gmail service untuk user tertentu — multi-user"""
    try:
        creds = _get_user_creds(user_id)
        return build('gmail', 'v1', credentials=creds)
    except Exception as e:
        print(f"[GMAIL USER SERVICE ERROR] {e}")
        return get_gmail_service()


def get_drive_service():
    try:
        creds = _get_valid_creds()
        return build('drive', 'v3', credentials=creds)
    except Exception as e:
        print(f"[DRIVE SERVICE ERROR] {e}")
        raise e


def get_contacts_service():
    try:
        creds = _get_valid_creds()
        return build('people', 'v1', credentials=creds)
    except Exception as e:
        print(f"[CONTACTS SERVICE ERROR] {e}")
        raise e


# ── Gmail Functions ───────────────────────────────────────

def get_recent_emails(max_results=5, user_id: str = None):
    """Ambil email — kalau ada user_id pakai token user, kalau tidak pakai default"""
    try:
        if user_id:
            service = get_gmail_service_for_user(user_id)
        else:
            service = get_gmail_service()
        results = service.users().messages().list(
            userId='me', maxResults=max_results, labelIds=['INBOX']
        ).execute()
        messages = results.get('messages', [])
        emails = []
        for msg in messages:
            detail = service.users().messages().get(
                userId='me', id=msg['id'], format='full'
            ).execute()
            headers = detail['payload']['headers']
            subject = next((h['value'] for h in headers if h['name'] == 'Subject'), 'No Subject')
            sender = next((h['value'] for h in headers if h['name'] == 'From'), 'Unknown')
            body = ''
            payload = detail.get('payload', {})
            if 'parts' in payload:
                for part in payload['parts']:
                    if part.get('mimeType') == 'text/plain':
                        data = part.get('body', {}).get('data', '')
                        if data:
                            body = base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')
                            break
            else:
                data = payload.get('body', {}).get('data', '')
                if data:
                    body = base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')
            emails.append({
                'id': msg['id'],
                'subject': subject,
                'from': sender,
                'snippet': detail.get('snippet', ''),
                'body': body[:1000]
            })
        return emails
    except Exception as e:
        print(f"[GET EMAILS ERROR] {e}")
        return []


def send_email(to: str, subject: str, body: str, user_id: str = None):
    try:
        if user_id:
            service = get_gmail_service_for_user(user_id)
        else:
            service = get_gmail_service()
        message = MIMEText(body)
        message['to'] = to
        message['subject'] = subject
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        service.users().messages().send(
            userId='me', body={'raw': raw}
        ).execute()
        return {"status": "sent", "to": to, "subject": subject}
    except Exception as e:
        print(f"[SEND EMAIL ERROR] {e}")
        return {"status": "error", "message": str(e)}


def send_email_with_attachment(to: str, subject: str, body: str,
                                file_path: str, filename: str,
                                user_id: str = None):
    try:
        if user_id:
            service = get_gmail_service_for_user(user_id)
        else:
            service = get_gmail_service()
        message = MIMEMultipart()
        message['to'] = to
        message['subject'] = subject
        message.attach(MIMEText(body, 'plain'))
        with open(file_path, 'rb') as f:
            part = MIMEBase('application', 'octet-stream')
            part.set_payload(f.read())
            encoders.encode_base64(part)
            part.add_header('Content-Disposition',
                           f'attachment; filename="{filename}"')
            message.attach(part)
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        service.users().messages().send(
            userId='me', body={'raw': raw}
        ).execute()
        return {"status": "sent", "to": to, "subject": subject, "attachment": filename}
    except Exception as e:
        print(f"[SEND EMAIL ATTACHMENT ERROR] {e}")
        return {"status": "error", "message": str(e)}


# ── Drive Functions ───────────────────────────────────────

def search_drive_files(query: str, max_results: int = 5) -> list:
    try:
        service = get_drive_service()
        results = service.files().list(
            q=f"name contains '{query}' and trashed=false",
            pageSize=max_results,
            fields="files(id, name, mimeType, size, modifiedTime)"
        ).execute()
        return results.get('files', [])
    except Exception as e:
        print(f"[DRIVE SEARCH ERROR] {e}")
        return []


def download_drive_file(file_id: str, filename: str) -> str:
    try:
        import io
        from googleapiclient.http import MediaIoBaseDownload
        service = get_drive_service()
        file_meta = service.files().get(fileId=file_id, fields='mimeType,name').execute()
        mime_type = file_meta.get('mimeType', '')
        export_types = {
            'application/vnd.google-apps.spreadsheet': (
                'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', '.xlsx'),
            'application/vnd.google-apps.document': (
                'application/vnd.openxmlformats-officedocument.wordprocessingml.document', '.docx'),
            'application/vnd.google-apps.presentation': (
                'application/vnd.openxmlformats-officedocument.presentationml.presentation', '.pptx'),
        }
        safe_filename = filename.replace('/', '_').replace(' ', '_')
        tmp_path = f"/tmp/{safe_filename}"
        if mime_type in export_types:
            export_mime, ext = export_types[mime_type]
            if not safe_filename.endswith(ext):
                tmp_path = f"/tmp/{safe_filename}{ext}"
            request = service.files().export_media(fileId=file_id, mimeType=export_mime)
        else:
            request = service.files().get_media(fileId=file_id)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            status, done = downloader.next_chunk()
        with open(tmp_path, 'wb') as f:
            f.write(fh.getvalue())
        file_size = os.path.getsize(tmp_path)
        if file_size == 0:
            return ""
        return tmp_path
    except Exception as e:
        print(f"[DRIVE DOWNLOAD ERROR] {e}")
        return ""


# ── Contacts Functions ────────────────────────────────────

def search_contact_email(name: str) -> str:
    try:
        import re
        service = get_gmail_service()
        results = service.users().messages().list(
            userId='me', maxResults=50,
            q=f"to:{name} OR from:{name}"
        ).execute()
        messages = results.get('messages', [])
        for msg in messages:
            detail = service.users().messages().get(
                userId='me', id=msg['id'], format='metadata',
                metadataHeaders=['To', 'From']
            ).execute()
            headers = detail['payload']['headers']
            for h in headers:
                if h['name'] in ['To', 'From'] and name.lower() in h['value'].lower():
                    match = re.search(r'[\w.+-]+@[\w-]+\.[a-zA-Z]+', h['value'])
                    if match:
                        return match.group(0)
        return ""
    except Exception as e:
        print(f"[CONTACT SEARCH ERROR] {e}")
        return ""