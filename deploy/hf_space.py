"""Create (if needed) and update the Hugging Face Docker Space from ./backend."""
import os
import shutil
import tempfile
from pathlib import Path

from huggingface_hub import HfApi

space = os.environ["HF_SPACE"]
api = HfApi(token=os.environ["HF_TOKEN"])
api.create_repo(space, repo_type="space", space_sdk="docker", exist_ok=True, private=False)

root = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory() as tmp:
    dst = Path(tmp)
    shutil.copytree(root / "backend", dst, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("tests", "__pycache__", ".pytest_cache"))
    (dst / "README.md").write_text(
        "---\n"
        "title: HindiDub\n"
        "emoji: 🎬\n"
        "colorFrom: yellow\n"
        "colorTo: green\n"
        "sdk: docker\n"
        "app_port: 7860\n"
        "pinned: false\n"
        "---\n\n"
        "HindiDub backend: English video -> Hindi dub with consistent per-character voices.\n"
    )
    api.upload_folder(folder_path=str(dst), repo_id=space, repo_type="space",
                      commit_message="Deploy HindiDub backend", delete_patterns=["*"])
host = space.lower().replace("/", "-").replace("_", "-").replace(".", "-")
print(f"Deployed. API URL: https://{host}.hf.space")
