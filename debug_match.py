with open("data/corpus/clean/emergency/als-algorithm.txt", "r", encoding="utf-8-sig") as f:
    content = f.read()

search = "Immediately resume CPR for 2 minutes"
if search in content:
    print("MATCH FOUND")
else:
    print("NO MATCH")
    for line in content.split("\n"):
        if "resume CPR" in line.lower():
            print(f"  Found similar: '{line.strip()}'")
            print(f"  Bytes: {line.strip().encode()}")