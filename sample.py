from dotenv import load_dotenv
import os
import requests
from requests.auth import HTTPBasicAuth

# Load environment variables
load_dotenv()

JIRA_BASE_URL = os.getenv("JIRA_BASE_URL")
JIRA_EMAIL = os.getenv("JIRA_EMAIL")
JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN")

SPRINT_ID = 2399

url = f"{JIRA_BASE_URL}/rest/agile/1.0/sprint/{SPRINT_ID}/issue"

response = requests.get(
    url,
    auth=HTTPBasicAuth(JIRA_EMAIL, JIRA_API_TOKEN),
    headers={
        "Accept": "application/json"
    }
)

print("=" * 80)
print(f"Status Code : {response.status_code}")
print("=" * 80)

if response.status_code == 200:

    data = response.json()
    issues = data["issues"]

    print(f"\nTotal Issues in Sprint : {len(issues)}\n")

    print("-" * 120)

    for issue in issues:

        fields = issue["fields"]

        assignee = fields.get("assignee")

        assignee_name = (
            assignee["displayName"]
            if assignee
            else "Unassigned"
        )

        issue_type = fields["issuetype"]["name"]

        status = fields["status"]["name"]

        print(f"Key        : {issue['key']}")
        print(f"Summary    : {fields['summary']}")
        print(f"Issue Type : {issue_type}")
        print(f"Status     : {status}")
        print(f"Assignee   : {assignee_name}")
        print("-" * 120)

else:
    print(response.text)