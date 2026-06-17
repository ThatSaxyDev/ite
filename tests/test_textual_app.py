#!/usr/bin/env python3
from textual.app import App

class TestApp(App):
    def copy_to_clipboard(self, text):
        import subprocess
        proc = subprocess.Popen(['pbcopy'], stdin=subprocess.PIPE)
        proc.communicate(input=text.encode('utf-8'))
        print(f'Copied: {text!r}')
        self.notify('Copied!')

app = TestApp()
app.run()