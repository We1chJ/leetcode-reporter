<p align="center">
  <img src="web/logo.svg" width="88" alt="">
</p>

<h1 align="center">LeetCode Contest Reporter</h1>

<p align="center">
  Finds contest submissions that were pasted in rather than written,<br>
  writes the violation report, and files it.
</p>

<p align="center">
  <em>Runs locally. Fully deterministic — no model, no API key.</em>
</p>

---

## Start it

**Windows**

```
start_chrome.bat     sign in to LeetCode, leave the window open
run.bat              opens http://127.0.0.1:8000
```

**macOS / Linux**

```
./start_chrome.sh    sign in to LeetCode, leave the window open
./run.sh             opens http://127.0.0.1:8000
```

Then in the dashboard: enter a contest number, choose how many contestants to
scan, and press **Start scanning**.

Needs Python 3.11+ and Google Chrome. Both windows stay open while a scan runs.
