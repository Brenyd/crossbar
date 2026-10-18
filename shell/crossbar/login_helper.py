#!/usr/bin/env python3
"""Tiny web-view window used for store sign-ins (GOG, Epic).

    login_helper.py URL MATCH (--param NAME | --json-key KEY)

Opens URL, waits until the page URL contains MATCH, then prints either the
query parameter NAME or KEY from the JSON the page shows. Exit 2 = cancelled.
"""
import argparse
import json
import sys
import time
import urllib.parse

import webview  # python-pywebview (GTK/WebKit backend on Linux)

ap = argparse.ArgumentParser()
ap.add_argument("url")
ap.add_argument("match")
ap.add_argument("--param")
ap.add_argument("--json-key")
args = ap.parse_args()

result = {}


def watch(win):
    while "value" not in result:
        time.sleep(0.5)
        try:
            url = win.get_current_url() or ""
        except Exception:
            return
        if args.match not in url:
            continue
        if args.param:
            val = urllib.parse.parse_qs(urllib.parse.urlparse(url).query).get(args.param, [None])[0]
        else:
            try:
                body = win.evaluate_js("document.body.innerText")
                val = json.loads(body).get(args.json_key)
            except Exception:
                val = None
        if val:
            result["value"] = val
            win.destroy()


win = webview.create_window("Sign in", args.url, width=1100, height=800)
webview.start(watch, win, private_mode=False)  # pywebview runs `watch` on its own thread

if "value" in result:
    print(result["value"])
else:
    sys.exit(2)
