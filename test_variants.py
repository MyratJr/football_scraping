# test_variants.py  (python -m app.test_variants)
from app.tasks.translator_browser import BrowserTranslator, clean_text

TEXT = """𝐁𝐞𝐥𝐥𝐢𝐧𝐠𝐡𝐚𝐦 𝐱𝟐 𝐢𝐧 𝐄𝐧𝐠𝐥𝐚𝐧𝐝 𝐭𝐫𝐚𝐢𝐧𝐢𝐧𝐠 𝐭𝐨𝐝𝐚𝐲! 🤩🏴󠁧󠁢󠁥󠁮󠁧󠁿

All smiles for Jude and Jobe Bellingham, playing together for the very first time at professional level for England NT 🫂✨

𝐏𝐫𝐨𝐮𝐝 𝐦𝐨𝐦𝐞𝐧𝐭 𝐟𝐨𝐫 𝐭𝐡𝐞 𝐰𝐡𝐨𝐥𝐞 𝐟𝐚𝐦𝐢𝐥𝐲. 🫲🏽🫱🏽"""

with BrowserTranslator(headless=True) as t, open("variants.txt", "w", encoding="utf-8") as f:
    f.write("A) ORIGINAL letters, whole text in one request\n")
    f.write(t._translate_piece(TEXT) + "\n\n")

    f.write("B) CLEANED letters, whole text in one request\n")
    f.write(t._translate_piece(clean_text(TEXT)) + "\n\n")

    f.write("C) ORIGINAL letters, line by line\n")
    f.write("\n".join(l if not l.strip() else t._translate_piece(l) for l in TEXT.split("\n")) + "\n\n")

    f.write("D) CLEANED letters, line by line (what your service did)\n")
    f.write("\n".join(l if not l.strip() else t._translate_piece(l) for l in clean_text(TEXT).split("\n")) + "\n")
print("saved variants.txt")