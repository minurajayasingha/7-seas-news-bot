"""One-time helper: get the TikTok refresh token for the bot (run it on your own computer).

    python3 tools/tiktok_token.py            (asks for the Client key + Client secret)
    python3 tools/tiktok_token.py --b64      (only if TikTok says the "code_verifier" is wrong: other PKCE style)

Before: in developers.tiktok.com → your app → Login Kit → Desktop, add this Redirect URI exactly:
    http://localhost:3455/callback/
It opens TikTok in your browser, you log in with the 7 Seas News TikTok account and allow access, and it
prints the REFRESH TOKEN. Put the three values in GitHub → repo → Settings → Secrets and variables → Actions:
    TT_CLIENT_KEY, TT_CLIENT_SECRET, TT_REFRESH_TOKEN
Never share or commit the refresh token. Only Python's own modules are used (nothing to install).
After the first run the bot keeps the login fresh by itself (saved encrypted in state/tiktok_token.json).
"""
import base64
import hashlib
import http.server
import json
import secrets
import sys
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

PORT = 3455
REDIRECT = f"http://localhost:{PORT}/callback/"
SCOPES = "user.info.basic,video.upload"


def main():
    key = input("Client key: ").strip()
    secret = input("Client secret: ").strip()
    verifier = secrets.token_urlsafe(64)[:64]
    digest = hashlib.sha256(verifier.encode()).digest()
    if "--b64" in sys.argv:                          # standard PKCE (RFC 7636)
        challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    else:                                            # what TikTok's desktop docs say: hex of SHA-256
        challenge = digest.hex()
    state = secrets.token_urlsafe(16)
    url = "https://www.tiktok.com/v2/auth/authorize/?" + urllib.parse.urlencode({
        "client_key": key, "scope": SCOPES, "response_type": "code", "redirect_uri": REDIRECT, "state": state,
        "code_challenge": challenge, "code_challenge_method": "S256"})
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

    print("\nOpening TikTok in your browser. If it doesn't open, copy this link into the browser:\n\n" + url + "\n")
    webbrowser.open(url)
    srv = http.server.HTTPServer(("127.0.0.1", PORT), Handler)
    while "code" not in got and "error" not in got:
        srv.handle_request()
    if got.get("error") or got.get("state") != state:
        print("Stopped:", got.get("error_description") or got.get("error") or "wrong state (try again)")
        return
    data = urllib.parse.urlencode({"client_key": key, "client_secret": secret, "code": got["code"],
                                   "grant_type": "authorization_code", "redirect_uri": REDIRECT,
                                   "code_verifier": verifier}).encode()
    req = urllib.request.Request("https://open.tiktokapis.com/v2/oauth/token/", data=data,
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            tok = json.load(r)
    except urllib.error.HTTPError as e:
        tok = json.loads(e.read() or b"{}")
    if "refresh_token" not in tok:
        print("No refresh token in TikTok's answer:", {k: v for k, v in tok.items() if k != "access_token"})
        if "verifier" in json.dumps(tok).lower() and "--b64" not in sys.argv:
            print("→ Run it again with:  python3 tools/tiktok_token.py --b64")
        return
    print("Allowed:", tok.get("scope"), "· valid for about", int(tok.get("refresh_expires_in", 0)) // 86400, "days")
    if "video.upload" not in str(tok.get("scope")):
        print("⚠️ video.upload is missing: add the Content Posting API product to the app, then run this again.")
    print("\n✅ TT_REFRESH_TOKEN (copy it into the GitHub secret, then close this window):\n")
    print(tok["refresh_token"])


if __name__ == "__main__":
    main()
