"""注文入力パネル。"""

from __future__ import annotations

from PySide6 import QtCore, QtWidgets


class OrderPanel(QtWidgets.QWidget):
    order_requested = QtCore.Signal(str, str, int, float)

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        root = QtWidgets.QVBoxLayout(self)
        root.addWidget(QtWidgets.QLabel("注文"))

        form = QtWidgets.QFormLayout()
        self.side_combo = QtWidgets.QComboBox()
        self.side_combo.addItem("買い", "BUY")
        self.side_combo.addItem("売り", "SELL")
        self.type_combo = QtWidgets.QComboBox()
        self.type_combo.addItem("成行", "MARKET")
        self.type_combo.addItem("指値", "LIMIT")
        self.quantity_spin = QtWidgets.QSpinBox()
        self.quantity_spin.setRange(1, 1_000_000_000)
        self.quantity_spin.setValue(100)
        self.limit_spin = QtWidgets.QDoubleSpinBox()
        self.limit_spin.setDecimals(4)
        self.limit_spin.setRange(0.0001, 1_000_000_000)
        self.limit_spin.setSingleStep(1.0)
        self.limit_spin.setEnabled(False)
        form.addRow("売買", self.side_combo)
        form.addRow("注文種別", self.type_combo)
        form.addRow("数量", self.quantity_spin)
        form.addRow("指値価格", self.limit_spin)
        root.addLayout(form)

        self.submit_button = QtWidgets.QPushButton("注文する")
        self.submit_button.setMinimumHeight(36)
        root.addWidget(self.submit_button)
        root.addStretch(1)

        self.type_combo.currentIndexChanged.connect(self._update_limit_enabled)
        self.submit_button.clicked.connect(self._submit)

    def _update_limit_enabled(self) -> None:
        self.limit_spin.setEnabled(self.type_combo.currentData() == "LIMIT")

    def _submit(self) -> None:
        order_type = str(self.type_combo.currentData())
        limit_price = float(self.limit_spin.value()) if order_type == "LIMIT" else 0.0
        self.order_requested.emit(
            str(self.side_combo.currentData()),
            order_type,
            int(self.quantity_spin.value()),
            limit_price,
        )
