"""插件开发示例：展示如何创建 UI 页面和实现生命周期方法。

本模块演示：
1. QWidget 子类的基本结构
2. `shutdown()` 和 `wait_for_shutdown()` 生命周期契约
3. 简单交互逻辑（无需后台线程）

页面生命周期契约：
- `shutdown() -> bool`：请求停止后台任务，返回是否已停止
- `wait_for_shutdown() -> None`：阻塞等待所有后台任务完成
MainWindow 退出时会调用这两个方法。
"""

from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget


class DemoHelloPage(QWidget):
    """示例页面：点击按钮计数，展示基本交互。

    无后台线程，shutdown 立即返回 True。
    """

    def __init__(self) -> None:
        super().__init__()
        self._count = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(34, 26, 34, 24)
        layout.setSpacing(14)

        title = QLabel("插件开发示例")
        title.setStyleSheet("font-size: 21px; font-weight: 700; color: #17212b;")
        layout.addWidget(title)

        hint = QLabel(
            "<b>本项目是开源项目，欢迎各位开发者进群交流一起维护&贡献代码，也欢迎各位同学进群或在 issues 中提出问题和建议。</b>"
            "这是最小可运行的插件模板。\n"

        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #667783; font-size: 13px;")
        layout.addWidget(hint)

        self._status_label = QLabel("点击次数：0")
        self._status_label.setStyleSheet("font-size: 15px; color: #17212b;")
        layout.addWidget(self._status_label)

        self._click_button = QPushButton("点我计数")
        self._click_button.setStyleSheet("padding: 8px 16px;")
        self._click_button.clicked.connect(self._on_click)
        layout.addWidget(self._click_button)

        layout.addStretch(1)

    def _on_click(self) -> None:
        """按钮点击回调，更新计数显示。"""
        self._count += 1
        self._status_label.setText(f"点击次数：{self._count}")

    def shutdown(self) -> bool:
        """请求停止后台任务。无后台任务，立即返回 True。"""
        return True

    def wait_for_shutdown(self) -> None:
        """阻塞等待后台任务完成。无后台任务，立即返回。"""
