"""One-time helper: get the YouTube refresh token for the bot (run it on your own computer, once).

    python3 tools/youtube_token.py                         (asks for the Client ID + secret)
    python3 tools/youtube_token.py ~/Downloads/client_secret_….json   (reads them from the downloaded file)

It asks for your OAuth "Client ID" and "Client secret" (Google Cloud → APIs & Services → Credentials →
your "Desktop app" client), opens Google in your browser, you log in with the account that owns the
YouTube channel and allow access, and it prints the REFRESH TOKEN.
Put the three values in GitHub → repo → Settings → Secrets and variables → Actions:
    YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN
Never share or commit the refresh token. Only Python's own modules are used (nothing to install).
"""
import http.server
import json
import secrets
import socket
import urllib.parse
import urllib.request
import webbrowser

SCOPES = "https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube"


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def main():
    import sys
    if len(sys.argv) > 1:                       # the JSON file downloaded from Google Cloud (Clients → Download JSON)
        with open(sys.argv[1], encoding="utf-8") as f:
            j = json.load(f)
        j = j.get("installed") or j.get("web") or j
        cid, csec = j["client_id"], j["client_secret"]
        print("Read the Client ID + secret from", sys.argv[1])
    else:
        cid = input("Client ID: ").strip()
        csec = input("Client secret: ").strip()
    port = free_port()
    redirect = f"http://127.0.0.1:{port}"
    state = secrets.token_urlsafe(16)
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode({
        "client_id": cid, "redirect_uri": redirect, "response_type": "code", "scope": SCOPES,
        "access_type": "offline", "prompt": "consent", "state": state})
    got = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            got.update({k: v[0] for k, v in q.items()})
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write("<h2>Done — go back to the terminal.</h2>".encode())

        def log_message(self, *a):
            pass

    print("\nOpening Google in your browser. If it doesn't open, copy this link into the browser:\n\n" + url + "\n")
    webbrowser.open(url)
    srv = http.server.HTTPServer(("127.0.0.1", port), Handler)
    while "code" not in got and "error" not in got:
        srv.handle_request()
    if got.get("error") or got.get("state") != state:
        print("Stopped:", got.get("error") or "wrong state (try again)")
        return
    data = urllib.parse.urlencode({"code": got["code"], "client_id": cid, "client_secret": csec,
                                   "redirect_uri": redirect, "grant_type": "authorization_code"}).encode()
    with urllib.request.urlopen("https://oauth2.googleapis.com/token", data=data, timeout=30) as r:
        tok = json.load(r)
    if "refresh_token" not in tok:
        print("No refresh token in Google's answer:", {k: v for k, v in tok.items() if k != "access_token"})
        return
    print("\n✅ YT_REFRESH_TOKEN (copy it into the GitHub secret, then close this window):\n")
    print(tok["refresh_token"])


if __name__ == "__main__":
    main()
