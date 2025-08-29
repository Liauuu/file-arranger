import yaml

with open("rules.example.yml", "r", encoding="utf-8") as f:
    data = yaml.safe_load(f)

print(data)

