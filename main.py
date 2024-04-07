import sys
import os
import pathlib

import libWiiPy

from PySide6.QtWidgets import QApplication, QMainWindow, QFileDialog, QMessageBox
from PySide6.QtCore import QRunnable, Slot, QThreadPool, Signal, QObject, Qt

from qt.py.ui_MainMenu import Ui_MainWindow


class WorkerSignals(QObject):
    result = Signal(int)
    progress = Signal(str)


class Worker(QRunnable):
    def __init__(self, fn, **kwargs):
        super(Worker, self).__init__()
        self.fn = fn
        self.kwargs = kwargs
        self.signals = WorkerSignals()

        self.kwargs['progress_callback'] = self.signals.progress

    @Slot()
    def run(self):
        try:
            self.fn(**self.kwargs)
        except ValueError:
            self.signals.result.emit(1)
        else:
            self.signals.result.emit(0)


class MainWindow(QMainWindow, Ui_MainWindow):
    def __init__(self):
        super(MainWindow, self).__init__()
        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)
        self.log_text = ""
        self.threadpool = QThreadPool()
        self.ui.download_btn.clicked.connect(self.download_btn_pressed)
        self.ui.pack_wad_chkbox.clicked.connect(self.pack_wad_chkbox_toggled)

    def update_log_text(self, new_text):
        self.log_text += new_text + "\n"
        self.ui.log_text_browser.setText(self.log_text)
        # Always auto-scroll to the bottom of the log.
        scrollBar = self.ui.log_text_browser.verticalScrollBar()
        scrollBar.setValue(scrollBar.maximum())

    def download_btn_pressed(self):
        self.ui.download_btn.setEnabled(False)
        self.log_text = ""
        self.ui.log_text_browser.setText(self.log_text)

        worker = Worker(self.run_nus_download)
        worker.signals.result.connect(self.check_download_result)
        worker.signals.progress.connect(self.update_log_text)

        self.threadpool.start(worker)

    def check_download_result(self, result):
        if result == 1:
            msgBox = QMessageBox()
            msgBox.setWindowTitle("Invalid Title ID/Version")
            msgBox.setIcon(QMessageBox.Icon.Critical)
            msgBox.setTextFormat(Qt.MarkdownText)
            msgBox.setText("### No title with the requested Title ID or version could be found!")
            msgBox.setInformativeText("Please make sure the Title ID is entered correctly, and if a specific version is"
                                      " set, that it exists for the chosen title.")
            msgBox.setStandardButtons(QMessageBox.StandardButton.Ok)
            msgBox.setDefaultButton(QMessageBox.StandardButton.Ok)
            msgBox.exec()
        self.ui.download_btn.setEnabled(True)

    def run_nus_download(self, progress_callback):
        tid = self.ui.tid_entry.text()
        try:
            version = int(self.ui.version_entry.text())
        except ValueError:
            version = None

        title = libWiiPy.Title()

        title_dir = pathlib.Path(os.path.join(out_folder, tid))
        if not title_dir.is_dir():
            title_dir.mkdir()

        if version is not None:
            progress_callback.emit("Downloading title " + tid + " v" + str(version) + ", please wait...")
        else:
            progress_callback.emit("Downloading title " + tid + " vLatest, please wait...")

        progress_callback.emit(" - Downloading and parsing TMD...")
        if version is not None:
            title.load_tmd(libWiiPy.download_tmd(tid, version))
        else:
            title.load_tmd(libWiiPy.download_tmd(tid))
            version = title.tmd.title_version

        version_dir = pathlib.Path(os.path.join(title_dir, str(version)))
        if not version_dir.is_dir():
            version_dir.mkdir()

        tmd_out = open(os.path.join(version_dir, "tmd." + str(version)), "wb")
        tmd_out.write(title.tmd.dump())
        tmd_out.close()

        progress_callback.emit(" - Downloading and parsing Ticket...")
        title.load_ticket(libWiiPy.download_ticket(tid))
        ticket_out = open(os.path.join(version_dir, "tik"), "wb")
        ticket_out.write(title.ticket.dump())
        ticket_out.close()

        title.load_content_records()
        content_list = []
        for content in range(len(title.tmd.content_records)):
            progress_callback.emit(" - Downloading content " + str(content + 1) + " of " +
                                   str(len(title.tmd.content_records)) + " (" +
                                   str(title.tmd.content_records[content].content_size) + " bytes)...")
            content_list.append(libWiiPy.download_content(tid, title.tmd.content_records[content].content_id))
            progress_callback.emit("  - Done!")
            if self.ui.keep_enc_chkbox.isChecked() is True:
                content_id_hex = hex(title.tmd.content_records[content].content_id)[2:]
                if len(content_id_hex) < 2:
                    content_id_hex = "0" + content_id_hex
                content_file_name = "000000" + content_id_hex
                enc_content_out = open(os.path.join(version_dir, content_file_name), "wb")
                enc_content_out.write(content_list[content])
                enc_content_out.close()
        title.content.content_list = content_list

        if self.ui.create_dec_chkbox.isChecked() is True:
            for content in range(len(title.tmd.content_records)):
                progress_callback.emit(" - Decrypting content " + str(content + 1) + " of " +
                                       str(len(title.tmd.content_records)) + "...")
                dec_content = title.get_content_by_index(content)
                content_id_hex = hex(title.tmd.content_records[content].content_id)[2:]
                if len(content_id_hex) < 2:
                    content_id_hex = "0" + content_id_hex
                content_file_name = "000000" + content_id_hex + ".app"
                dec_content_out = open(os.path.join(version_dir, content_file_name), "wb")
                dec_content_out.write(dec_content)
                dec_content_out.close()

        if self.ui.pack_wad_chkbox.isChecked() is True:
            progress_callback.emit(" - Building certificate...")
            title.wad.set_cert_data(libWiiPy.download_cert())

            progress_callback.emit("Packing WAD...")
            if self.ui.wad_file_entry.text() != "":
                wad_file_name = self.ui.wad_file_entry.text()
                if wad_file_name[-4:] != ".wad":
                    wad_file_name = wad_file_name + ".wad"
            else:
                wad_file_name = tid + "-v" + str(version) + ".wad"
            file = open(os.path.join(version_dir, wad_file_name), "wb")
            file.write(title.dump_wad())
            file.close()

        progress_callback.emit("Download complete!")

    def pack_wad_chkbox_toggled(self):
        if self.ui.pack_wad_chkbox.isChecked() is True:
            self.ui.wad_file_entry.setEnabled(True)
        else:
            self.ui.wad_file_entry.setEnabled(False)


if __name__ == "__main__":
    app = QApplication(sys.argv)

    out_folder = pathlib.Path("titles")
    if not out_folder.is_dir():
        out_folder.mkdir()

    window = MainWindow()
    window.setWindowTitle("NUSD-Py")
    window.show()

    sys.exit(app.exec())
