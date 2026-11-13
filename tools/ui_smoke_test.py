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
    window.navigate_to_stage(4)
    window.flux_calculate_btn.click()
    results = window.flux_density_page_ui.flux_results
    _require(results and results['flux_densities'])
    _require(window.flux_export_all_btn.isEnabled())

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

    # Exercise preparation in its worker thread, real Qt scene playback and cache reuse.
    controller = window.flux_density_page_ui
    window.navigate_to_stage(4)
    original_wt = window.connection_tab.mmf_calculator.wt_angle_deg
    window.flux_anim_visualization_type.setCurrentIndex(2)
    controller.prepare_animation_frames()
    loop = QEventLoop()
    controller._animation_worker.finished.connect(loop.quit)
    QTimer.singleShot(45000, loop.quit)
    loop.exec()
    app.processEvents()
    _require(controller.animation_model is not None)
    _require(window.connection_tab.mmf_calculator.wt_angle_deg == original_wt)
    model = controller.animation_model
    render_times = []
    for angle in np.arange(0, 360, 3):
        started = time.perf_counter()
        controller._render_animation_angle(float(angle))
        app.processEvents()
        render_times.append(time.perf_counter() - started)
    controller.play_animation()
    _require(controller.animation_timer.isActive())
    controller.pause_animation()
    _require(not controller.animation_timer.isActive())
    window.flux_tabs.setCurrentIndex(2)
    controller._render_animation_angle(47.0)
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
        window.flux_anim_pg_widget.set_model(model, mode)
        window.flux_anim_pg_widget.show_angle(47)
        app.processEvents()
        window.grab().save(str(output / ('animation-' + mode.replace(' ', '-').lower() + '.png')))
    controller.prepare_animation_frames()
    _require(controller.animation_model is model)
    _require(controller._animation_worker is None)
    animation = {'generation_seconds': model.generation_seconds,
                 'storage_bytes': model.storage_bytes,
                 'mean_frame_ms': 1000*float(np.mean(render_times)),
                 'p95_frame_ms': 1000*float(np.percentile(render_times, 95)),
                 'frames_rendered': len(render_times),
                 'worker_responsive': True, 'cache_reused': True}

    window.meshing_page_ui.invalidate_mesh()
    _require(not window.navigation_buttons[4].isEnabled())
    _require(window.current_stage() == 3)
    _require(not window.navigation_buttons[4].isEnabled())
    summary = {
        'qt_binding': 'PyQt6', 'frozen': bool(getattr(sys, 'frozen', False)),
        'mesh_elements': len(results['flux_densities']), 'animation': animation,
        'screenshots': captures, 'clipped_buttons': clipping,
        'checks': ['direct navigation', 'mesh prerequisite', 'mesh generation',
                   'field solve', 'export enabled', 'mesh invalidation',
                   'desktop and minimum-size layouts'],
    }
    (output / 'smoke-test.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    window.close()
    if clipping:
        raise RuntimeError('Clipped controls: ' + '; '.join(clipping))
    return 0
