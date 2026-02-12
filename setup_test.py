#!/usr/bin/env python3
"""
Quick setup validation — run this to verify everything is installed correctly.
Usage: python setup_test.py
"""

import sys
import importlib

def check(module, name):
    try:
        importlib.import_module(module)
        print(f"  ✅ {name}")
        return True
    except ImportError:
        print(f"  ❌ {name} — run: pip install {name.lower()}")
        return False

print("\n🔍 Checking dependencies...\n")
all_ok = True
all_ok &= check("requests", "Requests")
all_ok &= check("bs4", "BeautifulSoup4")
all_ok &= check("yaml", "PyYAML")
all_ok &= check("openpyxl", "Openpyxl")
all_ok &= check("sqlite3", "SQLite3 (built-in)")

if all_ok:
    print("\n✅ All dependencies installed!")
else:
    print("\n⚠️  Missing dependencies. Run: pip install -r requirements.txt")
    sys.exit(1)

# Test config loading
from pathlib import Path
config_path = Path(__file__).parent / "config.yaml"
if config_path.exists():
    import yaml
    with open(config_path) as f:
        config = yaml.safe_load(f)
    skills = config.get("skills", {}).get("primary", [])
    print(f"\n📋 Config loaded — {len(skills)} primary keywords configured")
    print(f"   Notification method: {config.get('notification', {}).get('method', 'console')}")
else:
    print(f"\n⚠️  Config not found at {config_path}")

# Test Excel detection
data_dir = Path(__file__).parent / "data"
xlsx_files = list(data_dir.glob("*.xlsx"))
if xlsx_files:
    print(f"\n📁 Found {len(xlsx_files)} Excel file(s) in data/:")
    for f in xlsx_files:
        print(f"   → {f.name}")
else:
    print(f"\n⚠️  No Excel files in data/ — copy your company Excel files there")

# Quick scraper test
print("\n🧪 Testing Greenhouse API (Anthropic careers)...")
try:
    import requests as req
    resp = req.get("https://boards-api.greenhouse.io/v1/boards/anthropic/jobs", timeout=10)
    if resp.status_code == 200:
        jobs = resp.json().get("jobs", [])
        print(f"   ✅ API works! Found {len(jobs)} jobs at Anthropic")
    else:
        print(f"   ⚠️  Got status {resp.status_code}")
except Exception as e:
    print(f"   ❌ Connection error: {e}")

print("\n🎉 Setup complete! Next steps:")
print("   1. Copy your company Excel files to the data/ folder")
print("   2. Edit config.yaml to customize skills & notifications")
print("   3. Run: python main.py --dry-run")
print()
