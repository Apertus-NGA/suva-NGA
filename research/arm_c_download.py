from huggingface_hub import snapshot_download
import re, pathlib
for m in ["BAAI/bge-m3", "intfloat/multilingual-e5-large-instruct"]:
    p = snapshot_download(m, ignore_patterns=["onnx/*", "*.onnx*", "openvino/*", "*.bin", "imgs/*", "*.jpg", "*.png", "*.webp"])
    rd = pathlib.Path(p, "README.md").read_text()[:3000]
    print(m, p, re.findall(r"license:\s*\S+", rd))
