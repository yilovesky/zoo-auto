# zoo-auto

Automates Zo email-link login using Gmail IMAP and a Gmail app password.

## What it does

1. Triggers a Zo login email for your address
2. Connects to Gmail over IMAP using your Gmail app password
3. Finds the newest Zo login email
4. Extracts the real `https://www.zo.computer/api/email-login/verify?...` link
5. Opens that link in your default browser, or prints it

## Files

- `login_zo.py` — main script
- `tests/test_login_zo.py` — parser tests
- `.env.example` — environment variable template
- `requirements-dev.txt` — test dependency

## Requirements

- Python 3.10+
- A Gmail account with IMAP enabled
- A Gmail app password

## Configure

Copy `.env.example` into your shell environment or a local `.env` file you do **not** commit.

Example:

```bash
export GMAIL_USER='yilovesky520@gmail.com'
export GMAIL_APP_PASSWORD='your_gmail_app_password_here'
```

## Usage

Print the Zo magic link without opening a browser:

```bash
python3 login_zo.py --no-browser
```

Trigger the email, fetch the newest Zo magic link, and open it in the default browser:

```bash
python3 login_zo.py
```

Use a custom timeout while waiting for the email:

```bash
python3 login_zo.py --timeout 180
```

Use explicit credentials instead of environment variables:

```bash
python3 login_zo.py --email 'yilovesky520@gmail.com' --app-password 'YOUR_APP_PASSWORD'
```

## Test

```bash
python3 -m pip install --user -r requirements-dev.txt
python3 -m pytest tests/test_login_zo.py -q
```

## Notes

- The script reads only the mailbox needed to find the Zo login email.
- Zo login links expire quickly, so the script fetches the newest matching message.
- If Zo changes its email format, update the regexes in `login_zo.py` and re-run tests.
