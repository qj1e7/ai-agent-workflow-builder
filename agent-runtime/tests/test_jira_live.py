import json
import urllib.request
import base64

JIRA_URL = "https://lustrouscx.atlassian.net"
JIRA_USER = "lustrouscx@gmail.com"
JIRA_API_TOKEN = "ATATT3xFfGF0htRCgNmn1sQGe1DE09XJX-NV36C428bvoUa5fAl0gXt6RgDg9QqrmydhRjbKgkqv8rTNcTk9K2MX5at_NwfURBMLYC7vJ9Mtny3-WW6CFGXzZCQiLpRNSaYS0n91QkQGmL31UtEHb1n2-25BCgOA-F5VH_5p9-AkaPoA2ALlS3E=D2097BB1"
ISSUE_KEY = "SCRUM-1"

def test_live_jira():
    url = f"{JIRA_URL}/rest/api/3/issue/{ISSUE_KEY}"
    
    # Construct Basic Auth header
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
                print("\n SUCCESS: Connected to real Jira successfully!")
                print(f"   - Issue Key: {data.get('key')}")
                print(f"   - Summary:   {data.get('fields', {}).get('summary')}")
                print(f"   - Status:    {data.get('fields', {}).get('status', {}).get('name')}")
            else:
                print(f"\n FAILED: Jira returned status code {response.status}")
    except Exception as e:
        print(f"\n ERROR: Could not connect to Jira: {e}")

if __name__ == "__main__":
    test_live_jira()