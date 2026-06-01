import unittest

from whispr_flow_linux.cli import build_parser


class CliParserTest(unittest.TestCase):
    def test_dictate_defaults_to_paste_and_polish(self):
        args = build_parser().parse_args(["dictate"])
        self.assertEqual(args.command, "dictate")
        self.assertEqual(args.target, "paste")
        self.assertFalse(args.no_polish)
        self.assertIsNone(args.style)

    def test_dictate_can_copy_without_polish(self):
        args = build_parser().parse_args(["dictate", "--target", "copy", "--no-polish"])
        self.assertEqual(args.target, "copy")
        self.assertTrue(args.no_polish)

    def test_toggle_defaults_to_paste_and_polish(self):
        args = build_parser().parse_args(["toggle"])
        self.assertEqual(args.command, "toggle")
        self.assertEqual(args.target, "paste")
        self.assertFalse(args.no_polish)

    def test_toggle_status_flag(self):
        args = build_parser().parse_args(["toggle", "--status"])
        self.assertTrue(args.status)

    def test_install_desktop_parser(self):
        args = build_parser().parse_args(["install-desktop", "--print"])
        self.assertEqual(args.command, "install-desktop")
        self.assertTrue(args.print)


if __name__ == "__main__":
    unittest.main()
