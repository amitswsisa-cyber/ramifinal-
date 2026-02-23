"""
scripts/office/pack.py
Repack an unpacked DOCX directory back into a .docx file.
Preserves the original zip structure (content types, relationships, etc.)

Usage:
    python pack.py unpacked_dir/ output.docx
    # or import and call pack(src_dir, dst_docx)
"""
import sys
import zipfile
import os


def pack(src_dir: str, dst_docx: str) -> None:
    """
    Zip up src_dir into dst_docx.
    Uses ZIP_DEFLATED compression — matches what Word produces.
    Files are added relative to src_dir (no leading path components).
    """
    # Ensure parent directory exists
    parent = os.path.dirname(dst_docx)
    if parent:
        os.makedirs(parent, exist_ok=True)

    with zipfile.ZipFile(dst_docx, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for root, _dirs, files in os.walk(src_dir):
            for fname in files:
                full_path = os.path.join(root, fname)
                # Archive name = relative path from src_dir
                arcname = os.path.relpath(full_path, src_dir).replace("\\", "/")
                zf.write(full_path, arcname)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: pack.py <unpacked_dir> <output.docx>")
        sys.exit(1)
    pack(sys.argv[1], sys.argv[2])
    print(f"Packed to {sys.argv[2]}")
