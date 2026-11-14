import unittest
from unittest.mock import call, patch

import play_azan
from azan import player


class PlayerVolumeTests(unittest.TestCase):
    @patch("azan.player.time.sleep")
    @patch("azan.player._run", return_value=True)
    def test_sets_requested_volume_before_cast(self, run, sleep):
        self.assertTrue(player.play_azan("catt", "Nest", "azan.mp3", 35))
        self.assertEqual(run.call_args_list, [
            call("catt", "Nest", "volume", "35"),
            call("catt", "Nest", "cast", "azan.mp3"),
        ])


class PlaybackCleanupTests(unittest.TestCase):
    def run_main(self, playback_result=True, sleep_exception=None):
        cfg = {"device_name": "Nest", "azan_file": "audio/azan.mp3", "azan_duration": 60}
        with patch.object(play_azan.sys, "argv", ["play_azan.py", "35"]), \
             patch.object(play_azan.config, "load_config_or_exit", return_value=cfg), \
             patch.object(play_azan.config, "get", side_effect=lambda cfg, key: cfg[key]), \
             patch.object(play_azan, "get_venv_catt", return_value="catt"), \
             patch.object(play_azan.tv_control, "pause_tv", return_value=True), \
             patch.object(play_azan.tv_control, "resume_tv") as resume, \
             patch.object(play_azan.player, "play_azan", return_value=playback_result), \
             patch.object(play_azan.player, "set_volume", return_value=True) as volume, \
             patch.object(play_azan.time, "sleep", side_effect=sleep_exception) as sleep:
            try:
                play_azan.main()
            finally:
                volume.assert_called_once_with("catt", "Nest", 100)
                resume.assert_called_once_with(cfg)
                if playback_result:
                    sleep.assert_called_once_with(60)

    def test_resets_after_playback(self):
        self.run_main()

    def test_resets_after_cast_failure(self):
        with self.assertRaises(SystemExit):
            self.run_main(playback_result=False)

    def test_resets_after_interruption(self):
        with self.assertRaises(KeyboardInterrupt):
            self.run_main(sleep_exception=KeyboardInterrupt())


if __name__ == "__main__":
    unittest.main()
