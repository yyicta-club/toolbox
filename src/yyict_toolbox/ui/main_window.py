from collections.abc import Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from yyict_toolbox.plugins.specs import ToolDescriptor


class MainWindow(QMainWindow):
    def __init__(self, tools: Sequence[ToolDescriptor]) -> None:
        super().__init__()
        self._tools = list(tools)
        self._tool_buttons: dict[str, QPushButton] = {}
        self.setWindowTitle("校园工具箱")
        self.setMinimumSize(760, 520)
        self.resize(960, 640)
        self.setStyleSheet(
            """
            QMainWindow, QWidget#root { background: #f5f7f8; color: #17212b; }
            QWidget#sidebar { background: #ffffff; border-right: 1px solid #e2e8ec; }
            QLabel#brand { color: #173b4d; font-size: 17px; font-weight: 700; }
            QLabel#eyebrow { color: #60717d; font-size: 11px; font-weight: 700; }
            QLabel#pageTitle { color: #17212b; font-size: 23px; font-weight: 700; }
            QLabel#muted { color: #667783; font-size: 13px; }
            QLabel#state { color: #8a4b12; background: #fff2df; border: 1px solid #f1d3aa;
                           border-radius: 4px; padding: 5px 9px; font-weight: 600; }
            QPushButton#toolButton { text-align: left; padding: 10px 12px; border: 0;
                                     border-radius: 5px; color: #40515d; font-size: 13px; }
            QPushButton#toolButton:hover { background: #f0f5f7; }
            QPushButton#toolButton:checked { background: #e6f2f2; color: #12615e;
                                             font-weight: 600; }
            QFrame#separator { background: #e2e8ec; border: 0; max-height: 1px; }
            """
        )

        root = QWidget(objectName="root")
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._build_sidebar())
        layout.addWidget(self._build_content(), 1)
        self.setCentralWidget(root)

        if self._tools:
            self._select_tool(self._tools[0].id)

    def _build_sidebar(self) -> QWidget:
        sidebar = QWidget(objectName="sidebar")
        sidebar.setFixedWidth(228)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(18, 20, 14, 16)
        layout.setSpacing(8)

        brand = QLabel("校园工具箱", objectName="brand")
        layout.addWidget(brand)
        layout.addSpacing(22)
        layout.addWidget(QLabel("工具", objectName="eyebrow"))
        layout.addSpacing(5)

        for tool in self._tools:
            button = QPushButton(tool.name, objectName="toolButton")
            button.setCheckable(True)
            button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DriveNetIcon))
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            button.clicked.connect(lambda checked=False, tool_id=tool.id: self._select_tool(tool_id))
            layout.addWidget(button)
            self._tool_buttons[tool.id] = button

        layout.addStretch(1)
        layout.addWidget(QLabel("YYICT TOOLBOX  ·  0.1.0", objectName="muted"))
        return sidebar

    def _build_content(self) -> QWidget:
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(34, 28, 34, 28)
        layout.setSpacing(0)

        top = QHBoxLayout()
        section = QLabel("工具箱  /  功能")
        section.setObjectName("muted")
        top.addWidget(section)
        top.addStretch(1)
        self._state_label = QLabel("尚未实现", objectName="state")
        top.addWidget(self._state_label)
        layout.addLayout(top)
        layout.addSpacing(28)

        heading = QHBoxLayout()
        icon = QLabel()
        icon.setFixedSize(42, 42)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet("background:#e6f2f2; border-radius:6px; color:#12615e;")
        icon.setPixmap(self.style().standardIcon(QStyle.StandardPixmap.SP_DriveNetIcon).pixmap(22, 22))
        heading.addWidget(icon)
        heading.addSpacing(14)
        title_group = QVBoxLayout()
        self._title_label = QLabel("校园网自动登录", objectName="pageTitle")
        self._description_label = QLabel("校园网络连接工具", objectName="muted")
        title_group.addWidget(self._title_label)
        title_group.addWidget(self._description_label)
        heading.addLayout(title_group)
        heading.addStretch(1)
        layout.addLayout(heading)
        layout.addSpacing(24)

        separator = QFrame(objectName="separator")
        separator.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(separator)
        layout.addSpacing(24)

        self._empty_label = QLabel("该工具尚未实现", objectName="muted")
        layout.addWidget(self._empty_label)
        layout.addStretch(1)
        return content

    def _select_tool(self, tool_id: str) -> None:
        tool = next((item for item in self._tools if item.id == tool_id), None)
        if tool is None:
            return
        for current_id, button in self._tool_buttons.items():
            button.setChecked(current_id == tool_id)
        self._title_label.setText(tool.name)
        self._description_label.setText(tool.description)
        self._state_label.setText("可用" if tool.available else "尚未实现")
        self._state_label.setStyleSheet(
            "" if not tool.available else "color:#176247; background:#e5f4ed; border-color:#b8dfca;"
        )
        self._empty_label.setText("" if tool.available else "该工具尚未实现")
