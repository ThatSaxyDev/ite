import unittest

from ite.ui.reup.app import ReupPromptTextArea


class ReupPromptTextAreaTests(unittest.TestCase):
    def test_inherits_textarea_paste_binding(self) -> None:
        bindings = {
            part.strip()
            for binding in ReupPromptTextArea.BINDINGS
            for part in str(binding.key).split(",")
        }

        self.assertIn("ctrl+v", bindings)

