"""Regenerate the example report-card photos shown in setup and settings.

    python manage.py render_card_examples

Needs PyMuPDF (in requirements-dev.txt) to turn the PDFs into PNGs.
"""

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from results.services.cards import TEMPLATES, sample_snapshot
from results.services.pdf import build_result_pdf

OUT = Path(settings.BASE_DIR) / "static" / "img" / "report-cards"


class Command(BaseCommand):
    help = "Render example result cards for each template to static/img/report-cards/."

    def add_arguments(self, parser):
        parser.add_argument("--dpi", type=int, default=110)

    def handle(self, *args, **options):
        try:
            import pymupdf
        except ImportError as exc:
            raise CommandError("Install PyMuPDF first: pip install -r requirements-dev.txt") from exc
        OUT.mkdir(parents=True, exist_ok=True)
        data = sample_snapshot()
        variants = [(key, True, key) for key, _, _ in TEMPLATES] + [("classic", False, "no-positions")]
        for template, show_positions, name in variants:
            content = build_result_pdf(
                data,
                data["result_code"],
                "regate.ng/greenfield/verify/SAMPLE7KQ4MX/",
                template=template,
                show_positions=show_positions,
            )
            page = pymupdf.open(stream=content, filetype="pdf")[0]
            target = OUT / f"{name}.png"
            page.get_pixmap(dpi=options["dpi"]).save(target)
            self.stdout.write(f"wrote {target.relative_to(settings.BASE_DIR)}")
