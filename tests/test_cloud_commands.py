import unittest

from ite.commands import build_registry


class CloudCommandRegistryTests(unittest.TestCase):
    def test_account_status_replaces_the_cloud_command_namespace(self) -> None:
        registry = build_registry()

        self.assertIsNotNone(registry.get("/status"))
        self.assertIsNotNone(registry.get("/login"))
        self.assertIsNotNone(registry.get("/logout"))
        self.assertIsNone(registry.get("/cloud"))


if __name__ == "__main__":
    unittest.main()
