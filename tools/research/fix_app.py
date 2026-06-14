import re
with open("app.py", "r", encoding="utf-8") as f:
    content = f.read()
new_content = re.sub(r"use_container_width=True", "width='stretch'", content)
new_content = re.sub(r"use_container_width=False", "width='content'", new_content)
with open("app.py", "w", encoding="utf-8") as f:
    f.write(new_content)
print("Fixed app.py")
