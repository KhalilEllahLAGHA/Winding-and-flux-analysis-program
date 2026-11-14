"""Exercise the real Qt pages and solver in both source and standalone builds."""

import json
import os
from pathlib import Path
import sys
import time

from PyQt6.QtGui import QFontDatabase
from PyQt6.QtCore import QEventLoop, QTimer
from PyQt6.QtWidgets import QApplication, QPushButton
import numpy as np


def _require(condition):
    if not condition:
        raise RuntimeError('Desktop workflow check failed.')


def _wait_until(predicate, timeout_ms=45000):
    if predicate():
        return
    loop = QEventLoop()
    poll, timeout = QTimer(), QTimer()
    poll.timeout.connect(lambda: loop.quit() if predicate() else None)
    timeout.setSingleShot(True)
    timeout.timeout.connect(loop.quit)
    poll.start(10)
    timeout.start(timeout_ms)
    loop.exec()
    poll.stop()
    timeout.stop()
    _require(predicate())


def load_preview_fonts():
    # Qt's Windows offscreen plugin does not enumerate system fonts itself.
    # Load installed fonts only for previews; no Windows fonts are distributed.
    fonts = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts'
    for name in ('segoeui.ttf', 'segoeuib.ttf', 'seguisym.ttf', 'consola.ttf'):
        if (fonts / name).is_file():
            QFontDatabase.addApplicationFont(str(fonts / name))


def run_smoke_test(window, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance()
    window.resize(1440, 960)
    window.show()
    app.processEvents()
    _require(window.current_stage() == 0)
    _require(not window.navigation_buttons[4].isEnabled())
    window.navigate_to_stage(4)
    _require(window.current_stage() == 0)

    window.navigate_to_stage(3)
    window.mesh_preset.setCurrentIndex(1)
    window.generate_mesh_btn.click()
    _require(window.meshing_page_ui.mesh_data is not None)
    _require(window.navigation_buttons[4].isEnabled())
    controller = window.flux_density_page_ui
    original_wt = window.connection_tab.mmf_calculator.wt_angle_deg
    heartbeats = []
    heartbeat = QTimer()
    heartbeat.timeout.connect(lambda: heartbeats.append(time.perf_counter()))
    heartbeat.start(5)
    _wait_until(lambda: controller.animation_model is not None
                and controller._animation_worker is None)
    heartbeat.stop()
    window.navigate_to_stage(4)
    _require(not controller.animation_timer.isActive())
    _require(window.flux_play_anim_btn.text() == 'Play')
    _require(not any(button.text() in ('Pause', 'Stop')
                    for button in window.findChildren(QPushButton)))
    results = controller.flux_results
    _require(results and results['flux_densities'])
    _require(window.flux_export_all_btn.isEnabled())
    _require(window.connection_tab.mmf_calculator.wt_angle_deg == original_wt)
    _require(heartbeats)
    _require(not any(button.isVisibleTo(window) and button.text() in
                    ('Solve field', 'Refresh view', 'Prepare animation')
                    for button in window.findChildren(QPushButton)))

    # Compare windings at one electrical angle using the prepared machine response.
    mesh = window.meshing_page_ui.mesh_data
    window.flux_anim_wt_spin.setValue(47.25)
    for control, value in ((window.flux_anim_span_spin, 7),
                           (window.flux_anim_phases_spin, 9),
                           (window.flux_anim_layer_combo, 'Single layer'),
                           (window.flux_anim_layer_combo, 'Double layer'),
                           (window.flux_anim_phases_spin, 3),
                           (window.flux_anim_span_spin, 9)):
        previous = controller.animation_model
        if isinstance(value, str):
            control.setCurrentText(value)
        else:
            control.setValue(value)
        _wait_until(lambda: controller.animation_model is not None
                    and controller.animation_model is not previous
                    and controller._animation_worker is None)
        _require(window.meshing_page_ui.mesh_data is mesh)
        _require(abs(controller._animation_angle - 47.25) < 1e-8)
        _require(not controller.animation_timer.isActive())
        _require(controller.animation_model.network_reused)
        _require(controller.animation_model.direct_winding_updates)
    _require(window.phases_spin.value() == window.flux_anim_phases_spin.value() == 3)
    _require(window.span_spin.value() == window.flux_anim_span_spin.value() == 9)
    _require(window.double_layer.isChecked())
    cached_model = controller.animation_model
    window.flux_restart_anim_btn.click()
    _require(controller._animation_angle == window.flux_anim_wt_spin.value() == 0)
    _require(controller.animation_model is cached_model)
    _require(controller._animation_worker is None)
    _require(not controller.animation_timer.isActive())

    captures = []
    clipping = []
    for width, height in ((1440, 960), (1200, 760)):
        window.resize(width, height)
        for stage in range(5):
            window.navigate_to_stage(stage)
            app.processEvents()
            path = output / f'{width}-{stage + 1:02d}.png'
            _require(window.grab().save(str(path)))
            captures.append(path.name)
            for button in window.findChildren(QPushButton):
                if button.isVisibleTo(window) and button.text():
                    required = button.fontMetrics().horizontalAdvance(button.text())
                    if required > button.width() - 8:
                        clipping.append(f'{width}: {button.text()} ({button.width()}px)')

    # Preparation is automatic; display changes and arrow visibility reuse it.
    window.navigate_to_stage(4)
    window.flux_visualization_type.setCurrentIndex(2)
    app.processEvents()
    model = controller.animation_model
    _require(controller._animation_worker is None)
    window.flux_show_arrows_check.setChecked(False)
    app.processEvents()
    _require(not window.flux_anim_pg_widget.arrows.isVisible())
    _require(controller.animation_model is model)
    window.flux_show_arrows_check.setChecked(True)
    app.processEvents()
    _require(window.flux_anim_pg_widget.arrows.isVisible())
    render_times = []
    for angle in np.arange(0, 360, 3):
        started = time.perf_counter()
        controller._render_animation_angle(float(angle))
        app.processEvents()
        render_times.append(time.perf_counter() - started)
    window.flux_play_anim_btn.click()
    _require(controller.animation_timer.isActive())
    _require(window.flux_play_anim_btn.text() == 'Pause')
    window.flux_play_anim_btn.click()
    _require(not controller.animation_timer.isActive())
    _require(window.flux_play_anim_btn.text() == 'Play')
    window.flux_tabs.setCurrentIndex(0)
    window.flux_anim_wt_spin.setValue(47.0)
    app.processEvents()
    window.grab().save(str(output / 'animation-combined.png'))
    radius = model.outer_radius
    bounds = window.flux_anim_pg_widget.image.mapRectToParent(
        window.flux_anim_pg_widget.image.boundingRect())
    _require(abs(bounds.left() + radius) < 1e-6 and abs(bounds.right() - radius) < 1e-6)
    window.settings_toggle.click()
    app.processEvents()
    window.grab().save(str(output / 'animation-full-width.png'))
    window.settings_toggle.click()
    for mode in ('B Heatmap', 'Flux Lines'):
        window.flux_visualization_type.setCurrentText(mode)
        controller._render_animation_angle(47)
        app.processEvents()
        _require(controller.animation_model is model)
        _require(controller._animation_worker is None)
        window.grab().save(str(output / ('animation-' + mode.replace(' ', '-').lower() + '.png')))
    controller.prepare_animation_frames()
    _require(controller.animation_model is model)
    _require(controller._animation_worker is None)
    animation = {'generation_seconds': model.generation_seconds,
                 'storage_bytes': model.storage_bytes,
                 'mean_frame_ms': 1000*float(np.mean(render_times)),
                 'p95_frame_ms': 1000*float(np.percentile(render_times, 95)),
                 'frames_rendered': len(render_times),
                 'worker_responsive': bool(heartbeats), 'cache_reused': True,
                 'automatic_preparation': True, 'arrow_toggle': True,
                 'paused_initially': True, 'play_pause_toggle': True,
                 'winding_controls': True, 'prepared_winding_response': True, 'wt_seek': True, 'restart': True}

    window.meshing_page_ui.invalidate_mesh()
    _require(not window.navigation_buttons[4].isEnabled())
    _require(window.current_stage() == 3)
    _require(not window.navigation_buttons[4].isEnabled())
    summary = {
        'qt_binding': 'PyQt6', 'frozen': bool(getattr(sys, 'frozen', False)),
        'mesh_elements': len(results['flux_densities']), 'animation': animation,
        'screenshots': captures, 'clipped_buttons': clipping,
        'checks': ['direct navigation', 'mesh prerequisite', 'mesh generation',
                   'automatic field preparation', 'arrow visibility',
                   'paused initial view', 'single play/pause button',
                   'winding comparison without solving', 'Wt seek and restart',
                   'export enabled', 'mesh invalidation',
                   'desktop and minimum-size layouts'],
    }
    (output / 'smoke-test.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    window.close()
    if clipping:
        raise RuntimeError('Clipped controls: ' + '; '.join(clipping))
    return 0
