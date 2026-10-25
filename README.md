# URL to Video

Paste a video page URL, get an MP4 back. It comes in two forms that share the
same code:

- **Server version**: a web app that runs as a program under
  [HTTP Server Manager](https://github.com/tallen5431/HTTP_Server), or on its own.
- **Desktop app** (Windows first): the same page in a native window, saving
  straight to your Downloads folder.

Downloading is done by [yt-dlp](https://github.com/yt-dlp/yt-dlp), which
supports YouTube, Vimeo, X/Twitter, Reddit, TikTok, Instagram, and
[1000+ other sites](https://github.com/yt-dlp/yt-dlp/blob/master/supportedsites.md),
plus direct links to video files. ffmpeg merges the separate video and audio
streams and converts anything that isn't already MP4 (for example WebM) to
H.264/AAC, so the file plays everywhere.

## Layout

```
core/      download jobs; runs the yt-dlp executable and parses its progress
web/       Flask page + JSON API (python -m web runs the server version)
desktop/   desktop launcher, smoke test, PyInstaller spec, Windows build script
Start.sh   server-version launcher used by HTTP Server Manager
```

yt-dlp runs as a separate program rather than being imported, so the desktop
app can update it in place (`yt-dlp -U`) without a new release.

## Server version

### Requirements

- Python 3.9+
- ffmpeg: `sudo apt install ffmpeg` / `brew install ffmpeg`

### Running it

**Under HTTP Server Manager:** click **📥 Import from Git**, paste this repo's
URL, and start the new **URL_TO_VIDEO** card. The bundled `Start.sh` creates
a `.venv`, installs the requirements, and listens on port **8090**.

**On its own:**

```bash
./Start.sh                 # http://localhost:8090
PORT=9000 ./Start.sh       # different port
```

`Start.sh` also updates yt-dlp at most once a day. Sites change often enough
that an old yt-dlp stops working, so if a site that used to work starts
failing, restarting the program is usually the fix.

### Using it

Paste a link, optionally pick a maximum quality (best, 1080p, 720p, 480p),
and click **Convert**. Progress shows on the page; when it finishes, click
**Download**. Playlist links download only the single video.

### Settings (environment variables)

| Variable         | Default       | Meaning                                         |
|------------------|---------------|-------------------------------------------------|
| `PORT`           | `8090`        | Port to listen on                               |
| `HOST`           | `0.0.0.0`     | Interface to bind                               |
| `MAX_CONCURRENT` | `2`           | Conversions that run at the same time           |
| `KEEP_HOURS`     | `24`          | Finished files are deleted after this long      |
| `DOWNLOAD_DIR`   | `./downloads` | Where files are stored (cleared on startup)     |

## Desktop app

### Building on Windows

Needs Python 3.10+ on PATH. From the repo folder:

```powershell
powershell -ExecutionPolicy Bypass -File desktop\build_windows.ps1
```

The first run downloads yt-dlp and ffmpeg into `desktop\bin`. The result is
`dist\URLtoVideo\URLtoVideo.exe` (keep the whole folder together) and a zip
of it, `dist\URLtoVideo-windows.zip`.

Every push also builds it on GitHub Actions (**Build Windows app**), runs a
smoke test that converts a test clip with the built exe, and attaches the zip
to the run as an artifact.

### Running from source

```bash
pip install -r desktop/requirements.txt yt-dlp   # plus ffmpeg on PATH
python desktop/main.py              # native window
python desktop/main.py --browser    # open in your browser instead (handy for development)
python desktop/main.py --smoke-test # end-to-end self test
```

### How it behaves

- Saves to the Downloads folder; **Change…** picks another folder, which is
  remembered. Finished items have **Open** and **Show in folder**; **Remove**
  only clears the list entry and never deletes the file.
- App data (settings, the updatable yt-dlp copy, `app.log`) is in
  `%LOCALAPPDATA%\URL to Video`.
- yt-dlp is updated at most once a day in the background on startup.
- The page is served on a random port on 127.0.0.1 only, and refuses requests
  that come from other web pages.
- The bundled ffmpeg is a GPL build; `THIRD_PARTY_NOTICES.txt` and
  `bin\FFMPEG_LICENSE.txt` ship with the app to meet its license terms.

## Notes

- The server version has no login. Anyone who can reach the port can use it
  and use your bandwidth and disk, so keep it on your LAN/Tailscale, like the
  manager.
- Only download content you have the rights to; some sites' terms forbid it.
