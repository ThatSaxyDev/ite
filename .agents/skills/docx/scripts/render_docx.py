from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import subprocess
import tempfile


def main() -> int:
    parser = argparse.ArgumentParser(description="Render a DOCX file to page PNGs using LibreOffice and Poppler.")
    parser.add_argument("input", type=Path, help="Source .docx file")
    parser.add_argument("--output_dir", type=Path, required=True, help="Directory for rendered page images")
    parser.add_argument("--dpi", type=int, default=144, help="Rasterization DPI")
    args = parser.parse_args()

    for tool in ("soffice", "pdftoppm"):
        if shutil.which(tool) is None:
            raise SystemExit(f"missing required system tool: {tool}")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ite-docx-render-") as temp_dir:
        temp_root = Path(temp_dir)
        pdf_dir = temp_root / "pdf"
        pdf_dir.mkdir(parents=True, exist_ok=True)
        profile_dir = temp_root / "profile"
        profile_dir.mkdir(parents=True, exist_ok=True)

        subprocess.run(
            [
                "soffice",
                f"-env:UserInstallation=file://{profile_dir}",
                "--headless",
                "--convert-to",
                "pdf",
                "--outdir",
                str(pdf_dir),
                str(args.input),
            ],
            check=True,
            capture_output=True,
            text=True,
        )

        pdf_path = pdf_dir / f"{args.input.stem}.pdf"
        if not pdf_path.is_file():
            raise SystemExit("failed to produce an intermediate PDF")

        prefix = args.output_dir / "page"
        subprocess.run(
            [
                "pdftoppm",
                "-png",
                "-r",
                str(args.dpi),
                str(pdf_path),
                str(prefix),
            ],
            check=True,
            capture_output=True,
            text=True,
        )

    for path in sorted(args.output_dir.glob("page-*.png")):
        print(path.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
