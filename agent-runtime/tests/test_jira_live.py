import base64
import json
import os
import urllib.request

if not os.getenv("JIRA_API_TOKEN") and os.path.exists("deploy/.env"):
    with open("deploy/.env", "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                val = val.strip().strip('"').strip("'")
                os.environ[key.strip()] = val

JIRA_URL = os.getenv("JIRA_URL", "https://lustrouscx.atlassian.net")
JIRA_USER = os.getenv("JIRA_USER", "lustrouscx@gmail.com")
JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN", "")
ISSUE_KEY = "SCRUM-1"

if not JIRA_API_TOKEN:
    print("ERROR: JIRA_API_TOKEN environment variable is not set or is empty!")
    exit(1)

def test_live_jira():
    url = f"{JIRA_URL}/rest/api/3/issue/{ISSUE_KEY}"
    
    credentials = f"{JIRA_USER}:{JIRA_API_TOKEN}"
    encoded_credentials = base64.b64encode(credentials.encode("utf-8")).decode("utf-8")
    
    req = urllib.request.Request(
        url, 
        headers={
            "Accept": "application/json",
            "Authorization": f"Basic {encoded_credentials}"
        }
    )

    print(f"Connecting to live Jira at {JIRA_URL} for issue {ISSUE_KEY}...")
    try:
        with urllib.request.urlopen(req) as response:
            if response.status == 200:
                data = json.loads(response.read().decode("utf-8"))
                print("\nSUCCESS: Connected to real Jira successfully!")
                print(f"   - Issue Key: {data.get('key')}")
                print(f"   - Summary:   {data.get('fields', {}).get('summary')}")
                print(f"   - Status:    {data.get('fields', {}).get('status', {}).get('name')}")
            else:
                print(f"\nFAILED: Jira returned status code {response.status}")
    except Exception as e:
        print(f"\nERROR: Could not connect to Jira: {e}")

if __name__ == "__main__":
    test_live_jira()