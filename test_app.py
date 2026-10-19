import datetime
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import requests
from streamlit.testing.v1 import AppTest

import app

APP_PATH = Path(__file__).with_name("app.py")


class FetchLatestDriveIdTests(unittest.TestCase):
    @patch("app.requests.get")
    def test_highest_issue_is_selected_and_menu_drive_links_are_skipped(self, get):
        get.return_value.text = """
            <a href="https://drive.google.com/file/d/menu-file/view?usp=drive_link">גיליונות בעיצוב אישי</a>
            <a href="https://drive.google.com/file/d/calendar/view">לוח שנה תשפ"ו</a>
            <a href="https://drive.google.com/file/d/older/view"><img src="cover.png"></a>
            <a href="https://drive.google.com/file/d/older/view">גיליון משכן שילה 1039 - פרשת נח</a>
            <a href="https://drive.google.com/file/d/newest-123_abc/view?usp=drive_link">
                גיליון משכן שילה 1040 - פרשת לך לך
            </a>
            <a href="https://drive.google.com.example.com/file/d/fake/view">גיליון משכן שילה 9999</a>
        """

        self.assertEqual(app.fetch_latest_drive_id(), "newest-123_abc")
        get.assert_called_once_with(app.SOURCE_URL, timeout=app.REQUEST_TIMEOUT)
        get.return_value.raise_for_status.assert_called_once_with()

    @patch("app.requests.get")
    def test_missing_issue_drive_links_is_an_error(self, get):
        get.return_value.text = """
            <a href="https://drive.google.com/file/d/menu-file/view">גיליונות בעיצוב אישי</a>
            <a href="https://drive.google.com/folders/folder">גיליון משכן שילה 1040</a>
        """
        with self.assertRaises(ValueError):
            app.fetch_latest_drive_id()

    @patch("app.requests.get")
    def test_http_error_is_propagated(self, get):
        get.return_value.raise_for_status.side_effect = requests.HTTPError("503")
        with self.assertRaises(requests.HTTPError):
            app.fetch_latest_drive_id()


class PrepareAutoPdfTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.directory = Path(temp.name)
        for name in (
            "AUTO_REGULAR_PDF", "AUTO_REGULAR_BW_PDF",
            "AUTO_CUT_PDF", "AUTO_CUT_BW_PDF",
        ):
            self.mock_attribute(name, str(self.directory / f"{name}.pdf"))
            Path(getattr(app, name)).write_bytes(b"cached")

        self.config = {
            "source_url": app.SOURCE_URL,
            "last_drive_id": "existing",
            "last_title": "existing.pdf",
            "last_check_time": datetime.datetime.now().isoformat(),
        }
        self.mock_attribute("get_config", Mock(side_effect=lambda: self.config))
        self.save = self.mock_attribute("save_config", Mock())
        self.fetch = self.mock_attribute("fetch_latest_drive_id", Mock(return_value="existing"))
        self.download = self.mock_attribute("gdown.download", Mock())
        self.extract = self.mock_attribute("extract_pdf_by_images", Mock(return_value=True))
        self.convert = self.mock_attribute("convert_pdf_to_bw", Mock())
        self.split = self.mock_attribute("split_pdf_to_columns", Mock())

    def mock_attribute(self, name, value):
        patcher = patch(f"app.{name}", value)
        patcher.start()
        self.addCleanup(patcher.stop)
        return value

    def arrange_download(self):
        path = self.directory / "new.pdf"
        path.write_bytes(b"x" * 100001)
        self.download.return_value = str(path)

    def test_current_source_uses_cache_before_next_saturday(self):
        self.assertEqual(app.prepare_auto_pdf(), (True, None, "existing.pdf"))
        self.fetch.assert_not_called()
        self.download.assert_not_called()
        self.save.assert_not_called()

    def test_legacy_config_forces_source_migration_even_with_same_drive_id(self):
        del self.config["source_url"]
        self.config["last_post_id"] = 999999
        self.arrange_download()

        self.assertEqual(app.prepare_auto_pdf(), (True, None, "new.pdf"))
        self.fetch.assert_called_once_with()
        self.download.assert_called_once_with(id="existing", quiet=False, timeout=app.DOWNLOAD_TIMEOUT)
        saved = self.save.call_args.args[0]
        self.assertEqual(saved["source_url"], app.SOURCE_URL)
        self.assertEqual(saved["last_drive_id"], "existing")
        self.assertEqual(saved["last_title"], "new.pdf")
        self.extract.assert_called_once()
        self.assertEqual(self.convert.call_count, 2)
        self.split.assert_called_once()

    def test_unchanged_weekly_check_updates_timestamp_without_redownloading(self):
        self.config["last_check_time"] = "2020-01-01T10:00:00"

        self.assertEqual(app.prepare_auto_pdf(), (True, None, "existing.pdf"))
        self.fetch.assert_called_once_with()
        self.download.assert_not_called()
        saved = self.save.call_args.args[0]
        self.assertNotEqual(saved["last_check_time"], self.config["last_check_time"])
        self.assertEqual(saved["last_drive_id"], "existing")

    def test_new_issue_is_downloaded_and_saved(self):
        self.config["last_check_time"] = "2020-01-01T10:00:00"
        self.fetch.return_value = "newest"
        self.arrange_download()

        self.assertEqual(app.prepare_auto_pdf(), (True, None, "new.pdf"))
        self.download.assert_called_once_with(id="newest", quiet=False, timeout=app.DOWNLOAD_TIMEOUT)
        self.assertEqual(self.save.call_args.args[0]["last_drive_id"], "newest")

    def test_missing_local_pdf_fetches_latest_instead_of_using_stored_id(self):
        Path(app.AUTO_REGULAR_PDF).unlink()
        self.fetch.return_value = "newest"
        self.arrange_download()

        self.assertTrue(app.prepare_auto_pdf()[0])
        self.fetch.assert_called_once_with()
        self.download.assert_called_once_with(id="newest", quiet=False, timeout=app.DOWNLOAD_TIMEOUT)

    def test_empty_config_fetches_latest(self):
        self.config.clear()
        self.fetch.return_value = "newest"
        self.arrange_download()

        self.assertTrue(app.prepare_auto_pdf()[0])
        self.download.assert_called_once_with(id="newest", quiet=False, timeout=app.DOWNLOAD_TIMEOUT)
        self.assertEqual(self.save.call_args.args[0]["source_url"], app.SOURCE_URL)

    def test_source_errors_are_returned_without_advancing_check_time(self):
        self.config["last_check_time"] = "2020-01-01T10:00:00"
        for error in (requests.Timeout("timeout"), ValueError("missing link")):
            with self.subTest(error=error):
                self.fetch.side_effect = error
                success, message, title = app.prepare_auto_pdf()
                self.assertFalse(success)
                self.assertIn(str(error), message)
                self.assertIsNone(title)
                self.download.assert_not_called()
                self.save.assert_not_called()


    def test_gdown_retrieval_error_falls_back_then_reports_block(self):
        import gdown
        self.config.clear()
        self.fetch.return_value = "newest"
        self.download.side_effect = gdown.exceptions.FileURLRetrievalError("blocked")
        direct = self.mock_attribute("_download_drive_file_direct", Mock(side_effect=ValueError("quota")))

        success, message, title = app.prepare_auto_pdf()
        self.assertFalse(success)
        self.assertIn("quota", message)
        self.assertIsNone(title)
        direct.assert_called_once_with("newest")
        self.save.assert_not_called()

    def test_downloaded_file_is_removed_when_processing_raises(self):
        self.config.clear()
        self.fetch.return_value = "newest"
        self.arrange_download()
        self.extract.side_effect = RuntimeError("processing failed")

        with self.assertRaises(RuntimeError):
            app.prepare_auto_pdf()
        self.assertFalse(Path(self.download.return_value).exists())
        self.save.assert_not_called()


class AutomaticModeAppTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        previous_directory = os.getcwd()
        os.chdir(temp.name)
        self.addCleanup(os.chdir, previous_directory)

        page = Mock(text='<a href="https://drive.google.com/file/d/newest/view">גיליון משכן שילה 1040</a>')
        get_patcher = patch("requests.get", Mock(return_value=page))
        get_patcher.start()
        self.addCleanup(get_patcher.stop)
        self.download = Mock(side_effect=RuntimeError("Drive unavailable"))
        download_patcher = patch("gdown.download", self.download)
        download_patcher.start()
        self.addCleanup(download_patcher.stop)

    def test_first_load_failure_is_shown_instead_of_crashing_and_can_retry(self):
        at = AppTest.from_file(str(APP_PATH), default_timeout=30).run()

        self.assertEqual(len(at.exception), 0)
        self.assertIn("Drive unavailable", at.error[0].value)

        at.button(key="auto_retry").click().run()
        self.assertEqual(len(at.exception), 0)
        self.assertIn("Drive unavailable", at.error[0].value)
        self.assertEqual(self.download.call_count, 2)


class MarkerDetectionTests(unittest.TestCase):
    RENDER_SCALE = 1.2

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.directory = Path(temp.name)
        previous_directory = os.getcwd()
        os.chdir(APP_PATH.parent)
        self.addCleanup(os.chdir, previous_directory)

    def build_issue(self, start_marker):
        doc = app.fitz.open()
        for page_number in range(6):
            page = doc.new_page(width=623, height=884)
            page.insert_text((60, 400), f"page {page_number}", fontsize=30)
            marker = {2: start_marker, 4: app.END_IMAGE}.get(page_number)
            if marker:
                with app.fitz.open(marker) as image:
                    width, height = image[0].rect.width, image[0].rect.height
                page.insert_image(
                    app.fitz.Rect(60, 60, 60 + width / self.RENDER_SCALE, 60 + height / self.RENDER_SCALE),
                    filename=marker,
                )
        path = self.directory / f"{Path(start_marker).stem}.pdf"
        doc.save(path)
        doc.close()
        return path

    def test_old_and_new_start_markers_extract_marked_section(self):
        start_b64s, end_b64 = app.load_marker_images()
        for start_marker in app.START_IMAGES:
            with self.subTest(start_marker=start_marker):
                output = self.directory / f"{Path(start_marker).stem}_out.pdf"
                self.assertTrue(app.extract_pdf_by_images(str(self.build_issue(start_marker)), str(output), start_b64s, end_b64))
                with app.fitz.open(output) as doc:
                    self.assertEqual([page.get_text().strip() for page in doc], ["page 2", "page 3", "page 4"])


if __name__ == "__main__":
    unittest.main()
