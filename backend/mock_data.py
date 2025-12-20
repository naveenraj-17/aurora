from datetime import datetime, timedelta

MOCK_EMAILS = [
    {
        "id": "email_001",
        "sender": "newsletter@techdaily.com",
        "subject": "Top Tech Trends of 2025",
        "snippet": "Here are the top 10 technology trends you need to watch out for this year...",
        "body": "Full report on the top tech trends of 2025. AI Agents are taking over...",
        "timestamp": (datetime.now() - timedelta(hours=2)).isoformat()
    },
    {
        "id": "email_002",
        "sender": "boss@company.com",
        "subject": "Project Update Meeting",
        "snippet": "Can we reschedule our meeting to tomorrow at 10 AM?",
        "body": "Hi,\n\nI need to reschedule our project update meeting to tomorrow at 10 AM. Let me know if that works.\n\nThanks,\nBoss",
        "timestamp": (datetime.now() - timedelta(days=1)).isoformat()
    },
    {
        "id": "email_003",
        "sender": "security@bank.com",
        "subject": "Security Alert: New Login",
        "snippet": "We detected a new login to your account from a new device.",
        "body": "We detected a new login to your account from a new device in San Francisco, CA. If this wasn't you, please contact support immediately.",
        "timestamp": (datetime.now() - timedelta(days=2)).isoformat()
    }
]

def get_mock_emails():
    return MOCK_EMAILS

def get_mock_email_by_id(email_id):
    for email in MOCK_EMAILS:
        if email["id"] == email_id:
            return email
    return None
