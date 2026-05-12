#!/usr/bin/env python3
import os
os.environ['TERM_PROGRAM'] = 'Warp'

import pyperclip
pyperclip.copy('test123')
print('After pyperclip.copy:', pyperclip.paste())

import subprocess
proc = subprocess.Popen(['pbcopy'], stdin=subprocess.PIPE)
proc.communicate(input=b'pbcopy_test')
result = subprocess.run(['pbpaste'], capture_output=True, text=True)
print('After pbcopy:', result.stdout.strip())