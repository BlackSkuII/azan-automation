import unittest
from unittest import mock

from azan import system


class MacAddressTests(unittest.TestCase):
    def test_normalize_accepts_the_usual_forms(self):
        for text in ("aa:bb:cc:dd:ee:ff", "AA-BB-CC-DD-EE-FF", "aabbccddeeff",
                     " aa:bb:cc:dd:ee:ff "):
            self.assertEqual(system.normalize_mac(text), "aa:bb:cc:dd:ee:ff", text)
        # Short groups are padded rather than rejected.
        self.assertEqual(system.normalize_mac("aa:b:c:dd:ee:f"), "aa:0b:0c:dd:ee:0f")

    def test_normalize_rejects_junk(self):
        for text in ("", None, "hello", "aa:bb:cc:dd:ee", "aa:bb:cc:dd:ee:fff",
                     "gg:bb:cc:dd:ee:ff", "aa:bb:cc:dd:ee:ff:00"):
            self.assertIsNone(system.normalize_mac(text), text)

    def test_mac_for_ip_reads_the_neighbour_table(self):
        table = ("IP address       HW type     Flags       HW address            Mask     Device\n"
                 "192.168.1.23     0x1         0x2         AA:BB:CC:DD:EE:FF     *        wlan0\n"
                 "192.168.1.40     0x1         0x0         00:00:00:00:00:00     *        wlan0\n")
        empty_arp = mock.Mock(stdout="")
        with mock.patch("builtins.open", mock.mock_open(read_data=table)), \
             mock.patch.object(system.subprocess, "run", return_value=empty_arp):
            self.assertEqual(system.mac_for_ip("192.168.1.23"), "aa:bb:cc:dd:ee:ff")
            self.assertIsNone(system.mac_for_ip("192.168.1.40"))  # incomplete entry
            self.assertIsNone(system.mac_for_ip("192.168.1.99"))
            self.assertIsNone(system.mac_for_ip(""))

    def test_mac_for_ip_falls_back_to_arp(self):
        result = mock.Mock(stdout="? (192.168.1.30) at AA:BB:CC:DD:EE:FF on en0 ifscope [ethernet]\n")
        with mock.patch("builtins.open", side_effect=OSError), \
             mock.patch.object(system.subprocess, "run", return_value=result):
            self.assertEqual(system.mac_for_ip("192.168.1.30"), "aa:bb:cc:dd:ee:ff")

    def test_mac_for_ip_gives_up_quietly(self):
        with mock.patch("builtins.open", side_effect=OSError), \
             mock.patch.object(system.subprocess, "run", side_effect=OSError):
            self.assertIsNone(system.mac_for_ip("192.168.1.30"))


if __name__ == "__main__":
    unittest.main()
