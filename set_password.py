"""
Set or reset a login password without touching the app.

Usage:
    python set_password.py natasha "HerNewPassword123"

This updates config.yaml in place with a fresh bcrypt hash for that username.
Run it whenever you add a new person or someone forgets their password.
"""
import sys
from pathlib import Path

import bcrypt
import yaml

BASE = Path(__file__).parent
CONFIG = BASE / "config.yaml"


def main() -> None:
    if len(sys.argv) != 3:
        print('Usage: python set_password.py <username> "<new password>"')
        sys.exit(1)

    username, new_pw = sys.argv[1], sys.argv[2]
    with open(CONFIG) as f:
        config = yaml.load(f, Loader=yaml.SafeLoader)

    users = config["credentials"]["usernames"]
    if username not in users:
        print(f'User "{username}" not found. Existing users: {", ".join(users)}')
        sys.exit(1)

    users[username]["password"] = bcrypt.hashpw(new_pw.encode(), bcrypt.gensalt()).decode()
    with open(CONFIG, "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)

    print(f'✅ Password updated for "{username}".')


if __name__ == "__main__":
    main()
