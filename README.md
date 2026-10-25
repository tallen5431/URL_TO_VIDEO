# URL to Video

A small web app: paste a video page URL, get an MP4 back. It's built to run
as a program under [HTTP Server Manager](https://github.com/tallen5431/HTTP_Server),
but it also runs on its own.

Downloading is done by [yt-dlp](https://github.com/yt-dlp/yt-dlp), which
supports YouTube, Vimeo, X/Twitter, Reddit, TikTok, Instagram, and
[1000+ other sites](https://github.com/yt-dlp/yt-dlp/blob/master/supportedsites.md),
plus direct links to video files. ffmpeg merges the separate video and audio
streams and converts anything that isn't already MP4 (for example WebM) to
H.264/AAC, so the file plays everywhere.

## Requirements

- Python 3.9+
- ffmpeg: `sudo apt install ffmpeg` / `brew install ffmpeg`

## Running it

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

## Using it

Paste a link, optionally pick a maximum quality (best, 1080p, 720p, 480p),
and click **Convert**. Progress shows on the page; when it finishes, click
**Download**. Playlist links download only the single video.

## Settings (environment variables)

| Variable         | Default       | Meaning                                         |
|------------------|---------------|-------------------------------------------------|
| `PORT`           | `8090`        | Port to listen on                               |
| `HOST`           | `0.0.0.0`     | Interface to bind                               |
| `MAX_CONCURRENT` | `2`           | Conversions that run at the same time           |
| `KEEP_HOURS`     | `24`          | Finished files are deleted after this long      |
| `DOWNLOAD_DIR`   | `./downloads` | Where files are stored (cleared on startup)     |

## Notes

- There's no login. Anyone who can reach the port can use it and use your
  bandwidth and disk, so keep it on your LAN/Tailscale, like the manager.
- Only download content you have the rights to; some sites' terms forbid it.
