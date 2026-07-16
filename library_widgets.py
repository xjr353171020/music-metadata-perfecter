# -*- coding: utf-8 -*-
"""Standalone widgets used by the library pane."""

from PyQt6.QtCore import QAbstractAnimation, QEvent, QEasingCurve, QPoint, QPropertyAnimation, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPolygon
from PyQt6.QtWidgets import QComboBox, QLabel, QListWidget, QWidget


class TouchComboBox(QComboBox):
    """Editable combo box with a consistently visible high-DPI drop-down arrow."""

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor("#7f8c8d") if not self.isEnabled() else QColor("#34495e")
        center_x = self.width() - 14
        center_y = self.height() // 2 + 1
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawPolygon(QPolygon([
            QPoint(center_x - 5, center_y - 3),
            QPoint(center_x + 5, center_y - 3),
            QPoint(center_x, center_y + 3),
        ]))


class FileListOverlayContainer(QWidget):
    """Hosts the file list and fixed overlay controls outside its scroll viewport."""

    resized = pyqtSignal()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.resized.emit()


class TouchSafeFileList(QListWidget):
    """Keep touch scrolling from turning a finger swipe into range selection."""

    drag_threshold = 12
    ANGLE_STEP_DISTANCE = 108
    PIXEL_DELTA_MULTIPLIER = 1.1
    WHEEL_MIN_DURATION_MS = 80
    WHEEL_MAX_DURATION_MS = 180

    def __init__(self, parent=None):
        super().__init__(parent)
        self._press_position = None
        self._selection_before_press = []
        self._current_before_press = None
        self._is_scrolling_gesture = False
        self._scroll_animation = QPropertyAnimation(self.verticalScrollBar(), b"value", self)
        self._scroll_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.verticalScrollBar().sliderPressed.connect(self.cancel_smooth_scroll)
        self.verticalScrollBar().sliderMoved.connect(self.cancel_smooth_scroll)
        self.viewport().setAttribute(Qt.WidgetAttribute.WA_AcceptTouchEvents, True)

    def smooth_scroll_to_item(self, item, hint=QListWidget.ScrollHint.PositionAtCenter):
        """Animate programmatic list movement without affecting selection."""
        if item is None:
            return
        if self._is_scroller_active():
            self.scrollToItem(item, hint)
            return
        bar = self.verticalScrollBar()
        start = bar.value()
        target = self._scroll_target_for_item(item, hint)
        if target == start:
            return
        self.cancel_smooth_scroll()
        distance = abs(target - start)
        self._scroll_animation.setDuration(min(420, max(110, 110 + distance // 3)))
        self._scroll_animation.setStartValue(start)
        self._scroll_animation.setEndValue(target)
        self._scroll_animation.start()

    def smooth_scroll_by(self, delta, duration_limit=320):
        if not delta:
            return
        if self._is_scroller_active():
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() + delta)
            return
        bar = self.verticalScrollBar()
        target = max(bar.minimum(), min(bar.maximum(), bar.value() + delta))
        self.cancel_smooth_scroll()
        self._scroll_animation.setDuration(
            min(
                duration_limit,
                max(
                    self.WHEEL_MIN_DURATION_MS,
                    self.WHEEL_MIN_DURATION_MS + abs(target - bar.value()) // 3,
                ),
            )
        )
        self._scroll_animation.setStartValue(bar.value())
        self._scroll_animation.setEndValue(target)
        self._scroll_animation.start()

    def cancel_smooth_scroll(self):
        if self._scroll_animation.state() != QAbstractAnimation.State.Stopped:
            self._scroll_animation.stop()

    def wheelEvent(self, event):
        self.cancel_smooth_scroll()
        if self._is_scroller_active():
            super().wheelEvent(event)
            return
        pixel_delta = event.pixelDelta().y()
        if pixel_delta:
            distance = int(round(-pixel_delta * self.PIXEL_DELTA_MULTIPLIER))
            self.smooth_scroll_by(distance, self.WHEEL_MAX_DURATION_MS)
            event.accept()
            return
        angle_delta = event.angleDelta().y()
        if angle_delta:
            steps = angle_delta / 120
            distance = int(round(-steps * self.ANGLE_STEP_DISTANCE))
            self.smooth_scroll_by(distance, self.WHEEL_MAX_DURATION_MS)
            event.accept()
            return
        super().wheelEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (
            Qt.Key.Key_Up,
            Qt.Key.Key_Down,
            Qt.Key.Key_PageUp,
            Qt.Key.Key_PageDown,
            Qt.Key.Key_Home,
            Qt.Key.Key_End,
        ):
            self.cancel_smooth_scroll()
        super().keyPressEvent(event)

    def _scroll_target_for_item(self, item, hint):
        bar = self.verticalScrollBar()
        item_rect = self.visualItemRect(item)
        viewport_height = self.viewport().height()
        if hint == QListWidget.ScrollHint.PositionAtTop:
            offset = item_rect.top()
        elif hint == QListWidget.ScrollHint.PositionAtBottom:
            offset = item_rect.bottom() - viewport_height + 1
        else:
            offset = item_rect.center().y() - viewport_height // 2
        return max(bar.minimum(), min(bar.maximum(), bar.value() + offset))

    def _is_scroller_active(self):
        # Scroller state is queried lazily to preserve normal mouse-wheel use.
        from PyQt6.QtWidgets import QScroller
        return QScroller.scroller(self.viewport()).state() != QScroller.State.Inactive

    def mousePressEvent(self, event):
        self._press_position = event.position()
        self._is_scrolling_gesture = False
        self._remember_selection()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._press_position and (event.position() - self._press_position).manhattanLength() >= self.drag_threshold:
            self._is_scrolling_gesture = True
            self._restore_selection()
            event.ignore()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._is_scrolling_gesture:
            self._restore_selection()
            event.ignore()
            self._clear_gesture_state()
            return
        super().mouseReleaseEvent(event)
        self._clear_gesture_state()

    def viewportEvent(self, event):
        if event.type() == QEvent.Type.TouchBegin:
            point = event.points()[0].position() if event.points() else QPoint()
            self._press_position = point
            self._is_scrolling_gesture = False
            self._remember_selection()
        elif event.type() == QEvent.Type.TouchUpdate and self._press_position and event.points():
            if (event.points()[0].position() - self._press_position).manhattanLength() >= self.drag_threshold:
                self._is_scrolling_gesture = True
                self._restore_selection()
        elif event.type() in (QEvent.Type.TouchEnd, QEvent.Type.TouchCancel):
            if self._is_scrolling_gesture:
                self._restore_selection()
            QTimer.singleShot(0, self._clear_gesture_state)
        return super().viewportEvent(event)

    def _remember_selection(self):
        self._selection_before_press = self.selectedItems()
        self._current_before_press = self.currentItem()

    def _restore_selection(self):
        self.blockSignals(True)
        self.clearSelection()
        for item in self._selection_before_press:
            item.setSelected(True)
        if self._current_before_press:
            self.setCurrentItem(self._current_before_press)
        self.blockSignals(False)

    def _clear_gesture_state(self):
        self._press_position = None
        self._is_scrolling_gesture = False


class AlbumIndexLetter(QLabel):
    """A hover-only album index entry that leaves list selection unchanged."""

    hovered = pyqtSignal(str)
    hover_left = pyqtSignal(str)

    def __init__(self, letter, parent=None):
        super().__init__(letter, parent)
        self.letter = letter
        self.is_available = False
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(f"跳转到 {letter} 开头的专辑")
        self.set_available(False)

    def set_available(self, available):
        self.is_available = available
        color = "#2980b9" if available else "#bdc3c7"
        weight = "bold" if available else "normal"
        self.setStyleSheet(
            "QLabel {"
            f"color: {color}; font-size: 7pt; font-weight: {weight}; "
            "background: transparent;"
            "}"
        )

    def enterEvent(self, event):
        if self.is_available:
            self.hovered.emit(self.letter)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.hover_left.emit(self.letter)
        super().leaveEvent(event)
