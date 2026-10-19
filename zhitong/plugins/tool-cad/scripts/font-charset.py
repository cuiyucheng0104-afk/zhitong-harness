"""Write the character set of the bundled Noto Sans SC subset (GB2312 plus CAD symbols) to the given file.

Usage (fontTools installed):
    python3 -I scripts/font-charset.py charset.txt
    pyftsubset NotoSansSC-Regular.otf --text-file=charset.txt --output-file=assets/fonts/NotoSansSC-Regular-GB2312.otf \
        --layout-features='' --no-hinting --desubroutinize --name-IDs='*' --name-languages='*'
"""

import sys

chars = set()
for hi in range(0xA1, 0xF8):
    for lo in range(0xA1, 0xFF):
        try:
            chars.add(bytes([hi, lo]).decode("gb2312"))
        except UnicodeDecodeError:
            pass
for code in range(0x20, 0x7F):
    chars.add(chr(code))
for code in range(0xA0, 0x180):
    chars.add(chr(code))
for code in range(0x3000, 0x3040):
    chars.add(chr(code))
for code in range(0xFF00, 0xFFF0):
    chars.add(chr(code))
for code in range(0x2460, 0x24A0):
    chars.add(chr(code))
for ch in "ØøΦφ°±²³㎡㎜㎝㎞㎎㎏㏄×÷‰‐–—―‘’“”…※≤≥≠≈∞√∠⊥∥△□○◎◇◆■▲▼→←↑↓·•":
    chars.add(ch)
ordered = sorted(c for c in chars if len(c) == 1)
with open(sys.argv[1], "w", encoding="utf-8") as out:
    out.write("".join(ordered))
print(len(ordered))
