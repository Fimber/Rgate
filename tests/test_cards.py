"""Result card templates and the "show positions" rule."""

import importlib.util
import unittest

from django.core.cache import cache
from django.test import TestCase

from results.models import ResultSheet
from results.services.cards import TEMPLATES, sample_snapshot
from results.services.pdf import build_result_pdf
from tests.factories import SchoolWorld

HAS_PYMUPDF = importlib.util.find_spec("pymupdf") is not None


def pdf_text(content):
    import pymupdf

    return pymupdf.open(stream=content, filetype="pdf")[0].get_text()


class CardTemplateTests(TestCase):
    def setUp(self):
        cache.clear()
        self.w = SchoolWorld("cards", students=2)
        self.sheet = self.w.publish()[0]
        self.url = self.w.url(f"portal/result/{self.sheet.id}/")
        self.client.force_login(self.w.parent)

    def test_each_template_renders_its_own_design(self):
        for key, _, _ in TEMPLATES:
            self.w.school.result_template = key
            self.w.school.save()
            self.assertContains(self.client.get(self.url), f"result-card tpl-{key}")

    def test_compact_drops_remark_and_class_average(self):
        self.w.school.result_template = "compact"
        self.w.school.save()
        response = self.client.get(self.url)
        self.assertNotContains(response, "<th>Remark</th>")
        self.assertNotContains(response, "<th>Class avg</th>")

    def test_positions_shown_by_default(self):
        response = self.client.get(self.url)
        self.assertContains(response, "<th>Pos</th>")
        self.assertContains(response, "Position<strong>")

    def test_positions_can_be_switched_off_everywhere(self):
        self.w.school.show_positions = False
        self.w.school.save()
        for response in (
            self.client.get(self.url),
            self.client.get(self.w.url(f"verify/{self.sheet.result_code}/")),
        ):
            self.assertNotContains(response, "<th>Pos</th>")
            self.assertNotContains(response, "Position<strong>")
        self.client.force_login(self.w.admin)
        transcript = self.client.get(self.w.url(f"app/transcripts/{self.w.student.id}/"))
        self.assertNotContains(transcript, "Position")

    def test_settings_toggle_and_cached_pdfs_are_rebuilt(self):
        self.client.get(self.w.url(f"portal/result/{self.sheet.id}/pdf/"))
        self.sheet.refresh_from_db()
        self.assertTrue(self.sheet.pdf_file)
        self.client.force_login(self.w.admin)
        self.client.post(self.w.url("app/settings/"), {"show_positions": ["0"], "result_template": "colour"})
        self.w.school.refresh_from_db()
        self.assertFalse(self.w.school.show_positions)
        self.assertEqual(self.w.school.result_template, "colour")
        self.assertFalse(ResultSheet.objects.get(pk=self.sheet.pk).pdf_file)
        self.client.post(self.w.url("app/settings/"), {"show_positions": ["0", "1"]})
        self.w.school.refresh_from_db()
        self.assertTrue(self.w.school.show_positions)

    def test_settings_page_shows_example_photos(self):
        self.client.force_login(self.w.admin)
        response = self.client.get(self.w.url("app/settings/"))
        for key, _, _ in TEMPLATES:
            self.assertContains(response, f"img/report-cards/{key}.png")


class CardPdfTests(TestCase):
    def test_every_template_builds(self):
        for key, _, _ in TEMPLATES:
            for show in (True, False):
                content = build_result_pdf(sample_snapshot(), "X", "v", template=key, show_positions=show)
                self.assertTrue(content.startswith(b"%PDF"))

    @unittest.skipUnless(HAS_PYMUPDF, "PyMuPDF not installed")
    def test_pdf_leaves_out_positions_when_switched_off(self):
        data = sample_snapshot()
        with_pos = pdf_text(build_result_pdf(data, "X", "v", show_positions=True))
        without = pdf_text(build_result_pdf(data, "X", "v", show_positions=False))
        self.assertIn("Position: 3rd of 34", with_pos)
        self.assertNotIn("Position", without)
        self.assertNotIn("12th", without)

    @unittest.skipUnless(HAS_PYMUPDF, "PyMuPDF not installed")
    def test_long_headings_fit(self):
        text = pdf_text(build_result_pdf(sample_snapshot(), "X", "v", template="colour"))
        self.assertIn("Assignment", text)
        self.assertIn("Christian Religious Studies", text)
