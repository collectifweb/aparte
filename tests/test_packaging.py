import sys
import unittest
from pathlib import Path

PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"


@unittest.skipUnless(sys.version_info >= (3, 11), "tomllib is stdlib only on 3.11+")
class PackagingMetadataTest(unittest.TestCase):
    """The macOS packaging seam must stay inert off a Mac, and both OS
    classifiers must coexist. tomllib ships with 3.11+; on 3.10 this guard skips
    rather than pull in a parser just for a metadata check."""

    def setUp(self):
        import tomllib

        self.project = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]

    def test_macos_extra_exists_and_every_dep_is_darwin_gated(self):
        deps = self.project["optional-dependencies"]["macos"]
        self.assertTrue(deps, "the macos extra must not be empty")
        for dep in deps:
            self.assertIn(
                "sys_platform == 'darwin'",
                dep,
                f"macos dependency is not gated to Darwin: {dep!r}",
            )

    def test_both_linux_and_macos_classifiers_are_present(self):
        classifiers = self.project["classifiers"]
        self.assertIn("Operating System :: POSIX :: Linux", classifiers)
        self.assertIn("Operating System :: MacOS :: MacOS X", classifiers)


if __name__ == "__main__":
    unittest.main()
