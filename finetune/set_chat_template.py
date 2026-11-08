"""Copy a GGUF with the thinking-off chat template (prompts.NO_THINK_CHAT_TEMPLATE) embedded.

Why: Ollama 0.40 renders Qwen3 with the Jinja template stored inside the GGUF and ignores a Modelfile
TEMPLATE; Qwen3's own template thinks unless the client sends enable_thinking=false, which the app's
OpenAI-compatible requests can't. With this template the served prompt equals the training prompt.

Usage (from the repo root, in a venv with `pip install -r finetune/requirements-local.txt`):

    # base model: take qwen3:1.7b's GGUF from your Ollama store (run `ollama pull qwen3:1.7b` first)
    python finetune/set_chat_template.py --from-ollama qwen3:1.7b finetune/study-buddy-qwen-base-q4_k_m.gguf

    # any GGUF file (the notebook already embeds the template in the fine-tuned GGUF)
    python finetune/set_chat_template.py in.gguf out.gguf

The output is a new file; the input is never modified.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from prompts import NO_THINK_CHAT_TEMPLATE  # noqa: E402


def ollama_gguf_path(model: str, ollama: str = "ollama") -> Path:
    """The GGUF blob behind an Ollama model (the FROM line of `ollama show --modelfile`)."""
    exe = shutil.which(ollama) or ollama
    out = subprocess.run([exe, "show", model, "--modelfile"], capture_output=True, text=True, check=True).stdout
    m = re.search(r"^FROM\s+(.+)$", out, re.MULTILINE)
    if not m:
        raise SystemExit(f"no FROM line in `ollama show {model} --modelfile`")
    path = Path(m.group(1).strip())
    if not path.is_file():
        raise SystemExit(f"{path} is not a file (is {model} pulled?)")
    return path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", nargs="?", help="input GGUF (or use --from-ollama)")
    ap.add_argument("output", help="output GGUF (a new file)")
    ap.add_argument("--from-ollama", metavar="MODEL", help="read the GGUF of a pulled Ollama model, e.g. qwen3:1.7b")
    ap.add_argument("--ollama", default="ollama", help="path of the ollama executable if it isn't on PATH")
    args = ap.parse_args(argv)

    src = ollama_gguf_path(args.from_ollama, args.ollama) if args.from_ollama else Path(args.input or "")
    if not src.is_file():
        ap.error("give an input GGUF or --from-ollama MODEL")
    dst = Path(args.output)
    if dst.resolve() == src.resolve():
        ap.error("output must be a different file from the input")
    dst.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        tpl = Path(tmp) / "chat_template.jinja"
        tpl.write_text(NO_THINK_CHAT_TEMPLATE, encoding="utf-8")
        cmd = [sys.executable, "-m", "gguf.scripts.gguf_new_metadata", "--chat-template-file", str(tpl), "--force",
               str(src), str(dst)]
        print("source:", src)
        subprocess.run(cmd, check=True)

    from gguf import GGUFReader  # noqa: PLC0415 - verify what was written

    field = GGUFReader(str(dst)).get_field("tokenizer.chat_template")
    written = field.contents() if field is not None else None
    if written != NO_THINK_CHAT_TEMPLATE:
        raise SystemExit("the chat template in the output doesn't match prompts.NO_THINK_CHAT_TEMPLATE")
    print(f"wrote {dst} with the thinking-off chat template")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
