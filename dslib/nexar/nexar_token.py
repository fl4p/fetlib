"""Main entry point to the service."""
import base64
import hashlib
import os
import re
import webbrowser
import requests
import http.server
import getpass

from local_service import handlerFactory
from oauthlib.oauth2 import BackendApplicationClient
from oauthlib.oauth2.rfc6749.errors import MissingTokenError
from requests_oauthlib import OAuth2Session

HOST_NAME = "localhost"
PORT = 3000
REDIRECT_URI = "http://localhost:3000/login"
AUTHORITY_URL = "https://identity.nexar.com/connect/authorize"
PROD_TOKEN_URL = "https://identity.nexar.com/connect/token"

def get_token(client_id, client_secret, scopes):
    """Return the Nexar token from the client_id and client_secret provided."""
    if not client_id or not client_secret:
        raise Exception("client_id and/or client_secret are empty")
    if not scopes:
        raise Exception("scope is empty")
    if (scopes != ["supply.domain"]):
        return get_token_with_login(client_id, client_secret, scopes)

    client = BackendApplicationClient(client_id=client_id)
    oauth = OAuth2Session(client=client)
    token = {}
    try:
        token = oauth.fetch_token(
            token_url=PROD_TOKEN_URL,
            client_id=client_id,
            client_secret=client_secret,
            include_client_id=True,
        )
    except MissingTokenError:
        raise

    return token


def get_token_with_login(client_id, client_secret, scopes):
    """Open the Nexar authorization url from the client_id and scope provided."""
    if not client_id or not client_secret:
        raise Exception("client_id and/or client_secret are empty")
    if not scopes:
        raise Exception("scope is empty")

    token = {}
    scope_list = ["openid", "profile", "email"] + scopes

    # PCKE code verifier and challenge
    code_verifier = base64.urlsafe_b64encode(os.urandom(40)).decode("utf-8")
    code_verifier = re.sub("[^a-zA-Z0-9]+", "", code_verifier)

    code_challenge = hashlib.sha256(code_verifier.encode("utf-8")).digest()
    code_challenge = base64.urlsafe_b64encode(code_challenge).decode("utf-8")
    code_challenge = code_challenge.replace("=", "")

    oauth = OAuth2Session(client_id, redirect_uri=REDIRECT_URI, scope=scope_list)
    authorization_url, _ = oauth.authorization_url(
        url=AUTHORITY_URL,
        code_challenge=code_challenge,
        code_challenge_method="S256",
    )
    authorization_url = authorization_url.replace("+", "%20")

    try:
        # Start the local service
        code = []
        httpd = http.server.HTTPServer((HOST_NAME, PORT), handlerFactory(code))

        # Request login page
        webbrowser.open_new(authorization_url)

        while (len(code) == 0):
            httpd.handle_request()

        httpd.server_close()
        auth_code = code[0]

        # Exchange code for token
        token = requests.post(
            url=PROD_TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": REDIRECT_URI,
                "code": auth_code,
                "code_verifier": code_verifier,
            },
            allow_redirects=False,
        ).json()

    except Exception:
        raise

    return token

def get_token_with_resource_password(client_id, client_secret):
    """Open the Nexar authorization url from the client_id and scope provided."""
    if not client_id or not client_secret:
        raise Exception("client_id and/or client_secret are empty")

    username = input("Enter username: ")
    password = getpass.getpass("Enter password: ")

    token = {}
    try:
        token = requests.post(
            url=PROD_TOKEN_URL,
            data={
                "grant_type": "password",
                "client_id": client_id,
                "client_secret": client_secret,
                "username": username,
                "password": password,
            },
        ).json()

    except Exception:
        raise

    return token


"""Sample for getting nexar token."""
import argparse
from nexar_token import get_token, get_token_with_resource_password

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("client_id", help="The client ID.", type=str)
    parser.add_argument("client_secret", help="The client secret.", type=str)
    parser.add_argument("scope", help="The resources needed for authorization.", nargs="*")
    parser.add_argument("-p", help="option for using user credentials", action="store_true")
    args = parser.parse_args()

    if (args.p):
        print(get_token_with_resource_password(args.client_id, args.client_secret)["access_token"])
        raise SystemExit

    token = get_token(args.client_id, args.client_secret, args.scope)["access_token"]
    print(token)