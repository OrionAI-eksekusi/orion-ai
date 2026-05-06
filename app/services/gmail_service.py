import os
import json
import base64
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

def get_gmail_service():
    creds = None
    token_json = os.getenv("GMAIL_TOKEN_JSON")
    if token_json:
        token_data = json.loads(token_json)
        creds = Credentials(
            token=token_data.get("token"),
            refresh_token=token_data.get("refresh_token"),
            token_uri=token_data.get("token_uri"),
            client_id=token_data.get("client_id"),
            client_secret=token_data.get("client_secret"),
            scopes=token_data.get("scopes")
        )
    elif os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return build('gmail', 'v1', credentials=creds)

def get_drive_service():
    creds = None
    token_json = os.getenv("GMAIL_TOKEN_JSON")
    if token_json:
        token_data = json.loads(token_json)
        creds = Credentials(
            token=token_data.get("token"),
            refresh_token=token_data.get("refresh_token"),
            token_uri=token_data.get("token_uri"),
            client_id=token_data.get("client_id"),
            client_secret=token_data.get("client_secret"),
            scopes=token_data.get("scopes")
        )
    elif os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return build('drive', 'v3', credentials=creds)

def get_recent_emails(max_results=5):
    try:
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
        return []

def send_email(to: str, subject: str, body: str):
    try:
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
        return {"status": "error", "message": str(e)}

def send_email_with_attachment(to: str, subject: str, body: str, file_path: str, filename: str):
    """Kirim email dengan attachment file"""
    try:
        service = get_gmail_service()

        message = MIMEMultipart()
        message['to'] = to
        message['subject'] = subject
        message.attach(MIMEText(body, 'plain'))

        # Attach file
        with open(file_path, 'rb') as f:
            part = MIMEBase('application', 'octet-stream')
            part.set_payload(f.read())
            encoders.encode_base64(part)
            part.add_header('Content-Disposition', f'attachment; filename="{filename}"')
            message.attach(part)

        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        service.users().messages().send(
            userId='me', body={'raw': raw}
        ).execute()
        return {"status": "sent", "to": to, "subject": subject, "attachment": filename}
    except Exception as e:
        return {"status": "error", "message": str(e)}

def search_drive_files(query: str, max_results: int = 5) -> list:
    """Cari file di Google Drive"""
    try:
        service = get_drive_service()
        results = service.files().list(
            q=f"name contains '{query}' and trashed=false",
            pageSize=max_results,
            fields="files(id, name, mimeType, size, modifiedTime)"
        ).execute()
        files = results.get('files', [])
        return files
    except Exception as e:
        print(f"[DRIVE ERROR] {e}")
        return []

def download_drive_file(file_id: str, filename: str) -> str:
    """Download file dari Google Drive ke /tmp"""
    try:
        service = get_drive_service()
        import io
        from googleapiclient.http import MediaIoBaseDownload

        # Cek apakah Google Docs (perlu export)
        file_meta = service.files().get(fileId=file_id, fields='mimeType,name').execute()
        mime_type = file_meta.get('mimeType', '')

        export_types = {
            'application/vnd.google-apps.spreadsheet': ('application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', '.xlsx'),
            'application/vnd.google-apps.document': ('application/vnd.openxmlformats-officedocument.wordprocessingml.document', '.docx'),
            'application/vnd.google-apps.presentation': ('application/vnd.openxmlformats-officedocument.presentationml.presentation', '.pptx'),
        }

        tmp_path = f"/tmp/{filename}"

        if mime_type in export_types:
            export_mime, ext = export_types[mime_type]
            if not filename.endswith(ext):
                tmp_path = f"/tmp/{filename}{ext}"
            request = service.files().export_media(fileId=file_id, mimeType=export_mime)
        else:
            request = service.files().get_media(fileId=file_id)

        with io.FileIO(tmp_path, 'wb') as fh:
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()

        return tmp_path
    except Exception as e:
        print(f"[DRIVE DOWNLOAD ERROR] {e}")
        return ""

def search_contact_email(name: str) -> str:
    """Cari email kontak berdasarkan nama"""
    try:
        service = get_gmail_service()
        # Cari di sent emails untuk menemukan email kontak
        results = service.users().messages().list(
            userId='me',
            maxResults=50,
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
                    import re
                    match = re.search(r'[\w.+-]+@[\w-]+\.[a-zA-Z]+', h['value'])
                    if match:
                        return match.group(0)
        return ""
    except Exception as e:
        print(f"[CONTACT ERROR] {e}")
        return ""