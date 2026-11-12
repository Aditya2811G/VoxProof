"""Local development entry point: python run.py"""
import os

from dotenv import load_dotenv

load_dotenv()

from app.main import create_app  # noqa: E402

app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    print(f"\n  VoxProof running at http://localhost:{port}\n")
    app.run(host="0.0.0.0", port=port, debug=os.environ.get("FLASK_DEBUG") == "1")
