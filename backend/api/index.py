import os
import sys

# Ensure the backend root is on sys.path so `app.main` is importable
# when Vercel runs this from api/index.py (backend root is the project root).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.main import app

# Vercel's @vercel/python builder exports this as the ASGI handler.
handler = app
