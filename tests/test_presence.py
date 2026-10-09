import sys
import unittest
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'sys'))
from presence import PauseTimer, Track, build_payload


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


if __name__ == '__main__':
    unittest.main()
