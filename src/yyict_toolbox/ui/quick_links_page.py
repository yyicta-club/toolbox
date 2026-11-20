from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QVBoxLayout, QWidget


QUICK_LINKS: tuple[tuple[str, str], ...] = (
    ("学校官网", "https://www.jxyy.edu.cn/"),
    ("数字校园", "https://cas.jxyy.edu.cn/lyuapServer/login"),
    ("教务系统", "https://jw.jxyy.edu.cn:9002/jwglxt"),
)


class QuickLinksPage(QWidget):
    """展示内置校园链接，通过系统默认浏览器打开网站。"""

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(34, 26, 34, 24)
        layout.setSpacing(14)

        title = QLabel("快捷链接面板")
        title.setStyleSheet("font-size: 21px; font-weight: 700; color: #17212b;")
        layout.addWidget(title)
        hint = QLabel("点击网站名称，在系统默认浏览器中打开。")
        hint.setWordWrap(True)
        hint.setObjectName("muted")
        layout.addWidget(hint)

        for name, url in QUICK_LINKS:
            card = QFrame()
            card.setObjectName("quickLinkCard")
            card.setStyleSheet(
                "QFrame#quickLinkCard { background: #ffffff;"
                " border: 1px solid #e2e8ec; border-radius: 8px; }"
            )
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(16, 12, 16, 12)
            button = QPushButton(name)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setToolTip(url)
            button.setStyleSheet(
                "QPushButton { text-align: left; border: none; color: #12615e;"
                " font-size: 16px; font-weight: 600; padding: 4px 0; }"
                "QPushButton:hover { color: #173b4d; text-decoration: underline; }"
            )
            button.clicked.connect(
                lambda checked=False, link_url=url: self._open_link(link_url)
            )
            card_layout.addWidget(button)
            address = QLabel(url)
            address.setObjectName("muted")
            address.setWordWrap(True)
            address.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            card_layout.addWidget(address)
            layout.addWidget(card)

        self._status_label = QLabel()
        self._status_label.setWordWrap(True)
        self._status_label.setStyleSheet("color: #a53b32; font-size: 13px;")
        layout.addWidget(self._status_label)
        layout.addStretch(1)

    def _open_link(self, url: str) -> None:
        if QDesktopServices.openUrl(QUrl(url)):
            self._status_label.clear()
        else:
            self._status_label.setText("无法打开浏览器，请复制上方地址到浏览器中访问。")

    def shutdown(self) -> bool:
        """页面没有后台任务，可以立即关闭。"""
        return True

    def wait_for_shutdown(self) -> None:
        """页面没有后台任务，无需等待。"""
