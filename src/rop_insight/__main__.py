"""Application entry point."""

import sys

from PyQt6.QtWidgets import QApplication

from rop_insight.ui.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("ROP-Insight")
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
