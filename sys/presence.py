from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import sys
import time
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

LOG = logging.getLogger("yandex_presence")
CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.json"
sys.path.insert(0, str(Path(__file__).with_name(".deps")))


@dataclass(frozen=True)
class Track:
    title: str
    artist: str
    album: str
    position: float
    duration: float
    playing: bool

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.title, self.artist, self.album)


@dataclass
class PauseTimer:
    timeout: float = 300
    signature: tuple | None = None
    since: float | None = None

    def expired(self, track: Track | None, now: float) -> bool:
        if track is None or track.playing:
            self.signature = None
            self.since = None
            return False
        signature = (track.key, round(track.position, 1))
        if signature != self.signature:
            self.signature = signature
            self.since = now
        return self.since is not None and now - self.since >= self.timeout


def seconds(value: object) -> float:
    """WinRT duration values may be timedelta-like or numeric."""
    if hasattr(value, "total_seconds"):
        return float(value.total_seconds())
    if hasattr(value, "seconds"):
        return float(value.seconds)
    return float(value or 0)


def source_matches(source: str, keywords: list[str]) -> bool:
    normalized = re.sub(r"[^\w]", "", source.casefold())
    return any(re.sub(r"[^\w]", "", word.casefold()) in normalized for word in keywords if word)


def compute_timestamps(track: Track, now_ms: int) -> tuple[int, int] | None:
    if not track.playing or track.duration <= 0:
        return None
    position = max(0, min(track.position, track.duration))
    start = now_ms - round(position * 1000)
    end = start + round(track.duration * 1000)
    return start, end


def build_payload(track: Track, image: str | None, link: str | None, activity_type: object, now_ms: int, config: dict | None = None) -> dict:
    config = config or {}
    state = track.artist or track.album or "Яндекс Музыка"
    values = dict(title=track.title, artist=state, album=track.album)
    details = config.get("details_template", "{title}").format_map(values)
    state = config.get("state_template", "{artist}").format_map(values)
    if not track.playing and track.title != "Яндекс Музыка открыта":
        state += " • Пауза"
    payload = {
        "activity_type": activity_type,
        "details": details[:128],
        "state": state[:128],
        "instance": track.playing,
    }
    if image and config.get("show_cover", True):
        payload["large_image"] = image
    if link:
        if config.get("link_title", True):
            payload["details_url"] = link
        if config.get("show_button", True):
            payload["buttons"] = [{"label": config.get("button_label", "Открыть трек"), "url": link}]
    timestamps = compute_timestamps(track, now_ms) if config.get("show_timing", True) else None
    if timestamps:
        payload.update(start=timestamps[0], end=timestamps[1])
    return payload


def player_running(process_names: list[str]) -> bool:
    import psutil

    wanted = {name.casefold() for name in process_names}
    for process in psutil.process_iter(["name"]):
        try:
            if (process.info["name"] or "").casefold() in wanted:
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return False


def _normalized(text: str) -> str:
    return re.sub(r"[^\w]+", "", text.casefold())


def find_cover(track: Track) -> tuple[str | None, str | None]:
    """Best-effort public search; never substitute an unrelated cover."""
    query = urlencode({"text": f"{track.artist} {track.title}", "type": "track", "page": 0})
    request = Request(
        f"https://api.music.yandex.net/search?{query}",
        headers={"User-Agent": "YandexDiscordPresence/1.0"},
    )
    try:
        with urlopen(request, timeout=5) as response:
            data = json.load(response)
        results = data.get("result", {}).get("tracks", {}).get("results", [])
        for item in results[:10]:
            title = str(item.get("title", ""))
            artists = [str(a.get("name", "")) for a in item.get("artists", [])]
            if _normalized(title) != _normalized(track.title):
                continue
            if track.artist and not any(_normalized(a) in _normalized(track.artist) or _normalized(track.artist) in _normalized(a) for a in artists if a):
                continue
            albums = item.get("albums") or []
            track_id = str(item.get("id", ""))
            album_id = str(albums[0].get("id", "")) if albums else ""
            link = f"https://music.yandex.ru/album/{album_id}/track/{track_id}" if album_id and track_id else None
            cover = item.get("coverUri") or (albums[0].get("coverUri") if albums else None)
            image_url = (
                "https://" + str(cover).removeprefix("https://").removeprefix("http://").replace("%%", "400x400")
                if cover else None
            )
            if image_url or link:
                return image_url, link
    except (OSError, ValueError, KeyError, TypeError) as exc:
        LOG.debug("Cover search unavailable: %s", exc)
    return None, None


async def read_track(manager: object, keywords: list[str]) -> Track | None:
    candidates = [s for s in manager.get_sessions() if source_matches(s.source_app_user_model_id, keywords)]
    for session in candidates:
        playback = session.get_playback_info()
        if playback is None:
            continue
        status = playback.playback_status.name.upper()
        if status not in ("PLAYING", "PAUSED"):
            continue
        media = await session.try_get_media_properties_async()
        if media is None or not str(media.title or "").strip():
            continue
        timeline = session.get_timeline_properties()
        position = seconds(timeline.position)
        duration = max(0, seconds(timeline.end_time) - seconds(timeline.start_time))
        if status == "PLAYING" and timeline.last_updated_time:
            updated = timeline.last_updated_time
            if updated.tzinfo is None:
                updated = updated.replace(tzinfo=timezone.utc)
            position += max(0, (datetime.now(timezone.utc) - updated).total_seconds())
        return Track(
            title=str(media.title).strip(),
            artist=str(media.artist or "").strip(),
            album=str(media.album_title or "").strip(),
            position=max(0, min(position, duration)) if duration else max(0, position),
            duration=duration,
            playing=status == "PLAYING",
        )
    return None


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        raise SystemExit("Создайте config.json в основной папке и укажите discord_application_id.")
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    app_id = str(config.get("discord_application_id", ""))
    if not app_id.isdecimal():
        raise SystemExit("В config.json нужен числовой discord_application_id из Discord Developer Portal.")
    return config


async def run() -> None:
    from winsdk.windows.media.control import GlobalSystemMediaTransportControlsSessionManager
    from pypresence import AioPresence
    from pypresence.types import ActivityType

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list-sessions", action="store_true", help="Show Windows media source IDs and exit")
    parser.add_argument("--background", action="store_true", help="Run without a console (for Task Scheduler)")
    args = parser.parse_args()
    manager = await GlobalSystemMediaTransportControlsSessionManager.request_async()
    if args.list_sessions:
        for session in manager.get_sessions():
            print(session.source_app_user_model_id)
        return

    config = load_config()
    rpc = None
    last_track: Track | None = None
    last_sent_at = 0.0
    cover_cache: dict[tuple[str, str, str], tuple[str | None, str | None]] = {}
    next_connect = 0.0
    poll = max(1, float(config.get("poll_seconds", 2)))
    keywords = config.get("source_keywords") or ["Яндекс Музыка", "Yandex Music", "YandexMusic", "music.yandex", "pulsesync"]
    process_names = config.get("process_names") or ["Яндекс Музыка.exe"]
    LOG.info("Watching Yandex Music media sessions. Press Ctrl+C to stop.")
    running = False
    track = None
    observed_track = None
    pause_timer = PauseTimer(max(1, float(config.get("pause_timeout_seconds", 300))))
    pause_timed_out = False

    try:
        while True:
            try:
                running = player_running(process_names)
                track = await read_track(manager, keywords) if running else None
                if running and track is None:
                    track = replace(observed_track, playing=False) if observed_track else Track("Яндекс Музыка открыта", "Ожидание трека", "", 0, 0, False)
                observed_track = track
                pause_timed_out = pause_timer.expired(track, time.monotonic()) and config.get("hide_after_pause", True)
                active = running and track is not None and not pause_timed_out and (track.playing or not config.get("clear_when_paused", False))
                if pause_timed_out and rpc is not None:
                    try:
                        await rpc.clear()
                    finally:
                        rpc.close()
                        rpc = None
                        last_track = None
                    LOG.info("Pause timeout reached; presence cleared and RPC disconnected")
                if active and rpc is None and time.monotonic() >= next_connect:
                    try:
                        rpc = AioPresence(str(config["discord_application_id"]))
                        await rpc.connect()
                        LOG.info("Connected to Discord")
                    except Exception as exc:
                        rpc = None
                        next_connect = time.monotonic() + 10
                        LOG.warning("Discord unavailable; retrying in 10 seconds: %s", exc)
                if rpc is not None:
                    if not active:
                        if last_track is not None:
                            await rpc.clear()
                            last_track = None
                            LOG.info("Presence cleared")
                    elif (last_track is None or track.key != last_track.key or track.playing != last_track.playing
                          or (track.playing and abs(track.position - (last_track.position + time.monotonic() - last_sent_at)) > 4)
                          or time.monotonic() - last_sent_at > 60):
                        assert track is not None
                        if track.key not in cover_cache:
                            cover_cache[track.key] = await asyncio.to_thread(find_cover, track) if config.get("find_cover_online", True) else (None, None)
                        cover, link = cover_cache[track.key]
                        image = cover or config.get("fallback_image_asset") or None
                        activity_type = getattr(ActivityType, config.get("activity_type", "LISTENING"), ActivityType.LISTENING)
                        payload = build_payload(track, image, link, activity_type, int(time.time() * 1000), config)
                        if last_track is not None and last_track.playing and not track.playing:
                            await rpc.clear()
                        await rpc.update(**payload)
                        last_track = track
                        last_sent_at = time.monotonic()
                        LOG.info("%s — %s%s", track.artist, track.title, " (paused)" if not track.playing else "")
            except Exception as exc:
                LOG.warning("Could not update presence: %s", exc)
                if rpc is not None:
                    try:
                        rpc.close()
                    except Exception:
                        pass
                    rpc = None
                last_track = None
                next_connect = time.monotonic() + 10
            try:
                status_path = Path(__file__).with_name("status.json")
                status_tmp = status_path.with_suffix(".tmp")
                status_tmp.write_text(json.dumps({
                    "pid": os.getpid(), "updated": time.time(), "connected": rpc is not None,
                    "player_running": running, "title": track.title if track else "",
                    "artist": track.artist if track else "", "album": track.album if track else "",
                    "playing": track.playing if track else False,
                    "pause_timed_out": bool(pause_timed_out),
                    "position": track.position if track else 0, "duration": track.duration if track else 0,
                }, ensure_ascii=False), encoding="utf-8")
                status_tmp.replace(status_path)
            except OSError:
                pass
            await asyncio.sleep(poll)
    finally:
        if rpc is not None:
            try:
                await rpc.clear()
                rpc.close()
            except Exception:
                pass


if __name__ == "__main__":
    log_options = {"level": logging.INFO, "format": "%(asctime)s %(levelname)s: %(message)s"}
    if "--background" in sys.argv:
        log_options["filename"] = str(Path(__file__).with_name("presence.log"))
        log_options["encoding"] = "utf-8"
    logging.basicConfig(**log_options)
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("\nStopped")
