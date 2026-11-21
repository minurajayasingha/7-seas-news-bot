"""One-time helper: get the TikTok refresh token for the bot (run it on your own computer).

    python3 tools/tiktok_token.py            (asks for the Client key + Client secret, or reads tools/.tiktok_keys:
                                              two lines "key=…" and "secret=…"; that file is never committed)
    python3 tools/tiktok_token.py --b64      (only if TikTok says the "code_verifier" is wrong: other PKCE style)

Before: in developers.tiktok.com → your app → Login Kit → Desktop, add this Redirect URI exactly:
    http://localhost:3455/callback/
It opens TikTok in your browser, you log in with the 7 Seas News TikTok account and allow access. It saves the
login ENCRYPTED in state/tiktok_token.json (commit it; then TT_REFRESH_TOKEN is not needed) and prints the
REFRESH TOKEN (not with --quiet). Put the three values in GitHub → repo → Settings → Secrets and variables → Actions:
    TT_CLIENT_KEY, TT_CLIENT_SECRET, TT_REFRESH_TOKEN
Never share or commit the refresh token. Only Python's own modules are used (nothing to install).
After the first run the bot keeps the login fresh by itself (saved encrypted in state/tiktok_token.json).
"""
import base64
import hashlib
import hmac
import os
import http.server
import json
import secrets
import socket
import sys
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

PORT = 3455
REDIRECT = f"http://localhost:{PORT}/callback/"
SCOPES = "user.info.basic,video.upload"
WEB_REDIRECT = "https://minurajayasingha.github.io/7-seas-news-bot/tiktok-callback/"   # docs/tiktok-callback/


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KEYS_FILE = os.path.join(ROOT, "tools", ".tiktok_keys")
TOKEN_FILE = os.path.join(ROOT, "state", "tiktok_token.json")


def read_keys():
    vals = {}
    if os.path.exists(KEYS_FILE):
        for line in open(KEYS_FILE, encoding="utf-8"):
            if "=" in line:
                k, v = line.split("=", 1)
                vals[k.strip().lower()] = v.strip().strip('"').strip("'")
    key = vals.get("key") or vals.get("client_key") or input("Client key: ").strip()
    secret = vals.get("secret") or vals.get("client_secret") or input("Client secret: ").strip()
    print(f"Client key: {key[:4]}… ({len(key)} characters) · secret: {len(secret)} characters")
    return key, secret


def save_encrypted(refresh, secret, expires_in):
    """The same encryption as bot/roundup.py tt_encrypt (key made from the client secret)."""
    from datetime import datetime, timedelta, timezone
    root = hashlib.sha256(b"7seas-tiktok-token|" + secret.encode()).digest()
    k_enc = hmac.new(root, b"enc", hashlib.sha256).digest()
    k_mac = hmac.new(root, b"mac", hashlib.sha256).digest()
    nonce, raw = os.urandom(16), refresh.encode()
    stream, i = b"", 0
    while len(stream) < len(raw):
        stream += hmac.new(k_enc, nonce + i.to_bytes(8, "big"), hashlib.sha256).digest()
        i += 1
    ct = bytes(a ^ b for a, b in zip(raw, stream))
    tag = hmac.new(k_mac, nonce + ct, hashlib.sha256).digest()[:16]
    now = datetime.now(timezone.utc)
    with open(TOKEN_FILE, "w", encoding="utf-8") as f:
        json.dump({"data": base64.b64encode(nonce + ct + tag).decode(), "saved_at": now.isoformat(),
                   "refresh_expires_at": (now + timedelta(seconds=int(expires_in or 0))).isoformat()}, f, indent=1)


def exchange(key, secret, code, redirect, verifier=None):
    body = {"client_key": key, "client_secret": secret, "code": code, "grant_type": "authorization_code",
            "redirect_uri": redirect}
    if verifier:
        body["code_verifier"] = verifier
    req = urllib.request.Request("https://open.tiktokapis.com/v2/oauth/token/",
                                 data=urllib.parse.urlencode(body).encode(),
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        return json.loads(e.read() or b"{}")


def finish(tok, secret):
    if "refresh_token" not in tok:
        print("No refresh token in TikTok's answer:", {k: v for k, v in tok.items() if k != "access_token"})
        return
    print("Allowed:", tok.get("scope"), "· valid for about", int(tok.get("refresh_expires_in", 0)) // 86400, "days")
    if "video.upload" not in str(tok.get("scope")):
        print("⚠️ video.upload is missing: add the Content Posting API product to the app, then run this again.")
    save_encrypted(tok["refresh_token"], secret, tok.get("refresh_expires_in"))
    print("\n✅ Login saved (encrypted) in state/tiktok_token.json — commit + sync it.")
    if "--quiet" not in sys.argv:
        print("\nTT_REFRESH_TOKEN (only needed if you don't commit that file):\n")
        print(tok["refresh_token"])


def web_login(key, secret):
    """--web: Login through the website (Login Kit → Web redirect URI = WEB_REDIRECT).
    Step 1 (no --code): opens TikTok. After Allow, the callback page shows an address to copy.
    Step 2: python3 tools/tiktok_token.py --web --code "<that address>"   (the code works once, a few minutes)."""
    state_file = os.path.join(ROOT, "tools", ".tiktok_state")
    if "--code" in sys.argv:
        pasted = sys.argv[sys.argv.index("--code") + 1]
        q = urllib.parse.parse_qs(urllib.parse.urlparse(pasted).query) if "?" in pasted else {"code": [pasted]}
        want = open(state_file).read().strip() if os.path.exists(state_file) else ""
        if want and q.get("state", [want])[0] != want:
            print("That address is from an older login try — run step 1 again.")
            return
        finish(exchange(key, secret, q["code"][0], WEB_REDIRECT), secret)
        return
    state = secrets.token_urlsafe(16)
    with open(state_file, "w") as f:
        f.write(state)
    url = "https://www.tiktok.com/v2/auth/authorize/?" + urllib.parse.urlencode({
        "client_key": key, "scope": SCOPES, "response_type": "code", "redirect_uri": WEB_REDIRECT, "state": state})
    print("\nOpen this link, log in with the 7 Seas News TikTok account, Allow:\n\n" + url + "\n")
    print('Then copy the address the 7 Seas page shows and run:\n  python3 tools/tiktok_token.py --web --code "<address>"')
    webbrowser.open(url)


def main():
    key, secret = read_keys()
    if "--web" in sys.argv:
        return web_login(key, secret)
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
    class Server(http.server.HTTPServer):             # listens on 127.0.0.1 AND ::1 (browsers may use either)
        address_family = socket.AF_INET6

        def server_bind(self):
            self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
            super().server_bind()
    try:
        srv = Server(("::", PORT), Handler)
    except OSError:
        srv = http.server.HTTPServer(("127.0.0.1", PORT), Handler)
    while "code" not in got and "error" not in got:
        srv.handle_request()
    if got.get("error") or got.get("state") != state:
        print("Stopped:", got.get("error_description") or got.get("error") or "wrong state (try again)")
        return
    tok = exchange(key, secret, got["code"], REDIRECT, verifier)
    if "refresh_token" not in tok and "verifier" in json.dumps(tok).lower() and "--b64" not in sys.argv:
        print("→ Run it again with:  python3 tools/tiktok_token.py --b64")
    finish(tok, secret)


if __name__ == "__main__":
    main()
