# -*- coding: utf-8 -*-
"""The self-contained preview player used by the main window."""

import os

from mutagen import File as MutagenFile
from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
from PyQt6.QtWidgets import QGroupBox, QHBoxLayout, QLabel, QPushButton, QSlider, QVBoxLayout


class AudioPlayerWidget(QGroupBox):
    def __init__(self, parent=None):
        super().__init__("试听", parent)
        self.setFixedHeight(80)

        self.audio_output = QAudioOutput(self)
        self.player = QMediaPlayer(self)
        self.player.setAudioOutput(self.audio_output)
        self.player.positionChanged.connect(self._on_position_changed)
        self.player.durationChanged.connect(self._on_duration_changed)
        self.player.playbackStateChanged.connect(self._on_state_changed)

        player_layout = QVBoxLayout(self)
        player_layout.setContentsMargins(8, 7, 8, 7)
        player_layout.setSpacing(4)
        player_row = QHBoxLayout()
        player_row.setContentsMargins(0, 0, 0, 0)
        self.track_label = QLabel("未载入单曲")
        self.track_label.setStyleSheet("color: #34495e; font-size: 9pt;")
        self.track_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.track_label.setMinimumWidth(0)
        self.play_button = QPushButton("▶️")
        self.play_button.setFixedSize(28, 24)
        self.play_button.setToolTip("播放 / 暂停")
        self.play_button.clicked.connect(self._toggle_playback)
        self.stop_button = QPushButton("⏹️")
        self.stop_button.setFixedSize(28, 24)
        self.stop_button.setToolTip("停止")
        self.stop_button.clicked.connect(self.stop)
        player_row.addWidget(self.track_label, stretch=1)
        player_row.addWidget(self.play_button)
        player_row.addWidget(self.stop_button)

        progress_row = QHBoxLayout()
        progress_row.setContentsMargins(0, 0, 0, 0)
        self.time_label = QLabel("0:00 / 0:00")
        self.time_label.setFixedWidth(72)
        self.time_label.setStyleSheet("color: #7f8c8d; font-size: 8pt;")
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 0)
        self.slider.sliderMoved.connect(self.player.setPosition)
        progress_row.addWidget(self.slider, stretch=1)
        progress_row.addWidget(self.time_label)
        player_layout.addLayout(player_row)
        player_layout.addLayout(progress_row)

    def load_track(self, path):
        if not path or not os.path.isfile(path):
            return
        source = QUrl.fromLocalFile(path)
        if self.player.source() != source:
            self.stop()
            self.player.setSource(source)
            duration = self._read_audio_duration(path)
            self.slider.setRange(0, duration)
            self.time_label.setText(f"0:00 / {self._format_time(duration)}")
        self.track_label.setText(os.path.basename(path))
        self.track_label.setToolTip(path)

    def stop(self):
        self.player.stop()
        self.player.setPosition(0)
        self.slider.setValue(0)
        self.time_label.setText(
            f"0:00 / {self._format_time(self.slider.maximum())}"
        )

    def clear(self):
        self.stop()
        self.player.setSource(QUrl())
        self.slider.setRange(0, 0)
        self.time_label.setText("0:00 / 0:00")
        self.track_label.setText("未载入单曲")
        self.track_label.setToolTip("")

    @staticmethod
    def _format_time(milliseconds):
        seconds = max(0, milliseconds // 1000)
        return f"{seconds // 60}:{seconds % 60:02d}"

    @staticmethod
    def _read_audio_duration(path):
        try:
            audio = MutagenFile(path)
            if audio is not None and getattr(audio, "info", None) is not None:
                return max(0, round(audio.info.length * 1000))
        except Exception:
            pass
        return 0

    def _toggle_playback(self):
        if not self.player.source().isValid():
            return
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def _on_position_changed(self, position):
        if not self.slider.isSliderDown():
            self.slider.setValue(position)
        self.time_label.setText(
            f"{self._format_time(position)} / {self._format_time(self.player.duration())}"
        )

    def _on_duration_changed(self, duration):
        self.slider.setRange(0, max(0, duration))

    def _on_state_changed(self, state):
        self.play_button.setText(
            "⏸️" if state == QMediaPlayer.PlaybackState.PlayingState else "▶️"
        )
