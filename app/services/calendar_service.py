import os
import json
from datetime import datetime, timedelta
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

def get_calendar_service():
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
        from google.oauth2.credentials import Credentials as Creds
        creds = Creds.from_authorized_user_file('token.json')
    
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    
    return build('calendar', 'v3', credentials=creds)

def add_calendar_event(title: str, description: str, start_time: str, duration_hours: int = 1):
    try:
        service = get_calendar_service()
        
        # Parse waktu
        try:
            start = datetime.fromisoformat(start_time)
        except:
            start = datetime.now() + timedelta(days=1)
        
        end = start + timedelta(hours=duration_hours)
        
        event = {
            'summary': title,
            'description': description,
            'start': {
                'dateTime': start.isoformat(),
                'timeZone': 'Asia/Jakarta',
            },
            'end': {
                'dateTime': end.isoformat(),
                'timeZone': 'Asia/Jakarta',
            },
            'reminders': {
                'useDefault': False,
                'overrides': [
                    {'method': 'popup', 'minutes': 30},
                    {'method': 'popup', 'minutes': 10},
                ],
            },
        }
        
        event = service.events().insert(calendarId='primary', body=event).execute()
        return {"status": "success", "event_id": event.get('id'), "link": event.get('htmlLink')}
    except Exception as e:
        return {"status": "error", "message": str(e)}

def get_upcoming_events(max_results=10):
    try:
        service = get_calendar_service()
        now = datetime.utcnow().isoformat() + 'Z'
        events_result = service.events().list(
            calendarId='primary',
            timeMin=now,
            maxResults=max_results,
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        events = events_result.get('items', [])
        return [{"title": e.get('summary'), "start": e.get('start', {}).get('dateTime', ''), "link": e.get('htmlLink')} for e in events]
    except Exception as e:
        return []