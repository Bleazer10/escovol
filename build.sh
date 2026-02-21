#!/usr/bin/env bash
set -o errexit

pip install -r requirements.txt
python manage.py collectstatic --no-input
python manage.py migrate
```

**PASO 6 — Agregar `.env` al `.gitignore`**

Asegúrate que tu `.gitignore` tenga estas líneas:
```
.env
*.pyc
__pycache__/
db.sqlite3
staticfiles/