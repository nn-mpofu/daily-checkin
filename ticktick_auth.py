import http.server, urllib.parse, webbrowser, os, json, threading
import urllib.request

CLIENT_ID = os.environ["TICKTICK_CLIENT_ID"]
CLIENT_SECRET = os.environ["TICKTICK_CLIENT_SECRET"]
REDIRECT_URI = "http://localhost:8080/callback"
AUTH_URL = (
    f"https://ticktick.com/oauth/authorize"
    f"?client_id={CLIENT_ID}"
    f"&response_type=code"
    f"&redirect_uri={urllib.parse.quote(REDIRECT_URI)}"
    f"&scope=tasks:write tasks:read"
)

code_holder = {}

class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        if "code" in params:
            code_holder["code"] = params["code"][0]
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"<h2>Authorised! You can close this tab.</h2>")
        threading.Thread(target=self.server.shutdown, daemon=True).start()

    def log_message(self, *args):
        pass

print("\nOpening TickTick in your browser...")
webbrowser.open(AUTH_URL)
server = http.server.HTTPServer(("localhost", 8080), Handler)
server.serve_forever()

code = code_holder["code"]
import base64
creds = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
req = urllib.request.Request(
    "https://ticktick.com/oauth/token",
    data=urllib.parse.urlencode({
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": REDIRECT_URI,
    }).encode(),
    headers={
        "Authorization": f"Basic {creds}",
        "Content-Type": "application/x-www-form-urlencoded",
    },
)
resp = json.loads(urllib.request.urlopen(req).read())
print(f"\nFull response: {json.dumps(resp, indent=2)}")
print(f"\nAccess token:  {resp['access_token']}")
print(f"Refresh token: {resp.get('refresh_token', '(none returned)')}")
print("\nCopy both into your .env file.")
