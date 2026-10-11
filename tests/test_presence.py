import sys
import io
import json
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'sys'))
from presence import PauseTimer, Track, build_payload, CoverCache, cover_from_items, web_search_items, find_cover, disconnect_rpc


class PresenceTests(unittest.TestCase):
    def setUp(self):
        self.track = Track('Track', 'Artist', 'Album', 42, 180, False)

    def test_pause_timeout_and_resume(self):
        timer = PauseTimer()
        self.assertFalse(timer.expired(self.track, 0))
        self.assertFalse(timer.expired(self.track, 299.9))
        self.assertTrue(timer.expired(self.track, 300))
        self.assertTrue(timer.expired(self.track, 600))
        self.assertFalse(timer.expired(replace(self.track, playing=True), 601))
        self.assertFalse(timer.expired(self.track, 602))
        self.assertTrue(timer.expired(self.track, 902))

    def test_track_change_seek_and_player_close_reset_timeout(self):
        timer = PauseTimer()
        timer.expired(self.track, 0)
        other = replace(self.track, title='Next track')
        self.assertFalse(timer.expired(other, 250))
        self.assertFalse(timer.expired(other, 549))
        self.assertTrue(timer.expired(other, 550))
        self.assertFalse(timer.expired(replace(other, position=60), 551))
        self.assertFalse(timer.expired(None, 552))
        self.assertFalse(timer.expired(self.track, 1000))

    def test_paused_presence_has_no_timer_or_cover_caption(self):
        payload = build_payload(self.track, 'cover', 'https://music.yandex.ru/album/1/track/2', 2, 100_000)
        self.assertEqual(payload['state'], 'Artist • Пауза')
        for field in ('start', 'end', 'large_text', 'large_url'):
            self.assertNotIn(field, payload)

    def test_formatting_and_optional_fields(self):
        settings = dict(details_template='{artist} — {title}', state_template='{album}',
                        show_cover=False, show_timing=False, show_button=False, link_title=False)
        payload = build_payload(replace(self.track, playing=True), 'cover', 'https://example.com', 2, 100_000, settings)
        self.assertEqual(payload['details'], 'Artist — Track')
        self.assertEqual(payload['state'], 'Album')
        for field in ('start', 'end', 'large_image', 'details_url', 'buttons'):
            self.assertNotIn(field, payload)


class ArtworkTests(unittest.TestCase):
    def setUp(self):
        self.track = Track('Track', 'Artist', 'Album', 0, 180, True)
        self.item = dict(id='123', title='Track', artists=[{'name': 'Artist'}],
                         albumId=456, coverUri='avatars.yandex.net/test/%%')
        patches = [{'op': 'add', 'path': '/search/pagesLoader/items/0',
                    'value': {'type': 'track', 'data': self.item}}]
        self.html = '<script>(window.__STATE_PATCHES__ = window.__STATE_PATCHES__ || []).push(' + json.dumps(patches) + ');</script>'
        self.result = ('https://avatars.yandex.net/test/400x400', 'https://music.yandex.ru/album/456/track/123')

    def test_public_search_and_exact_match(self):
        items = web_search_items(self.html)
        self.assertEqual(cover_from_items(self.track, items), self.result)
        self.assertEqual(cover_from_items(replace(self.track, artist='Another, Artist'), items), self.result)
        self.assertEqual(cover_from_items(replace(self.track, artist='Different artist'), items), (None, None))
        self.assertEqual(cover_from_items(replace(self.track, title='Different track'), items), (None, None))
        self.assertEqual(web_search_items('<script>window.__STATE_PATCHES__.push(not_json());</script>'), [])

    def test_rate_limit_uses_website_and_skips_api_during_cooldown(self):
        error = HTTPError('https://api.music.yandex.net/search', 429, 'Too Many Requests', {'Retry-After': '300'}, None)
        responses = [error, io.BytesIO(self.html.encode()), io.BytesIO(self.html.encode())]
        with patch('presence._api_retry_at', 0), patch('presence._web_retry_at', 0), \
             patch('presence.time.monotonic', return_value=100), \
             patch('presence.urlopen', side_effect=responses) as opener:
            self.assertEqual(find_cover(self.track), self.result)
            self.assertEqual(find_cover(self.track), self.result)
        self.assertEqual(opener.call_count, 3)
        self.assertIn('api.music.yandex.net', opener.call_args_list[0].args[0].full_url)
        self.assertIn('music.yandex.ru/search', opener.call_args_list[2].args[0].full_url)

    def test_failure_cache_expires_and_success_is_reused(self):
        finder = Mock(side_effect=[(None, None), self.result])
        cache = CoverCache(finder)
        self.assertEqual(cache.lookup(self.track, 0), (None, None))
        self.assertEqual(cache.lookup(self.track, 59), (None, None))
        self.assertEqual(finder.call_count, 1)
        self.assertEqual(cache.lookup(self.track, 60), self.result)
        self.assertEqual(cache.lookup(self.track, 600), self.result)
        self.assertEqual(finder.call_count, 2)

    def test_disconnect_closes_transport_without_closing_loop(self):
        rpc = Mock(client_id='123')
        rpc.close.side_effect = RuntimeError('Cannot close a running event loop')
        disconnect_rpc(rpc)
        rpc.sock_writer.close.assert_called_once()
        rpc.close.assert_not_called()
        rpc.loop.close.assert_not_called()


if __name__ == '__main__':
    unittest.main()
